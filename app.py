import math
from itertools import combinations
from flask import Flask, render_template, request, redirect, url_for, flash
from src.api_client import CATEGORY_STAY_MINUTES, get_geocode, get_exploration_waypoints, get_mood_waypoints, get_route_matrix_v2, round_to_5
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
        "mode_name", "start_place", "end_place", "journey_type", "social_energy",
        "mood", "exploration_mode", "environment_preference", "stats",
    ]
    return {key: context.get(key) for key in snapshot_keys if key in context}


def _build_route_segments(route_data, waypoint_details, mode_name, end_label=None):
    end_label = end_label or "回到起點附近"
    stops = [{"name": "出發地", "stay_minutes": 0}] + waypoint_details + [
        {"name": end_label, "stay_minutes": 0}
    ]
    legs = route_data.get("legs") or []
    leg_geometries = route_data.get("leg_geometries") or []
    segments = []
    for idx in range(len(stops) - 1):
        raw_distance = 0
        if idx < len(legs):
            raw_distance = legs[idx].get("distance", 0)
        
        raw_duration = 0
        if idx < len(legs):
            raw_duration = legs[idx].get("duration", 0)

        walking_minutes = max(1, math.ceil(raw_duration / 60))
        
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


def _apply_optimized_order(waypoint_details, route_data):
    opt_order = route_data.get('optimized_order', [])
    if not opt_order:
        return list(waypoint_details)
    return [waypoint_details[i - 1] for i in opt_order if 0 < i <= len(waypoint_details)]


def _route_is_walkable(route_data, waypoint_details, max_walk_minutes):
    ordered_waypoints = _apply_optimized_order(waypoint_details, route_data)
    segments = _build_route_segments(route_data, ordered_waypoints, "SoulPath")
    return not _route_breaks_walk_limit(segments, max_walk_minutes), segments, ordered_waypoints


def _walk_limit_overage(route_segments, max_walk_minutes):
    if not route_segments:
        return 0
    return max(max(0, segment["walking_minutes"] - max_walk_minutes) for segment in route_segments)


def _total_with_max_stay(waypoint_details, walking_minutes, relaxation_minutes):
    buffer_minutes = min(10, max(5, round(int(relaxation_minutes) * 0.05)))
    stay_total = 0
    for waypoint in waypoint_details:
        _, high = _stay_range(waypoint)
        waypoint["stay_minutes"] = high
        stay_total += high
    return int(walking_minutes) + stay_total + buffer_minutes, stay_total, buffer_minutes


