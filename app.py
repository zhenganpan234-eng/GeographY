import math
from flask import Flask, render_template, request, redirect, url_for, flash
from src.api_client import CATEGORY_STAY_MINUTES, get_geocode, get_exploration_waypoints, get_route_matrix_v2, round_to_5
from src.map_builder import build_soul_map
from src.route_stats import compute_route_stats
from src.saved_routes import find_saved_route, load_saved_routes, save_route, delete_route
from src.custom_places import add_custom_place, delete_custom_place, load_custom_places
from src.place_memory import (
    block_place,
    clear_memory_list,
    like_place,
    load_place_memory,
    mark_visited,
    memory_sets,
    remove_place,
)

app = Flask(__name__)
app.secret_key = "soulpath-secret-key"
LATEST_ROUTE_CONTEXT = None


def estimate_walking_minutes(distance_m):
    walk_speed_m_per_min = 70
    campus_factor = 1.4
    return max(1, math.ceil((distance_m or 0) / walk_speed_m_per_min * campus_factor))


def _parse_relaxation_hours(value):
    try:
        hours = float(value)
    except (TypeError, ValueError):
        hours = 1.0
    hours = max(0, hours)
    return hours, max(1, round(hours * 60))


def _parse_walk_limit(value):
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = 12
    return max(1, minutes)


def _parse_selected_coords(lon_value=None, lat_value=None):
    try:
        lon = float(lon_value)
        lat = float(lat_value)
    except (TypeError, ValueError):
        return None
    if -180 <= lon <= 180 and -90 <= lat <= 90:
        return [lon, lat]
    return None


def _snapshot_context(context):
    snapshot_keys = [
        "start_coords", "end_coords", "route_data", "waypoints", "route_segments",
        "distance", "duration", "walking_minutes", "stay_minutes", "buffer_minutes",
        "relaxation_hours", "relaxation_minutes", "max_walk_minutes", "time_budget",
        "mode_name", "start_place", "social_energy", "mood", "exploration_mode",
        "environment_preference", "stats",
    ]
    return {key: context.get(key) for key in snapshot_keys if key in context}


def _build_route_segments(route_data, waypoint_details, mode_name):
    stops = [{"name": "出發地", "stay_minutes": 0}] + waypoint_details + [
        {"name": "回到起點附近", "stay_minutes": 0}
    ]
    legs = route_data.get("legs") or []
    leg_geometries = route_data.get("leg_geometries") or []
    segments = []
    for idx in range(len(stops) - 1):
        raw_distance = 0
        if idx < len(legs):
            raw_distance = legs[idx].get("distance", 0)
        walking_minutes = estimate_walking_minutes(raw_distance)
        segments.append({
            "from": stops[idx]["name"],
            "to": stops[idx + 1]["name"],
            "walking_minutes": walking_minutes,
            "distance_m": raw_distance,
            "distance_km": round(raw_distance / 1000, 2),
            "mode_name": mode_name,
            "geometry": leg_geometries[idx] if idx < len(leg_geometries) else [],
        })
    return segments


def _route_breaks_walk_limit(route_segments, max_walk_minutes):
    return any(segment["walking_minutes"] > max_walk_minutes for segment in route_segments)


def _expand_stay_time(waypoint_details, extra_minutes, deep_cap_minutes=None):
    if extra_minutes <= 0 or not waypoint_details:
        return 0
    added = 0
    while added < extra_minutes:
        changed = False
        for waypoint in waypoint_details:
            category = waypoint.get("category") or waypoint.get("type")
            default_max = CATEGORY_STAY_MINUTES.get(category, (15, 35))[1]
            max_stay = waypoint.get("max_stay_minutes") or default_max
            if deep_cap_minutes is not None:
                max_stay = max(max_stay, min(deep_cap_minutes, default_max + 30, 90))
            current = int(waypoint.get("stay_minutes", 0))
            remaining = extra_minutes - added
            if current < max_stay and remaining >= 5:
                step = min(5, max_stay - current)
                waypoint["stay_minutes"] = current + step
                added += step
                changed = True
        if not changed:
            break
    return added


