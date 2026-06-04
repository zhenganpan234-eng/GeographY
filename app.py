from flask import Flask, render_template, request, redirect, url_for, flash
from src.api_client import get_geocode, get_exploration_waypoints, get_route_matrix_v2
from src.map_builder import build_soul_map
from src.route_stats import compute_route_stats
from src.saved_routes import load_saved_routes, save_route, delete_route
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


def _build_route_segments(route_data, waypoint_details, mode_name):
    stops = [{"name": "出發地", "stay_minutes": 0}] + waypoint_details + [
        {"name": "回到起點附近", "stay_minutes": 0}
    ]
    legs = route_data.get("legs") or []
    leg_geometries = route_data.get("leg_geometries") or []
    segments = []
    for idx in range(len(stops) - 1):
        raw_duration = 0
        if idx < len(legs):
            raw_duration = legs[idx].get("duration", 0)
        walking_minutes = max(1, round(raw_duration / 60)) if raw_duration else 1
        segments.append({
            "from": stops[idx]["name"],
            "to": stops[idx + 1]["name"],
            "walking_minutes": walking_minutes,
            "mode_name": mode_name,
            "geometry": leg_geometries[idx] if idx < len(leg_geometries) else [],
        })
    return segments


def _route_breaks_walk_limit(route_segments, max_walk_minutes):
    return any(segment["walking_minutes"] > max_walk_minutes for segment in route_segments)


def _expand_stay_time(waypoint_details, extra_minutes):
    if extra_minutes <= 0 or not waypoint_details:
        return 0
    added = 0
    while added < extra_minutes:
        changed = False
        for waypoint in waypoint_details:
            category = waypoint.get("category") or waypoint.get("type")
            max_stay = waypoint.get("max_stay_minutes") or {
                "公園": 35, "庭園": 35, "河岸": 45, "步道": 60,
                "咖啡廳": 70, "書店": 45, "圖書館": 60,
                "藝文空間": 60, "古蹟": 35, "廟宇": 35,
                "市集": 70, "夜市": 70, "商圈": 70,
            }.get(category, 35)
            current = int(waypoint.get("stay_minutes", 0))
            if current < max_stay and added < extra_minutes:
                step = min(5, max_stay - current, extra_minutes - added)
                waypoint["stay_minutes"] = current + step
                added += step
                changed = True
        if not changed:
            break
    return added


def _build_itinerary(start_place, waypoint_details, route_segments):
    itinerary = [{"kind": "place", "name": start_place or "出發地", "label": "出發地"}]
    for idx, waypoint in enumerate(waypoint_details):
        if idx < len(route_segments):
            itinerary.append({
                "kind": "walk",
                "walking_minutes": route_segments[idx]["walking_minutes"],
            })
        itinerary.append({
            "kind": "place",
            "name": waypoint["name"],
            "label": waypoint.get("category") or waypoint.get("type", ""),
            "stay_minutes": waypoint.get("stay_minutes"),
            "recommendation_reason": waypoint.get("recommendation_reason", ""),
            "category": waypoint.get("category") or waypoint.get("type", ""),
        })
    if route_segments:
        itinerary.append({
            "kind": "walk",
            "walking_minutes": route_segments[-1]["walking_minutes"],
        })
    itinerary.append({"kind": "place", "name": "回到起點附近", "label": "終點"})
    return itinerary


@app.route('/')
def home():
    return render_template(
        'index.html',
        start_place=request.args.get('start', ''),
        relaxation_hours=request.args.get('hours', request.args.get('minutes', '1')),
        max_walk_minutes=request.args.get('walk', '12'),
        social_energy=request.args.get('energy', '80'),
        mood=request.args.get('mood', '放鬆'),
        exploration_mode=request.args.get('mode', '平衡模式'),
        environment_preference=request.args.get('env', '不限'),
    )