def build_route_incrementally(start_coords, end_coords, candidates, relaxation_minutes, max_walk_minutes):
    tolerance = 10
    candidates = [dict(candidate) for candidate in candidates[:30]]
    if not candidates:
        return None, None, None

    best_waypoints = None
    best_route = None
    fallback = None

    def remember_fallback(route_data, ordered_waypoints, segments):
        nonlocal fallback
        overage = _walk_limit_overage(segments, max_walk_minutes)
        if overage <= 0:
            return
        walking_minutes = sum(segment["walking_minutes"] for segment in segments)
        total_max, _, _ = _total_with_max_stay(
            [dict(wp) for wp in ordered_waypoints], walking_minutes, relaxation_minutes
        )
        score = sum(float(wp.get("score", 0)) for wp in ordered_waypoints)
        candidate = {
            "overage": overage,
            "time_diff": abs(total_max - int(relaxation_minutes)),
            "score": score,
            "waypoints": ordered_waypoints,
            "route": dict(route_data),
        }
        candidate["route"]["optimized_order"] = []
        if (
            fallback is None
            or candidate["overage"] < fallback["overage"]
            or (
                candidate["overage"] == fallback["overage"]
                and candidate["time_diff"] < fallback["time_diff"]
            )
            or (
                candidate["overage"] == fallback["overage"]
                and candidate["time_diff"] == fallback["time_diff"]
                and candidate["score"] > fallback["score"]
            )
        ):
            fallback = candidate

    for candidate in candidates:
        trial_waypoints = [dict(candidate)]
        route_data = get_route_matrix_v2(
            start_coords,
            end_coords,
            [wp["coords"] for wp in trial_waypoints],
        )
        if not route_data:
            continue

        walk_ok, segments, ordered_waypoints = _route_is_walkable(
            route_data, trial_waypoints, max_walk_minutes
        )
        if not walk_ok:
            remember_fallback(route_data, ordered_waypoints, segments)
            continue

        best_waypoints = ordered_waypoints
        best_route = dict(route_data)
        best_route["optimized_order"] = []
        break

    if not best_waypoints:
        if fallback:
            return (
                fallback["waypoints"],
                fallback["route"],
                "找不到完全符合步行限制的路線，改用最接近者",
            )
        return None, None, None

    walking_minutes = sum(segment["walking_minutes"] for segment in segments)
    total_max, _, _ = _total_with_max_stay(
        best_waypoints, walking_minutes, relaxation_minutes
    )
    if total_max >= int(relaxation_minutes) - tolerance:
        return best_waypoints, best_route, None

    used_keys = {_place_key(wp.get("name")) for wp in best_waypoints}
    used_categories = {wp.get("category") or wp.get("type") for wp in best_waypoints}

    for candidate in candidates:
        candidate_key = _place_key(candidate.get("name"))
        if candidate_key in used_keys:
            continue
        candidate_category = candidate.get("category") or candidate.get("type")
        if candidate_category in used_categories:
            continue

        trial_waypoints = best_waypoints + [dict(candidate)]
        route_data = get_route_matrix_v2(
            start_coords,
            end_coords,
            [wp["coords"] for wp in trial_waypoints],
        )
        if not route_data:
            continue

        walk_ok, segments, ordered_waypoints = _route_is_walkable(
            route_data, trial_waypoints, max_walk_minutes
        )
        if not walk_ok:
            remember_fallback(route_data, ordered_waypoints, segments)
            continue

        walking_minutes = sum(segment["walking_minutes"] for segment in segments)
        total_max, _, _ = _total_with_max_stay(
            ordered_waypoints, walking_minutes, relaxation_minutes
        )

        best_waypoints = ordered_waypoints
        best_route = dict(route_data)
        best_route["optimized_order"] = []
        used_keys = {_place_key(wp.get("name")) for wp in best_waypoints}
        used_categories = {wp.get("category") or wp.get("type") for wp in best_waypoints}

        if total_max >= int(relaxation_minutes) - tolerance:
            break

    return best_waypoints, best_route, None


def _remove_walk_limit_offender(waypoint_details, route_segments, max_walk_minutes):
    worst_idx = None
    worst_minutes = 0

    for idx, segment in enumerate(route_segments):
        if segment["walking_minutes"] > worst_minutes:
            worst_minutes = segment["walking_minutes"]
            worst_idx = idx

    if worst_minutes <= max_walk_minutes or worst_idx is None or not waypoint_details:
        return None

    if worst_idx == 0:
        remove_idx = 0
    elif worst_idx >= len(waypoint_details):
        remove_idx = len(waypoint_details) - 1
    else:
        left_idx = worst_idx - 1
        right_idx = worst_idx
        left_score = waypoint_details[left_idx].get("score", 0)
        right_score = waypoint_details[right_idx].get("score", 0)
        remove_idx = left_idx if left_score <= right_score else right_idx

    return waypoint_details.pop(remove_idx)


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
    waypoint_details, stay_minutes, buffer_minutes = rebalance_stay_times(
        waypoint_details, walking_minutes, relaxation_minutes
    )
    total_minutes = walking_minutes + stay_minutes + buffer_minutes
    return stay_minutes, buffer_minutes, total_minutes


def _stay_range(waypoint):
    category = waypoint.get("category") or waypoint.get("type")
    low, high = CATEGORY_STAY_MINUTES.get(category, (10, 30))
    low = waypoint.get("min_stay_minutes", low)
    high = waypoint.get("max_stay_minutes", high)
    low = round_to_5(int(low))
    high = round_to_5(int(max(high, low)))
    return low, high