def _annotate_liked_places(itinerary):
    memory = memory_sets(load_place_memory())
    liked_place_names = memory.get("liked", set())
    for item in itinerary:
        if item.get("kind") == "place":
            item["is_liked"] = _place_key(item.get("name")) in liked_place_names
    return itinerary


def _compute_time_totals(waypoint_details, walking_minutes, relaxation_minutes):
    stay_minutes = sum(int(wp.get("stay_minutes", 0)) for wp in waypoint_details)
    max_buffer_minutes = min(8, max(3, round(relaxation_minutes * 0.06)))
    buffer_minutes = min(max_buffer_minutes, max(0, relaxation_minutes - walking_minutes - stay_minutes))
    total_minutes = walking_minutes + stay_minutes + buffer_minutes
    return stay_minutes, buffer_minutes, total_minutes


def _build_itinerary(start_place, waypoint_details, route_segments):
    itinerary = [{"kind": "place", "name": start_place or "出發地", "label": "出發地"}]
    for idx, waypoint in enumerate(waypoint_details):
        if idx < len(route_segments):
            itinerary.append({
                "kind": "walk",
                "walking_minutes": route_segments[idx]["walking_minutes"],
                "distance_km": route_segments[idx].get("distance_km", 0),
            })
        itinerary.append({
            "kind": "place",
            "waypoint_index": idx,
            "name": waypoint["name"],
            "label": waypoint.get("category") or waypoint.get("type", ""),
            "stay_minutes": waypoint.get("stay_minutes"),
            "recommendation_reason": waypoint.get("recommendation_reason", ""),
            "category": waypoint.get("category") or waypoint.get("type", ""),
            "coords": waypoint.get("coords", []),
        })
    if route_segments:
        itinerary.append({
            "kind": "walk",
            "walking_minutes": route_segments[-1]["walking_minutes"],
            "distance_km": route_segments[-1].get("distance_km", 0),
        })
    itinerary.append({"kind": "place", "name": "回到起點附近", "label": "終點"})
    return itinerary


def _place_key(name):
    return (name or "").strip().lower()


def _route_context(**kwargs):
    kwargs.setdefault("custom_places", load_custom_places())
    return kwargs


def _hydrate_route_context(snapshot):
    if not snapshot or not snapshot.get("route_data"):
        return None
    waypoint_details = snapshot.get("waypoints") or []
    route_segments = snapshot.get("route_segments") or []
    social_energy = snapshot.get("social_energy", "80")
    mood = snapshot.get("mood", "放鬆")
    route_data = snapshot["route_data"]
    map_html = build_soul_map(
        route_data.get("geometry", []), social_energy, waypoint_details, mood, route_segments
    )
    itinerary = _build_itinerary(snapshot.get("start_place", ""), waypoint_details, route_segments)
    itinerary = _annotate_liked_places(itinerary)
    context = dict(snapshot)
    context.update({
        "map_html": map_html,
        "itinerary": itinerary,
        "waypoints": waypoint_details,
        "route_segments": route_segments,
        "custom_places": load_custom_places(),
    })
    return context


def _refresh_route_context(waypoint_details):
    global LATEST_ROUTE_CONTEXT
    if not LATEST_ROUTE_CONTEXT:
        return False
    start_coords = LATEST_ROUTE_CONTEXT.get("start_coords")
    end_coords = LATEST_ROUTE_CONTEXT.get("end_coords") or start_coords
    if not start_coords:
        return False
    route_data = get_route_matrix_v2(
        start_coords,
        end_coords,
        [wp["coords"] for wp in waypoint_details],
        optimize=False,
    )
    if not route_data:
        return False
    social_energy = LATEST_ROUTE_CONTEXT.get("social_energy", "80")
    mood = LATEST_ROUTE_CONTEXT.get("mood", "放鬆")
    mode_name = LATEST_ROUTE_CONTEXT.get("mode_name", "SoulPath 路線")
    route_segments = _build_route_segments(route_data, waypoint_details, mode_name)
    walking_minutes = sum(segment["walking_minutes"] for segment in route_segments)
    base_stay_minutes = sum(int(wp.get("stay_minutes", 0)) for wp in waypoint_details)
    relaxation_minutes = int(LATEST_ROUTE_CONTEXT.get("relaxation_minutes") or walking_minutes + base_stay_minutes)
    stay_minutes, buffer_minutes, total_minutes = _compute_time_totals(
        waypoint_details, walking_minutes, relaxation_minutes
    )
    km_distance = round(route_data["distance"] / 1000, 2)
    itinerary = _build_itinerary(
        LATEST_ROUTE_CONTEXT.get("start_place", ""),
        waypoint_details,
        route_segments,
    )
    itinerary = _annotate_liked_places(itinerary)
    LATEST_ROUTE_CONTEXT.update({
        "map_html": build_soul_map(route_data["geometry"], social_energy, waypoint_details, mood, route_segments),
        "route_data": route_data,
        "distance": km_distance,
        "duration": total_minutes,
        "walking_minutes": walking_minutes,
        "stay_minutes": stay_minutes,
        "buffer_minutes": buffer_minutes,
        "time_budget": {
            "total": total_minutes,
            "walking": walking_minutes,
            "stay": stay_minutes,
            "buffer": buffer_minutes,
        },
        "waypoints": waypoint_details,
        "route_segments": route_segments,
        "itinerary": itinerary,
        "stats": compute_route_stats(waypoint_details, social_energy, mood, km_distance, walking_minutes),
    })
    return True


