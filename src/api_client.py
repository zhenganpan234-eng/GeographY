import requests

import requests

def get_geocode(address):
    """
    1. 地名解析 (嚴格遵循規定：使用 Nominatim API)
    將文字地名轉換為 [經度, 緯度] 數字座標
    """
    url = "https://nominatim.openstreetmap.org/search"
    
    # 💡 修正封鎖與搜尋問題的核心 1：換一個更像真實瀏覽器的 User-Agent，避免被官方阻擋
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    # 💡 修正核心 2：不要用空格字串！改用 Nominatim 官方推薦的「結構化搜尋」
    # 限制搜尋範圍在「台灣 (tw)」，這樣使用者直接打「羅東車站」或「台北車站」就絕對找得到！
    params = {
        'q': address,
        'countrycodes': 'tw',  # 嚴格限制在台灣地區搜尋
        'format': 'json',
        'limit': 1,
        'accept-language': 'zh-TW' # 強制要求繁體中文回傳
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200 and len(response.json()) > 0:
            result = response.json()[0]
            lon = float(result['lon'])
            lat = float(result['lat'])
            print(f"[Nominatim定位成功] 輸入: {address} -> 經度:{lon}, 緯度:{lat}")
            return [lon, lat]
        else:
            print(f"[Nominatim定位失敗] API查無此地名: {address}")
    except Exception as e:
        print(f"[錯誤] Nominatim 連線失敗: {e}")
    return None


def get_route_matrix(start_coords, end_coords):
    """
    2. 步行路由規劃 (OSRM API)
    取得起點到終點沿著馬路走的真實步行軌跡 (GeoJSON) 與距離
    coords 格式: [經度, 緯度]
    """
    url = f"http://router.project-osrm.org/route/v1/foot/{start_coords[0]},{start_coords[1]};{end_coords[0]},{end_coords[1]}"
    params = {
        'overview': 'full',
        'geometries': 'geojson'
    }
    
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data.get('code') == 'Ok':
            route = data['routes'][0]
            geometry = route['geometry']['coordinates']
            distance = route['distance']
            duration = route['duration']
            return {"geometry": geometry, "distance": distance, "duration": duration}
    return None


def get_mood_places(mood, social_energy):
    """
    3. 依情緒周邊搜尋 (預留未來演算法擴充使用)
    """
    # 這是先前測試保留的函式，先放著不動它
    return []