def rebalance_stay_times(waypoints, walking_minutes, relaxation_minutes):
    tolerance = 10
    buffer_minutes = min(10, max(5, round(int(relaxation_minutes) * 0.05)))
    target_total = int(relaxation_minutes)

    if not waypoints:
        return waypoints, 0, max(0, min(buffer_minutes, target_total - int(walking_minutes)))

    ranges = []
    for wp in waypoints:
        low, high = _stay_range(wp)
        ranges.append((low, high))
        wp["stay_minutes"] = high

    while True:
        stay_total = sum(int(wp["stay_minutes"]) for wp in waypoints)
        total = int(walking_minutes) + stay_total + buffer_minutes

        if target_total - tolerance <= total <= target_total + tolerance:
            break

        if total > target_total + tolerance:
            changed = False
            for wp, (low, high) in zip(waypoints, ranges):
                current = int(wp["stay_minutes"])
                if current > low:
                    wp["stay_minutes"] = max(low, current - 5)
                    changed = True

            if not changed:
                break
        else:
            break

    stay_total = sum(int(wp["stay_minutes"]) for wp in waypoints)
    return waypoints, stay_total, buffer_minutes


def _build_itinerary(start_place, waypoint_details, route_segments, end_place=None):
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
    itinerary.append({"kind": "place", "name": end_place or "回到起點附近", "label": "終點"})
    return itinerary


def _place_key(name):
    return (name or "").strip().lower()


def _route_context(**kwargs):
    kwargs.setdefault("custom_places", load_custom_places())
    return kwargs


def _direct_route_context(start_coords, end_coords):
    route_data = get_route_matrix_v2(start_coords, end_coords, [], optimize=False)
    if not route_data:
        return None, None, None
    return [], route_data, None


def _route_template(context):
    return "journey.html" if context.get("journey_type") == "journey" else "index.html"


def _route_landing_endpoint():
    if LATEST_ROUTE_CONTEXT and LATEST_ROUTE_CONTEXT.get("journey_type") == "journey":
        return "journey"
    return "wander"