@app.route('/')
def home():
    if LATEST_ROUTE_CONTEXT and not request.args:
        return render_template('index.html', **LATEST_ROUTE_CONTEXT)
    return render_template(
        'index.html',
        start_place=request.args.get('start', ''),
        relaxation_hours=request.args.get('hours', request.args.get('minutes', '1')),
        max_walk_minutes=request.args.get('walk', '12'),
        custom_places=load_custom_places(),
        social_energy=request.args.get('energy', '80'),
        mood=request.args.get('mood', '放鬆'),
        exploration_mode=request.args.get('mode', '平衡模式'),
        environment_preference=request.args.get('env', '不限'),
    )


def _generate_route_context(start_place, relaxation_hours, relaxation_minutes, social_energy, mood, exploration_mode, environment_preference, max_walk_minutes, selected_start_coords=None):
    start_coords = selected_start_coords or get_geocode(start_place)
    end_coords = start_coords

    if not start_coords:
        return None, f"找不到「{start_place}」的位置，請重新輸入！"

    place_memory = load_place_memory()
    memory = memory_sets(place_memory)
    waypoint_details, time_budget = get_exploration_waypoints(
        start_coords, mood, social_energy, relaxation_minutes, memory, exploration_mode,
        max_walk_minutes, environment_preference
    )
    waypoints_coords = [wp['coords'] for wp in waypoint_details]
    route_data = get_route_matrix_v2(start_coords, end_coords, waypoints_coords)

    while route_data and waypoint_details:
        preview_segments = _build_route_segments(route_data, waypoint_details, "SoulPath")
        walking_preview = sum(segment["walking_minutes"] for segment in preview_segments)
        stay_preview = sum(int(wp.get('stay_minutes', 0)) for wp in waypoint_details)
        route_tolerance = max(10, round(relaxation_minutes * 0.10))
        if (
            walking_preview + stay_preview <= relaxation_minutes + route_tolerance
            and not _route_breaks_walk_limit(preview_segments, max_walk_minutes)
        ):
            break
        waypoint_details.sort(key=lambda wp: wp.get('score', 0), reverse=True)
        waypoint_details.pop()
        if not waypoint_details:
            route_data = None
            break
        waypoints_coords = [wp['coords'] for wp in waypoint_details]
        route_data = get_route_matrix_v2(start_coords, end_coords, waypoints_coords)

    if not route_data:
        return None, "無法生成療癒探索路線，請延長放鬆時間或更換出發地點！"

    opt_order = route_data.get('optimized_order', [])
    if opt_order:
        waypoint_details = [waypoint_details[i - 1] for i in opt_order]

    km_distance = round(route_data['distance'] / 1000, 2)
    if int(social_energy) < 40:
        mode_name = "低社交能量療癒探索"
    else:
        mode_names = {
            "放鬆": "時間型放鬆探索",
            "文青": "文青慢逛探索",
            "探索": "城市小角落探索",
            "社交": "熱鬧能量探索",
            "療癒": "心靈療癒漫步",
        }
        mode_name = mode_names.get(mood, "SoulPath 路線")

    route_segments = _build_route_segments(route_data, waypoint_details, mode_name)
    walking_minutes = sum(segment["walking_minutes"] for segment in route_segments)
    for waypoint in waypoint_details:
        waypoint["stay_minutes"] = round_to_5(int(waypoint.get("stay_minutes", 0)))
    stay_minutes, buffer_minutes, total_minutes = _compute_time_totals(
        waypoint_details, walking_minutes, relaxation_minutes
    )
    time_budget.update({
        "total": total_minutes,
        "walking": walking_minutes,
        "stay": stay_minutes,
        "buffer": buffer_minutes,
    })

    stats = compute_route_stats(
        waypoint_details, social_energy, mood, km_distance, walking_minutes
    )
    itinerary = _build_itinerary(start_place, waypoint_details, route_segments)
    itinerary = _annotate_liked_places(itinerary)
    map_html = build_soul_map(
        route_data['geometry'], social_energy, waypoint_details, mood, route_segments
    )
    mark_visited(waypoint_details)

    return _route_context(
        map_html=map_html,
        start_coords=start_coords,
        end_coords=end_coords,
        route_data=route_data,
        distance=km_distance,
        duration=total_minutes,
        walking_minutes=walking_minutes,
        stay_minutes=stay_minutes,
        buffer_minutes=buffer_minutes,
        relaxation_hours=relaxation_hours,
        relaxation_minutes=relaxation_minutes,
        max_walk_minutes=max_walk_minutes,
        time_budget=time_budget,
        mode_name=mode_name,
        start_place=start_place,
        social_energy=social_energy,
        mood=mood,
        exploration_mode=exploration_mode,
        environment_preference=environment_preference,
        waypoints=waypoint_details,
        route_segments=route_segments,
        itinerary=itinerary,
        stats=stats,
    ), None


