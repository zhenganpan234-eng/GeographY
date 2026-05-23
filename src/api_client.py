import requests
import math

def get_geocode(address):
    """
    1. 地名解析 (Nominatim API)
    將文字地名轉換為 [經度, 緯度] 數字座標
    """
    url = "https://nominatim.openstreetmap.org/search"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    params = {
        'q': address,
        'countrycodes': 'tw',
        'format': 'json',
        'limit': 1,
        'accept-language': 'zh-TW'
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200 and len(response.json()) > 0:
            result = response.json()[0]
            return [float(result['lon']), float(result['lat'])]
    except Exception as e:
        print(f"[錯誤] Nominatim 定位失敗: {e}")
    return None


def get_mood_waypoints(start_coords, end_coords, mood, social_energy):
    """
    2. 順向特徵點搜尋演算法 (透過幾何距離排序，全面消除回頭路折返感)
    """
    url = "https://nominatim.openstreetmap.org/search"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    if int(social_energy) < 40:
        search_query = "公園"
    else:
        if mood == "文青":
            search_query = "書店"
        elif mood == "社交":
            search_query = "商圈"
        else:
            search_query = "咖啡廳"
            
    # 限制在終點（目的地）周邊方圓 2 公里內搜尋
    lon_e, lat_e = end_coords[0], end_coords[1]
    left, right = lon_e - 0.02, lon_e + 0.02
    bottom, top = lat_e - 0.02, lat_e + 0.02
    
    params = {
        'q': search_query,
        'countrycodes': 'tw',
        'viewbox': f"{left},{top},{right},{bottom}",
        'bounded': 1,
        'format': 'json',
        'limit': 3,
        'accept-language': 'zh-TW'
    }
    
    waypoints = []
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            results = response.json()
            raw_pts = []
            for item in results:
                raw_pts.append([float(item['lon']), float(item['lat'])])
            
            # 💡 核心演算法：計算各個中繼點與「出發起點」的直線距離
            lon_s, lat_s = start_coords[0], start_coords[1]
            
            # 用簡單的歐幾里得幾何公式計算距離，並綁定座標進行排序
            def calc_dist(pt):
                return math.sqrt((pt[0] - lon_s)**2 + (pt[1] - lat_s)**2)
            
            # 依據到起點的距離「由近到遠」自動排序！
            waypoints = sorted(raw_pts, key=calc_dist)
            
            print(f"[順向演算法] 成功抓取並排序了 {len(waypoints)} 個『{search_query}』站點，確保無回頭路。")
    except Exception as e:
        print(f"[錯誤] 搜尋中繼點失敗: {e}")
        
    return waypoints


def get_route_matrix_v2(start_coords, end_coords, waypoints):
    """
    3. 多點步行路由引擎 (OSRM API)
    """
    all_points = [start_coords] + waypoints + [end_coords]
    coord_string = ";".join([f"{pt[0]},{pt[1]}" for pt in all_points])
    
    url = f"http://router.project-osrm.org/route/v1/foot/{coord_string}"
    params = {
        'overview': 'full',
        'geometries': 'geojson'
    }
    
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data.get('code') == 'Ok':
            route = data['routes'][0]
            return {
                "geometry": route['geometry']['coordinates'],
                "distance": route['distance'],
                "duration": route['duration']
            }
    return None