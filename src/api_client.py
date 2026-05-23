import requests
import math

def get_geocode(address):
    """
    1. 地名解析 (Nominatim API)
    """
    url = "https://nominatim.openstreetmap.org/search"
    headers = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' }
    params = { 'q': address, 'countrycodes': 'tw', 'format': 'json', 'limit': 1, 'accept-language': 'zh-TW' }
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
    2. 動態向量篩選演算法 (Dynamic Waypoint Scaling)
    根據起終點距離，自動增減沿途景點數量，並維持完美的順向感！
    """
    url = "https://nominatim.openstreetmap.org/search"
    headers = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' }
    
    if int(social_energy) < 40:
        search_query = "公園"
    else:
        search_query = "書店" if mood == "文青" else ("商圈" if mood == "社交" else "咖啡廳")
            
    lon_s, lat_s = start_coords[0], start_coords[1]
    lon_e, lat_e = end_coords[0], end_coords[1]
    
    # 💡 核心優化：計算起終點的估計直線距離（經緯度粗估：0.01度約1公里）
    direct_dist = math.sqrt((lon_e - lon_s)**2 + (lat_e - lat_s)**2) * 100
    print(f"[距離偵測] 起終點直線距離約為：{round(direct_dist, 2)} 公里")
    
    # 💡 根據距離，動態決定我們要精選幾個中繼站 (Max Waypoints)
    if direct_dist < 1.5:
        max_waypoints = 2     # 短程
        search_limit = 10
    elif 1.5 <= direct_dist <= 3.0:
        max_waypoints = 3     # 中程
        search_limit = 15
    else:
        max_waypoints = 5     # 長程深度遊
        search_limit = 20
        
    # 動態調整搜尋方框大小 (路程越長，方框隨之等比例擴大，才抓得到沿途的點)
    box_buffer = max(0.02, direct_dist * 0.01)
    center_lon = (lon_s + lon_e) / 2
    center_lat = (lat_s + lat_e) / 2
    left, right = center_lon - box_buffer, center_lon + box_buffer
    bottom, top = center_lat - box_buffer, center_lat + box_buffer
    
    params = {
        'q': search_query, 'countrycodes': 'tw',
        'viewbox': f"{left},{top},{right},{bottom}", 'bounded': 1,
        'format': 'json', 'limit': search_limit, 
        'accept-language': 'zh-TW'
    }
    
    valid_waypoints = []
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            results = response.json()
            
            ax = lon_e - lon_s
            ay = lat_e - lat_s
            ab_length_sq = ax**2 + ay**2
            
            if ab_length_sq == 0:
                return []

            pts_with_scores = []
            for item in results:
                px = float(item['lon'])
                py = float(item['lat'])
                
                display_name = item.get('display_name', '').split(',')[0]
                
                apx = px - lon_s
                apy = py - lat_s
                t = (apx * ax + apy * ay) / ab_length_sq
                
                # 向量過濾：必須在起終點的前進區段內
                if 0.05 <= t <= 0.95:
                    proj_x = lon_s + t * ax
                    proj_y = lat_s + t * ay
                    perp_dist = math.sqrt((px - proj_x)**2 + (py - proj_y)**2)
                    
                    # 偏離距離限制（路程長時稍微放寬一點點偏離度，路網才豐富）
                    max_deviation = 0.007 if direct_dist < 3.0 else 0.012
                    if perp_dist < max_deviation:
                        pts_with_scores.append({
                            'name': display_name,
                            'coords': [px, py],
                            'progress': t
                        })
            
            # 依前進進度排序（確保順向不回頭）
            pts_with_scores.sort(key=lambda k: k['progress'])
            
            # 💡 依據前面算好的 max_waypoints 動態切片！
            valid_waypoints = pts_with_scores[:max_waypoints]
            print(f"[幾何演算法決策] 屬於計晝路程，動態精選出 {len(valid_waypoints)} 個沿途順路『{search_query}』！")
    except Exception as e:
        print(f"[錯誤] 順路篩選失敗: {e}")
        
    return valid_waypoints


def get_route_matrix_v2(start_coords, end_coords, waypoints_coords):
    """
    3. 多點步行路由引擎 (OSRM API)
    """
    all_points = [start_coords] + waypoints_coords + [end_coords]
    coord_string = ";".join([f"{pt[0]},{pt[1]}" for pt in all_points])
    
    url = f"http://router.project-osrm.org/route/v1/foot/{coord_string}"
    params = { 'overview': 'full', 'geometries': 'geojson' }
    
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