@app.route('/search', methods=['POST'])
def search():
    global LATEST_ROUTE_CONTEXT
    start_place = request.form.get('start_place')
    selected_start_coords = _parse_selected_coords(
        request.form.get("selected_start_lon"),
        request.form.get("selected_start_lat"),
    )
    relaxation_hours, relaxation_minutes = _parse_relaxation_hours(
        request.form.get('relaxation_hours', '1')
    )
    social_energy = request.form.get('social_energy', '80')
    mood = request.form.get('mood', '放鬆')
    exploration_mode = request.form.get('exploration_mode', '平衡模式')
    environment_preference = request.form.get('environment_preference', '不限')
    max_walk_minutes = _parse_walk_limit(request.form.get('max_walk_minutes', '12'))

    context, error = _generate_route_context(
        start_place, relaxation_hours, relaxation_minutes, social_energy, mood,
        exploration_mode, environment_preference, max_walk_minutes, selected_start_coords
    )
    if error:
        return render_template(
            'index.html',
            error=error,
            start_place=start_place,
            relaxation_hours=relaxation_hours,
            relaxation_minutes=relaxation_minutes,
            max_walk_minutes=max_walk_minutes,
            custom_places=load_custom_places(),
            social_energy=social_energy,
            mood=mood,
            exploration_mode=exploration_mode,
            environment_preference=environment_preference,
        )
    LATEST_ROUTE_CONTEXT = context
    return render_template('index.html', **context)


