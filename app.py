from flask import Flask, render_template, request
# 同時引入地名解析與路由規劃功能
from src.api_client import get_route_matrix, get_geocode
from src.map_builder import build_soul_map

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    # 1. 接收網頁輸入的文字與數值
    start_place = request.form.get('start_place')
    end_place = request.form.get('end_place')
    social_energy = request.form.get('social_energy')
    mood = request.form.get('mood')
    
    # 2. 透過 Peter 寫的 Nominatim 功能，將文字轉成經緯度數字
    start_coords = get_geocode(start_place)
    end_coords = get_geocode(end_place)
    
    # 防呆機制：如果隨便亂打字找不到地方，回傳錯誤訊息
    if not start_coords or not end_coords:
        return f"<h3>❌ 定位失敗！</h3><p>找不到「{start_place}」或「{end_place}」的具體位置，請重新輸入正確的地名或學校名稱！</p><a href='/'>返回首頁</a>"
    
    # 3. 呼叫 OSRM API 取得這兩點之間真實的步行馬路軌跡
    route_data = get_route_matrix(start_coords, end_coords)
    
    if route_data:
        # 4. 根據軌跡與社交能量，繪製專屬風格的互動地圖
        map_html = build_soul_map(route_data['geometry'], social_energy)
        return map_html
    else:
        return "<h3>❌ 路由失敗！</h3><p>OSRM 路由引擎無法在兩地之間規劃步行路線（可能距離太遠或跨海）。</p><a href='/'>返回首頁</a>"

if __name__ == '__main__':
    app.run(debug=True, port=5000)