@app.route('/search', methods=['POST'])
def search():
    start_place = request.form.get('start_place')
    relaxation_hours, relaxation_minutes = _parse_relaxation_hours(
        request.form.get('relaxation_hours', '1')
    )
    social_energy = request.form.get('social_energy', '80')
    mood = request.form.get('mood', '放鬆')
    exploration_mode = request.form.get('exploration_mode', '平衡模式')
    environment_preference = request.form.get('environment_preference', '不限')
    max_walk_minutes = _parse_walk_limit(request.form.get('max_walk_minutes', '12'))

    start_coords = get_geocode(start_place)
    end_coords = start_coords

    if not start_coords:
        return render_template(
            'index.html',
            error=f"找不到「{start_place}」的位置，請重新輸入！",
            start_place=start_place,
            relaxation_hours=relaxation_hours,
            relaxation_minutes=relaxation_minutes,
            max_walk_minutes=max_walk_minutes,
            social_energy=social_energy,
            mood=mood,
            exploration_mode=exploration_mode,
            environment_preference=environment_preference,
        )

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
        if (
            walking_preview + stay_preview <= relaxation_minutes
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

    if route_data:
        # 依最佳化順序重排 waypoint_details，讓清單與地圖一致
        opt_order = route_data.get('optimized_order', [])
        if opt_order:
            waypoint_details = [waypoint_details[i - 1] for i in opt_order]

        raw_distance = route_data['distance']
        km_distance = round(raw_distance / 1000, 2)

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
        stay_minutes = sum(int(wp.get('stay_minutes', 0)) for wp in waypoint_details)
        max_buffer_minutes = max(3, round(relaxation_minutes * 0.12))
        remaining_minutes = max(0, relaxation_minutes - walking_minutes - stay_minutes)
        if remaining_minutes > max_buffer_minutes:
            added_stay = _expand_stay_time(waypoint_details, remaining_minutes - max_buffer_minutes)
            stay_minutes += added_stay
            remaining_minutes = max(0, relaxation_minutes - walking_minutes - stay_minutes)
        buffer_minutes = min(max_buffer_minutes, remaining_minutes)
        total_minutes = walking_minutes + stay_minutes + buffer_minutes
        time_budget.update({
            "total": total_minutes,
            "walking": walking_minutes,
            "stay": stay_minutes,
            "buffer": buffer_minutes,
        })

        # Route Statistics
        stats = compute_route_stats(
            waypoint_details, social_energy, mood, km_distance, walking_minutes
        )

        itinerary = _build_itinerary(start_place, waypoint_details, route_segments)
        map_html = build_soul_map(
            route_data['geometry'], social_energy, waypoint_details, mood, route_segments
        )
        mark_visited(waypoint_details)

        return render_template(
            'index.html',
            map_html=map_html,
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
        )
    else:
        return render_template(
            'index.html',
            error="無法生成療癒探索路線，請延長放鬆時間或更換出發地點！",
            start_place=start_place,
            relaxation_hours=relaxation_hours,
            relaxation_minutes=relaxation_minutes,
            max_walk_minutes=max_walk_minutes,
            social_energy=social_energy,
            mood=mood,
            exploration_mode=exploration_mode,
            environment_preference=environment_preference,
        )


@app.route('/save', methods=['POST'])
def save():
    """收藏當前路線"""
    start_place   = request.form.get('start_place')
    end_place     = request.form.get('end_place') or "回到起點附近"
    mood          = request.form.get('mood')
    social_energy = request.form.get('social_energy')
    exploration_mode = request.form.get('exploration_mode') or "平衡模式"
    environment_preference = request.form.get('environment_preference') or "不限"
    distance      = request.form.get('distance')
    duration      = request.form.get('duration')
    relaxation_hours = request.form.get('relaxation_hours') or "1"
    max_walk_minutes = request.form.get('max_walk_minutes') or "12"
    relaxation_minutes = request.form.get('relaxation_minutes') or duration
    waypoints_raw = request.form.get('waypoints_names', '')
    waypoints = [{"name": n} for n in waypoints_raw.split("||") if n]

    save_route(start_place, end_place, mood, social_energy,
               float(distance), int(duration), waypoints, int(relaxation_minutes), exploration_mode,
               int(max_walk_minutes), environment_preference)
    flash("✨ 路線已收藏成功！", "success")
    return redirect(url_for('saved'))


@app.route('/place/like', methods=['POST'])
def like():
    place = {
        "name": request.form.get("name"),
        "category": request.form.get("category"),
    }
    like_place(place)
    flash(f"已收藏景點：{place['name']}", "success")
    return redirect(request.referrer or url_for('home'))


@app.route('/place/block', methods=['POST'])
def block():
    place = {
        "name": request.form.get("name"),
        "category": request.form.get("category"),
    }
    block_place(place)
    flash(f"之後不再推薦：{place['name']}", "info")
    return redirect(request.referrer or url_for('home'))


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
        lon = float(request.form.get("lon"))
        lat = float(request.form.get("lat"))
        stay_min = int(request.form.get("stay_min") or 20)
        stay_max = int(request.form.get("stay_max") or stay_min)
    except (TypeError, ValueError):
        flash("手動景點新增失敗：請確認經緯度與停留時間格式。", "info")
        return redirect(url_for('memory'))

    place = {
        "name": request.form.get("name", "").strip(),
        "category": request.form.get("category", "公園"),
        "environment": request.form.get("environment", "戶外"),
        "coords": [lon, lat],
        "stay_range": [stay_min, max(stay_min, stay_max)],
        "tags": [
            tag.strip() for tag in request.form.get("tags", "").split(",")
            if tag.strip()
        ],
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


@app.route('/delete/<route_id>', methods=['POST'])
def delete(route_id):
    delete_route(route_id)
    flash("🗑️ 路線已刪除。", "info")
    return redirect(url_for('saved'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)