@app.route('/save', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/save/', methods=['GET', 'POST', 'OPTIONS'])
def save():
    """收藏當前路線"""
    global LATEST_ROUTE_CONTEXT
    if request.method == "OPTIONS":
        return ("", 204)
    start_place   = request.values.get('start_place')
    if not start_place:
        flash("目前沒有可收藏的路線，請先生成路線。", "info")
        return redirect(url_for('home'))
    end_place     = request.values.get('end_place') or "回到起點附近"
    mood          = request.values.get('mood')
    social_energy = request.values.get('social_energy')
    exploration_mode = request.values.get('exploration_mode') or "平衡模式"
    environment_preference = request.values.get('environment_preference') or "不限"
    distance      = request.values.get('distance') or 0
    duration      = request.values.get('duration') or 0
    relaxation_hours = request.values.get('relaxation_hours') or "1"
    max_walk_minutes = request.values.get('max_walk_minutes') or "12"
    relaxation_minutes = request.values.get('relaxation_minutes') or duration
    waypoints_raw = request.values.get('waypoints_names', '')
    waypoints = [{"name": n} for n in waypoints_raw.split("||") if n]

    snapshot = _snapshot_context(LATEST_ROUTE_CONTEXT or {})
    save_route(start_place, end_place, mood, social_energy,
               float(distance), int(duration), waypoints, int(relaxation_minutes), exploration_mode,
               int(max_walk_minutes), environment_preference, float(relaxation_hours), snapshot=snapshot)
    flash("✨ 路線已收藏成功！可點上方「收藏路線」查看。", "success")
    return redirect(request.referrer or url_for('home'))


@app.route('/place/like', methods=['GET', 'POST'])
def like():
    global LATEST_ROUTE_CONTEXT
    place = {
        "name": request.values.get("name"),
        "category": request.values.get("category"),
    }
    liked_names = memory_sets(load_place_memory()).get("liked", set())
    if _place_key(place["name"]) in liked_names:
        remove_place("liked_places", place["name"])
        flash(f"已從喜歡景點移除：{place['name']}。", "info")
    else:
        like_place(place)
        flash(f"已加入喜歡景點：{place['name']}。可點上方「記憶管理」查看。", "success")
    if LATEST_ROUTE_CONTEXT and LATEST_ROUTE_CONTEXT.get("itinerary"):
        LATEST_ROUTE_CONTEXT["itinerary"] = _annotate_liked_places(LATEST_ROUTE_CONTEXT["itinerary"])
    return redirect(request.referrer or url_for('home'))


@app.route('/place/block', methods=['GET', 'POST'])
def block():
    place = {
        "name": request.values.get("name"),
        "category": request.values.get("category"),
    }
    block_place(place)
    flash(f"已加入黑名單：{place['name']}。可點上方「記憶管理」查看。", "info")
    return redirect(request.referrer or url_for('home'))


@app.route('/route/reorder', methods=['POST'])
def reorder_route_place():
    global LATEST_ROUTE_CONTEXT
    if not LATEST_ROUTE_CONTEXT:
        flash("目前沒有可編輯的路線。", "info")
        return redirect(url_for('home'))
    waypoint_details = list(LATEST_ROUTE_CONTEXT.get("waypoints") or [])
    try:
        index = int(request.form.get("index", -1))
    except ValueError:
        index = -1
    direction = request.form.get("direction")
    target = index - 1 if direction == "up" else index + 1
    if 0 <= index < len(waypoint_details) and 0 <= target < len(waypoint_details):
        waypoint_details[index], waypoint_details[target] = waypoint_details[target], waypoint_details[index]
        if _refresh_route_context(waypoint_details):
            flash("已更新行程順序。", "success")
    return redirect(url_for('home'))


@app.route('/route/delete-place', methods=['POST'])
def delete_route_place():
    global LATEST_ROUTE_CONTEXT
    if not LATEST_ROUTE_CONTEXT:
        flash("目前沒有可編輯的路線。", "info")
        return redirect(url_for('home'))
    waypoint_details = list(LATEST_ROUTE_CONTEXT.get("waypoints") or [])
    try:
        index = int(request.form.get("index", -1))
    except ValueError:
        index = -1
    if 0 <= index < len(waypoint_details):
        removed = waypoint_details.pop(index)
        if _refresh_route_context(waypoint_details):
            flash(f"已移除：{removed.get('name')}", "success")
    return redirect(url_for('home'))


@app.route('/route/add-place', methods=['POST'])
def add_route_place():
    global LATEST_ROUTE_CONTEXT
    if not LATEST_ROUTE_CONTEXT:
        flash("目前沒有可編輯的路線。", "info")
        return redirect(url_for('home'))
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "公園")
    coords_raw = request.form.get("coords", "").replace("，", ",").strip()
    coords = None
    if coords_raw and "," in coords_raw:
        try:
            first, second = [float(part.strip()) for part in coords_raw.split(",", 1)]
            coords = [first, second] if abs(first) > 90 else [second, first]
        except ValueError:
            coords = None
    custom_match = next(
        (
            place for place in load_custom_places()
            if _place_key(place.get("name")) == _place_key(name)
        ),
        None,
    )
    if custom_match:
        category = custom_match.get("category") or category
        coords = coords or custom_match.get("coords")
        if coords and len(coords) >= 2 and abs(float(coords[0])) < 90 < abs(float(coords[1])):
            coords = [coords[1], coords[0]]
    if not coords and name:
        coords = get_geocode(name)
    if not name or not coords:
        flash("新增景點需要景點名稱，或可解析的經緯度。", "info")
        return redirect(url_for('home'))
    low, high = CATEGORY_STAY_MINUTES.get(category, (15, 30))
    waypoint_details = list(LATEST_ROUTE_CONTEXT.get("waypoints") or [])
    waypoint_details.append({
        "name": name,
        "display_name": name,
        "coords": coords,
        "type": category,
        "category": category,
        "stay_minutes": round_to_5((low + high) / 2),
        "max_stay_minutes": high,
        "recommendation_reason": "由你手動加入這段行程。",
        "score": 999,
    })
    if _refresh_route_context(waypoint_details):
        flash(f"已加入景點：{name}", "success")
    else:
        flash("景點加入失敗，可能是路線服務暫時無法連線。", "info")
    return redirect(url_for('home'))


