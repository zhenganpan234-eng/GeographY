from flask import Flask, render_template, request
from src.api_client import get_geocode, get_mood_waypoints, get_route_matrix_v2
from src.map_builder import build_soul_map

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    start_place = request.form.get('start_place')
    end_place = request.form.get('end_place')
    social_energy = request.form.get('social_energy')
    mood = request.form.get('mood')
    
    start_coords = get_geocode(start_place)
    end_coords = get_geocode(end_place)
    
    if not start_coords or not end_coords:
        return render_template('index.html', error=f"找不到「{start_place}」或「{end_place}」的位置，請重新輸入！")
    
    # 1. 抓取包含地名的中繼點字典列表
    waypoint_details = get_mood_waypoints(start_coords, end_coords, mood, social_energy)
    
    # 2. 提取出純座標陣列餵給 OSRM
    waypoints_coords = [wp['coords'] for wp in waypoint_details]
    route_data = get_route_matrix_v2(start_coords, end_coords, waypoints_coords)
    
    if route_data:
        raw_distance = route_data['distance']
        raw_duration = route_data['duration']
        
        km_distance = round(raw_distance / 1000, 2)
        
        if int(social_energy) < 40:
            adjusted_duration = raw_distance / 1.1
            mode_name = "極致孤獨暗巷"
        else:
            traffic_light_delay = (raw_distance / 500) * 60
            adjusted_duration = raw_duration + traffic_light_delay
            mode_name = "命定十字路口"
            
        minutes_duration = max(1, round(adjusted_duration / 60))
        
        # 💡 🔥 注意這行：必須要傳入三個參數！
        map_html = build_soul_map(route_data['geometry'], social_energy, waypoint_details)
        
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
            waypoints=waypoint_details
        )
    else:
        return render_template('index.html', error="無法串聯情緒路線，請縮短兩地距離或更換地點！")

if __name__ == '__main__':
    app.run(debug=True, port=5000)