def _hydrate_route_context(snapshot):
    if not snapshot or not snapshot.get("route_data"):
        return None
    waypoint_details = snapshot.get("waypoints") or []
    route_segments = snapshot.get("route_segments") or []
    social_energy = snapshot.get("social_energy", "80")
    mood = snapshot.get("mood", "放鬆")
    route_data = snapshot["route_data"]
    end_label = snapshot.get("end_place") or "回到起點附近"
    map_html = build_soul_map(
        route_data.get("geometry", []), social_energy, waypoint_details, mood, route_segments, end_label
    )
    itinerary = _build_itinerary(
        snapshot.get("start_place", ""),
        waypoint_details,
        route_segments,
        end_label,
    )
    itinerary = _annotate_liked_places(itinerary)
    context = dict(snapshot)
    context.update({
        "map_html": map_html,
        "itinerary": itinerary,
        "waypoints": waypoint_details,
        "route_segments": route_segments,
        "custom_places": load_custom_places(),
        "page_mode": context.get("journey_type", "wander"),
        "form_action": url_for('journey_search' if context.get("journey_type") == "journey" else 'search'),
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
    end_label = LATEST_ROUTE_CONTEXT.get("end_place") or "回到起點附近"
    route_segments = _build_route_segments(route_data, waypoint_details, mode_name, end_label)
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
        end_label,
    )
    itinerary = _annotate_liked_places(itinerary)
    LATEST_ROUTE_CONTEXT.update({
        "map_html": build_soul_map(route_data["geometry"], social_energy, waypoint_details, mood, route_segments, end_label),
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
    return render_template('landing.html')


@app.route('/wander')
def wander():
    if LATEST_ROUTE_CONTEXT and LATEST_ROUTE_CONTEXT.get("journey_type") != "journey" and not request.args:
        return render_template('index.html', **LATEST_ROUTE_CONTEXT)
    return render_template(
        'index.html',
        page_mode="wander",
        form_action=url_for('search'),
        start_place=request.args.get('start', ''),
        relaxation_hours=request.args.get('hours', request.args.get('minutes', '1')),
        max_walk_minutes=request.args.get('walk', '12'),
        custom_places=load_custom_places(),
        social_energy=request.args.get('energy', '80'),
        mood=request.args.get('mood', '放鬆'),
        exploration_mode=request.args.get('mode', '平衡模式'),
        environment_preference=request.args.get('env', '不限'),
    )


@app.route('/journey')
def journey():
    if LATEST_ROUTE_CONTEXT and LATEST_ROUTE_CONTEXT.get("journey_type") == "journey" and not request.args:
        return render_template('journey.html', **LATEST_ROUTE_CONTEXT)
    return render_template(
        'journey.html',
        page_mode="journey",
        form_action=url_for('journey_search'),
        start_place=request.args.get('start', ''),
        end_place=request.args.get('end', ''),
        relaxation_hours=request.args.get('hours', '3'),
        max_walk_minutes=request.args.get('walk', '20'),
        custom_places=load_custom_places(),
        social_energy=request.args.get('energy', '80'),
        mood=request.args.get('mood', '放鬆'),
        exploration_mode=request.args.get('mode', '平衡模式'),
        environment_preference=request.args.get('env', '不限'),
    )


@app.route('/route/current')
def current_route():
    if LATEST_ROUTE_CONTEXT:
        return render_template(_route_template(LATEST_ROUTE_CONTEXT), **LATEST_ROUTE_CONTEXT)
    return redirect(url_for('wander'))


def _generate_route_context(start_place, relaxation_hours, relaxation_minutes, social_energy, mood, exploration_mode, environment_preference, max_walk_minutes, selected_start_coords=None, end_place=None, journey_type="wander"):
    start_coords = selected_start_coords or get_geocode(start_place)
    end_coords = start_coords if journey_type == "wander" else get_geocode(end_place)

    if not start_coords:
        return None, f"找不到「{start_place}」的位置，請重新輸入！"
    if journey_type == "journey" and not end_coords:
        return None, f"找不到「{end_place}」的位置，請重新輸入！"

    place_memory = load_place_memory()
    memory = memory_sets(place_memory)
    waypoint_details, time_budget = get_exploration_waypoints(
        start_coords, mood, social_energy, relaxation_minutes, memory, exploration_mode,
        max_walk_minutes, environment_preference
    )
    waypoint_details, route_data, route_warning = build_route_incrementally(
        start_coords,
        end_coords,
        waypoint_details,
        relaxation_minutes,
        max_walk_minutes,
    )
    if journey_type == "journey" and not route_data:
        waypoint_details, route_data, route_warning = _direct_route_context(start_coords, end_coords)

    if waypoint_details:
        print("[選中景點]")
        for wp in waypoint_details:
            print(wp["name"], wp.get("category"), wp.get("stay_minutes"), round(wp.get("score", 0), 1))

    if not route_data:
        return None, "無法生成療癒探索路線，請延長放鬆時間或更換出發地點！"

    opt_order = route_data.get('optimized_order', [])
    if opt_order:
        waypoint_details = [waypoint_details[i - 1] for i in opt_order]

    km_distance = round(route_data['distance'] / 1000, 2)
    if journey_type == "journey":
        mode_name = "旅行模式療癒探索"
    elif int(social_energy) < 40:
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

    final_label = end_place if journey_type == "journey" else "回到起點附近"
    route_segments = _build_route_segments(route_data, waypoint_details, mode_name, final_label)
    walking_minutes = sum(segment["walking_minutes"] for segment in route_segments)
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
    itinerary = _build_itinerary(start_place, waypoint_details, route_segments, final_label)
    itinerary = _annotate_liked_places(itinerary)
    map_html = build_soul_map(
        route_data['geometry'], social_energy, waypoint_details, mood, route_segments, final_label
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
        route_warning=route_warning,
        mode_name=mode_name,
        start_place=start_place,
        end_place=final_label,
        journey_type=journey_type,
        page_mode=journey_type,
        form_action=url_for('journey_search' if journey_type == "journey" else 'search'),
        social_energy=social_energy,
        mood=mood,
        exploration_mode=exploration_mode,
        environment_preference=environment_preference,
        waypoints=waypoint_details,
        route_segments=route_segments,
        itinerary=itinerary,
        stats=stats,
    ), None


def _generate_journey_context(start_place, end_place, social_energy, mood, selected_start_coords=None):
    start_coords = selected_start_coords or get_geocode(start_place)
    end_coords = get_geocode(end_place)

    if not start_coords:
        return None, f"找不到「{start_place}」的位置，請重新輸入！"
    if not end_coords:
        return None, f"找不到「{end_place}」的位置，請重新輸入！"

    waypoint_details = get_mood_waypoints(start_coords, end_coords, mood, social_energy)
    for waypoint in waypoint_details:
        category = waypoint.get("category") or waypoint.get("type", "")
        waypoint["category"] = category
        waypoint["type"] = category
        waypoint.setdefault("stay_minutes", None)
        waypoint.setdefault("recommendation_reason", "這是依照你的心境與旅程方向挑選的沿途停靠點。")
        waypoint.setdefault("score", 0)

    route_data = get_route_matrix_v2(
        start_coords,
        end_coords,
        [wp["coords"] for wp in waypoint_details],
    )
    if not route_data:
        route_data = get_route_matrix_v2(start_coords, end_coords, [], optimize=False)
        waypoint_details = []

    if not route_data:
        return None, "無法生成旅行路線，請更換起點或終點後再試一次！"

    opt_order = route_data.get("optimized_order", [])
    if opt_order:
        waypoint_details = [waypoint_details[i - 1] for i in opt_order if 0 < i <= len(waypoint_details)]

    mode_name = "旅行模式療癒探索"
    route_segments = _build_route_segments(route_data, waypoint_details, mode_name, end_place)
    walking_minutes = sum(segment["walking_minutes"] for segment in route_segments)
    km_distance = round(route_data["distance"] / 1000, 2)
    duration = walking_minutes
    itinerary = _build_itinerary(start_place, waypoint_details, route_segments, end_place)
    itinerary = _annotate_liked_places(itinerary)
    map_html = build_soul_map(
        route_data["geometry"], social_energy, waypoint_details, mood, route_segments, end_place
    )
    mark_visited(waypoint_details)

    return _route_context(
        map_html=map_html,
        start_coords=start_coords,
        end_coords=end_coords,
        route_data=route_data,
        distance=km_distance,
        duration=duration,
        walking_minutes=walking_minutes,
        stay_minutes=0,
        buffer_minutes=0,
        relaxation_hours=None,
        relaxation_minutes=duration,
        max_walk_minutes=None,
        time_budget={
            "total": duration,
            "walking": walking_minutes,
            "stay": 0,
            "buffer": 0,
        },
        route_warning=None,
        mode_name=mode_name,
        start_place=start_place,
        end_place=end_place,
        journey_type="journey",
        page_mode="journey",
        form_action=url_for("journey_search"),
        social_energy=social_energy,
        mood=mood,
        exploration_mode="旅行模式",
        environment_preference="不限",
        waypoints=waypoint_details,
        route_segments=route_segments,
        itinerary=itinerary,
        stats=compute_route_stats(waypoint_details, social_energy, mood, km_distance, walking_minutes),
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
        exploration_mode, environment_preference, max_walk_minutes, selected_start_coords,
        journey_type="wander",
    )
    if error:
        return render_template(
            'index.html',
            error=error,
            page_mode="wander",
            form_action=url_for('search'),
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


@app.route('/journey/search', methods=['POST'])
def journey_search():
    global LATEST_ROUTE_CONTEXT
    start_place = request.form.get('start_place')
    end_place = request.form.get('end_place')
    selected_start_coords = _parse_selected_coords(
        request.form.get("selected_start_lon"),
        request.form.get("selected_start_lat"),
    )
    social_energy = request.form.get('social_energy', '80')
    mood = request.form.get('mood', '放鬆')

    context, error = _generate_journey_context(
        start_place,
        end_place,
        social_energy,
        mood,
        selected_start_coords,
    )
    if error:
        return render_template(
            'journey.html',
            error=error,
            page_mode="journey",
            form_action=url_for('journey_search'),
            start_place=start_place,
            end_place=end_place,
            custom_places=load_custom_places(),
            social_energy=social_energy,
            mood=mood,
            exploration_mode="旅行模式",
            environment_preference="不限",
        )
    LATEST_ROUTE_CONTEXT = context
    return render_template('journey.html', **context)


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
        return redirect(url_for('wander'))
    end_place     = request.values.get('end_place') or "回到起點附近"
    mood          = request.values.get('mood')
    social_energy = request.values.get('social_energy')
    exploration_mode = request.values.get('exploration_mode') or "平衡模式"
    environment_preference = request.values.get('environment_preference') or "不限"
    distance      = request.values.get('distance') or 0
    duration      = request.values.get('duration') or 0
    relaxation_hours = request.values.get('relaxation_hours') or "1"
    max_walk_minutes = request.values.get('max_walk_minutes') or "0"
    relaxation_minutes = request.values.get('relaxation_minutes') or duration
    waypoints_raw = request.values.get('waypoints_names', '')
    waypoints = [{"name": n} for n in waypoints_raw.split("||") if n]

    snapshot = _snapshot_context(LATEST_ROUTE_CONTEXT or {})
    try:
        saved_relaxation_hours = float(relaxation_hours)
    except (TypeError, ValueError):
        saved_relaxation_hours = round(int(duration) / 60, 2) if duration else 0
    save_route(start_place, end_place, mood, social_energy,
               float(distance), int(duration), waypoints, int(relaxation_minutes), exploration_mode,
               int(max_walk_minutes), environment_preference, saved_relaxation_hours, snapshot=snapshot)
    flash("✨ 路線已收藏成功！可點上方「收藏路線」查看。", "success")
    return redirect(request.referrer or url_for(_route_landing_endpoint()))


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
    return redirect(request.referrer or url_for(_route_landing_endpoint()))


@app.route('/place/block', methods=['GET', 'POST'])
def block():
    place = {
        "name": request.values.get("name"),
        "category": request.values.get("category"),
    }
    block_place(place)
    flash(f"已加入黑名單：{place['name']}。可點上方「記憶管理」查看。", "info")
    return redirect(request.referrer or url_for(_route_landing_endpoint()))


@app.route('/route/reorder', methods=['POST'])
def reorder_route_place():
    global LATEST_ROUTE_CONTEXT
    if not LATEST_ROUTE_CONTEXT:
        flash("目前沒有可編輯的路線。", "info")
        return redirect(url_for('wander'))
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
    return redirect(url_for(_route_landing_endpoint()))


@app.route('/route/delete-place', methods=['POST'])
def delete_route_place():
    global LATEST_ROUTE_CONTEXT
    if not LATEST_ROUTE_CONTEXT:
        flash("目前沒有可編輯的路線。", "info")
        return redirect(url_for('wander'))
    waypoint_details = list(LATEST_ROUTE_CONTEXT.get("waypoints") or [])
    try:
        index = int(request.form.get("index", -1))
    except ValueError:
        index = -1
    if 0 <= index < len(waypoint_details):
        removed = waypoint_details.pop(index)
        if _refresh_route_context(waypoint_details):
            flash(f"已移除：{removed.get('name')}", "success")
    return redirect(url_for(_route_landing_endpoint()))


@app.route('/route/add-place', methods=['POST'])
def add_route_place():
    global LATEST_ROUTE_CONTEXT
    if not LATEST_ROUTE_CONTEXT:
        flash("目前沒有可編輯的路線。", "info")
        return redirect(url_for('wander'))
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
        return redirect(url_for(_route_landing_endpoint()))
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
    return redirect(url_for(_route_landing_endpoint()))


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
        return render_template(_route_template(snapshot_context), **snapshot_context)

    flash("這是舊版收藏，沒有保存完整路線快照；請重新生成後再收藏一次。", "info")
    return redirect(url_for('saved'))


@app.route('/delete/<route_id>', methods=['POST'])
def delete(route_id):
    delete_route(route_id)
    flash("🗑️ 路線已刪除。", "info")
    return redirect(url_for('saved'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)
