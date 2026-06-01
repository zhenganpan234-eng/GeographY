from flask import Flask, render_template, request, redirect, url_for, flash
from src.api_client import get_geocode, get_mood_waypoints, get_route_matrix_v2
from src.map_builder import build_soul_map
from src.route_stats import compute_route_stats
from src.saved_routes import load_saved_routes, save_route, delete_route

app = Flask(__name__)
app.secret_key = "soulpath-secret-key"


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/search', methods=['POST'])
def search():
    start_place = request.form.get('start_place')
    end_place = request.form.get('end_place')
    social_energy = request.form.get('social_energy', '80')
    mood = request.form.get('mood', '放鬆')

    start_coords = get_geocode(start_place)
    end_coords = get_geocode(end_place)

    if not start_coords or not end_coords:
        return render_template(
            'index.html',
            error=f"找不到「{start_place}」或「{end_place}」的位置，請重新輸入！",
            start_place=start_place, end_place=end_place,
            social_energy=social_energy, mood=mood,
        )

    waypoint_details = get_mood_waypoints(start_coords, end_coords, mood, social_energy)
    waypoints_coords = [wp['coords'] for wp in waypoint_details]
    route_data = get_route_matrix_v2(start_coords, end_coords, waypoints_coords)

    if route_data:
        # 依最佳化順序重排 waypoint_details，讓清單與地圖一致
        opt_order = route_data.get('optimized_order', [])
        if opt_order:
            waypoint_details = [waypoint_details[i - 1] for i in opt_order]

        raw_distance = route_data['distance']
        raw_duration = route_data['duration']
        km_distance = round(raw_distance / 1000, 2)

        if int(social_energy) < 40:
            adjusted_duration = raw_distance / 1.1
            mode_name = "極致孤獨暗巷"
        else:
            traffic_light_delay = (raw_distance / 500) * 60
            adjusted_duration = raw_duration + traffic_light_delay
            mode_names = {
                "放鬆": "漫步療癒路線",
                "文青": "文青探索路線",
                "探索": "城市冒險路線",
                "社交": "命定十字路口",
                "療癒": "心靈靜謐路線",
            }
            mode_name = mode_names.get(mood, "SoulPath 路線")

        minutes_duration = max(1, round(adjusted_duration / 60))

        # Route Statistics
        stats = compute_route_stats(
            waypoint_details, social_energy, mood, km_distance, minutes_duration
        )

        map_html = build_soul_map(route_data['geometry'], social_energy, waypoint_details, mood)

        return render_template(
            'index.html',
            map_html=map_html,
            distance=km_distance,
            duration=minutes_duration,
            mode_name=mode_name,
            start_place=start_place,
            end_place=end_place,
            social_energy=social_energy,
            mood=mood,
            waypoints=waypoint_details,
            stats=stats,
        )
    else:
        return render_template(
            'index.html',
            error="無法串聯情緒路線，請縮短兩地距離或更換地點！",
            start_place=start_place, end_place=end_place,
            social_energy=social_energy, mood=mood,
        )


@app.route('/save', methods=['POST'])
def save():
    """收藏當前路線"""
    start_place   = request.form.get('start_place')
    end_place     = request.form.get('end_place')
    mood          = request.form.get('mood')
    social_energy = request.form.get('social_energy')
    distance      = request.form.get('distance')
    duration      = request.form.get('duration')
    waypoints_raw = request.form.get('waypoints_names', '')
    waypoints = [{"name": n} for n in waypoints_raw.split("||") if n]

    save_route(start_place, end_place, mood, social_energy,
               float(distance), int(duration), waypoints)
    flash("✨ 路線已收藏成功！", "success")
    return redirect(url_for('saved'))


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