@app.route('/memory')
def memory():
    """顯示與管理景點記憶資料"""
    place_memory = load_place_memory()
    return render_template('memory.html', memory=place_memory, custom_places=load_custom_places())


@app.route('/memory/clear/<list_name>', methods=['POST'])
def clear_memory(list_name):
    labels = {
        "liked_places": "喜歡景點",
        "blocked_places": "黑名單",
        "visited_places": "造訪紀錄",
    }
    clear_memory_list(list_name)
    flash(f"已清除{labels.get(list_name, '紀錄')}。", "info")
    return redirect(url_for('memory'))


@app.route('/memory/remove/<list_name>', methods=['POST'])
def remove_memory_place(list_name):
    place_name = request.form.get("name", "")
    remove_place(list_name, place_name)
    flash(f"已刪除景點：{place_name}", "info")
    return redirect(url_for('memory'))


@app.route('/custom-place/add', methods=['POST'])
def add_custom():
    try:
        coords_raw = request.form.get("coords", "").replace("，", ",")
        lon_raw, lat_raw = [part.strip() for part in coords_raw.split(",", 1)]
        lon = float(lon_raw)
        lat = float(lat_raw)
    except (TypeError, ValueError):
        flash("手動景點新增失敗：請確認經緯度格式，例如 120.9967, 24.7941。", "info")
        return redirect(url_for('memory'))

    place = {
        "name": request.form.get("name", "").strip(),
        "category": request.form.get("category", "公園"),
        "environment": request.form.get("environment", "戶外"),
        "coords": [lon, lat],
    }
    add_custom_place(place)
    flash(f"已新增手動景點：{place['name']}", "success")
    return redirect(url_for('memory'))


@app.route('/custom-place/delete', methods=['POST'])
def delete_custom():
    name = request.form.get("name", "")
    delete_custom_place(name)
    flash(f"已刪除手動景點：{name}", "info")
    return redirect(url_for('memory'))


@app.route('/saved')
def saved():
    """顯示收藏路線列表"""
    routes = load_saved_routes()
    return render_template('saved.html', routes=routes)


@app.route('/saved/<route_id>')
def view_saved(route_id):
    global LATEST_ROUTE_CONTEXT
    route = find_saved_route(route_id)
    if not route:
        flash("找不到這條收藏路線。", "info")
        return redirect(url_for('saved'))

    snapshot_context = _hydrate_route_context(route.get("snapshot"))
    if snapshot_context:
        LATEST_ROUTE_CONTEXT = snapshot_context
        return render_template('index.html', **snapshot_context)

    flash("這是舊版收藏，沒有保存完整路線快照；請重新生成後再收藏一次。", "info")
    return redirect(url_for('saved'))


@app.route('/delete/<route_id>', methods=['POST'])
def delete(route_id):
    delete_route(route_id)
    flash("🗑️ 路線已刪除。", "info")
    return redirect(url_for('saved'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)
