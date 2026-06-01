import requests
import math

# ── 步行速度常數 ──────────────────────────────────────────────────────────────
WALK_SPEED_MS = 1.4          # 公尺/秒（成人正常步行約 5 km/h）

# 步行可達性過濾閾值：
# OSRM 實際時間 / 直線距離理論時間 的比值上限。
# 比值 = 1.0 表示完全直線，現實中小巷約 1.3~1.5，走大馬路繞路會到 2.5+。
# 設 2.0 → 超過就代表「需要走行人不友善的路段才能到達」，排除。
WALKABILITY_RATIO_MAX = 2.0


def get_geocode(address):
    """
    1. 地名解析 (Nominatim API)
    """
    url = "https://nominatim.openstreetmap.org/search"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    params = {'q': address, 'countrycodes': 'tw', 'format': 'json',
              'limit': 1, 'accept-language': 'zh-TW'}
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200 and len(response.json()) > 0:
            result = response.json()[0]
            return [float(result['lon']), float(result['lat'])]
    except Exception as e:
        print(f"[錯誤] Nominatim 定位失敗: {e}")
    return None


# ── 黑名單：名稱中含有這些關鍵字的地點一律排除 ──────────────────────────────
NAME_BLACKLIST = [
    # 便利商店
    "7-ELEVEN", "7eleven", "711", "全家", "FamilyMart", "萊爾富", "OK超商", "OK mart",
    # 銀行 / 郵局 / 金融
    "銀行", "郵局", "信用合作社", "農會", "漁會", "ATM",
]

def is_blacklisted(name: str) -> bool:
    name_lower = name.lower()
    return any(kw.lower() in name_lower for kw in NAME_BLACKLIST)


# ── Mood → 搜尋關鍵字對照表 ──────────────────────────────────────────────────
MOOD_QUERY_MAP = {
    "放鬆": ["公園", "咖啡廳"],
    "文青": ["書店", "咖啡廳"],
    "探索": ["景點", "小路"],
    "社交": ["商圈", "夜市"],
    "療癒": ["公園", "圖書館"],
}


def _haversine_distance(lon1, lat1, lon2, lat2):
    """兩點間的直線距離（公尺）"""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _filter_by_walkability(candidates, start_coords, end_coords):
    """
    步行可達性過濾（核心新功能）
    ─────────────────────────────
    原理：對每個候選中繼點，用 OSRM /table 取得：
      - start → waypoint 的實際步行時間
      - waypoint → end   的實際步行時間
    再和直線距離換算的理論時間比較。
    若任一段的「實際/理論」比值 > WALKABILITY_RATIO_MAX，
    代表那段路需要繞行人不友善的路段（快速道路、省道等），直接排除該中繼點。

    只用 1 次 OSRM /table 呼叫取得所有點對點時間。
    """
    if not candidates:
        return candidates

    # 組合所有點：index 0 = start, 1..N = 候選中繼點, N+1 = end
    all_points = [start_coords] + [c['coords'] for c in candidates] + [end_coords]
    coord_string = ";".join([f"{pt[0]},{pt[1]}" for pt in all_points])
    url = f"http://router.project-osrm.org/table/v1/foot/{coord_string}"

    try:
        response = requests.get(url, params={'annotations': 'duration'}, timeout=10)
        if response.status_code != 200:
            print("[警告] 步行可達性過濾 API 失敗，略過過濾")
            return candidates
        data = response.json()
        if data.get('code') != 'Ok':
            print("[警告] 步行可達性過濾回傳異常，略過過濾")
            return candidates

        matrix = data['durations']  # N×N，單位：秒
        start_idx = 0
        end_idx = len(all_points) - 1

        passed = []
        for i, candidate in enumerate(candidates):
            wp_idx = i + 1  # 在 all_points 裡的 index
            wp_lon, wp_lat = candidate['coords']

            # ── start → waypoint ──
            actual_s2w = matrix[start_idx][wp_idx]
            dist_s2w = _haversine_distance(
                start_coords[0], start_coords[1], wp_lon, wp_lat)
            theory_s2w = dist_s2w / WALK_SPEED_MS  # 秒

            # ── waypoint → end ──
            actual_w2e = matrix[wp_idx][end_idx]
            dist_w2e = _haversine_distance(
                wp_lon, wp_lat, end_coords[0], end_coords[1])
            theory_w2e = dist_w2e / WALK_SPEED_MS

            # 避免除以零（理論時間 < 5 秒的點幾乎就是起終點本身）
            if theory_s2w < 5 or theory_w2e < 5:
                continue

            ratio_s2w = actual_s2w / theory_s2w
            ratio_w2e = actual_w2e / theory_w2e

            if ratio_s2w > WALKABILITY_RATIO_MAX or ratio_w2e > WALKABILITY_RATIO_MAX:
                print(f"[步行過濾] 排除（繞路比 {max(ratio_s2w, ratio_w2e):.1f}x）：{candidate['name']}")
            else:
                print(f"[步行過濾] 通過（繞路比 {max(ratio_s2w, ratio_w2e):.1f}x）：{candidate['name']}")
                passed.append(candidate)

        print(f"[步行過濾] {len(candidates)} 個候選 → {len(passed)} 個通過")
        return passed

    except Exception as e:
        print(f"[警告] 步行可達性過濾發生錯誤: {e}，略過過濾")
        return candidates


def get_mood_waypoints(start_coords, end_coords, mood, social_energy):
    """
    2. 動態向量篩選演算法 (Dynamic Waypoint Scaling)
    根據起終點距離自動增減沿途景點數量，並維持完美的順向感。
    最後加上 OSRM 步行可達性過濾，排除行人不適合的路段。
    """
    url = "https://nominatim.openstreetmap.org/search"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    # 社交能量低 → 強制導向安靜地點
    if int(social_energy) < 40:
        queries = ["公園", "圖書館"]
    else:
        queries = MOOD_QUERY_MAP.get(mood, ["咖啡廳"])

    lon_s, lat_s = start_coords[0], start_coords[1]
    lon_e, lat_e = end_coords[0], end_coords[1]

    direct_dist = math.sqrt((lon_e - lon_s)**2 + (lat_e - lat_s)**2) * 100
    print(f"[距離偵測] 起終點直線距離約為：{round(direct_dist, 2)} 公里")

    if direct_dist < 1.5:
        max_waypoints = 2
        search_limit = 10
    elif 1.5 <= direct_dist <= 3.0:
        max_waypoints = 3
        search_limit = 15
    else:
        max_waypoints = 5
        search_limit = 20

    box_buffer = max(0.02, direct_dist * 0.01)
    center_lon = (lon_s + lon_e) / 2
    center_lat = (lat_s + lat_e) / 2
    left, right = center_lon - box_buffer, center_lon + box_buffer
    bottom, top = center_lat - box_buffer, center_lat + box_buffer

    ax = lon_e - lon_s
    ay = lat_e - lat_s
    ab_length_sq = ax**2 + ay**2
    if ab_length_sq == 0:
        return []

    all_candidates = []

    for search_query in queries:
        params = {
            'q': search_query, 'countrycodes': 'tw',
            'viewbox': f"{left},{top},{right},{bottom}", 'bounded': 1,
            'format': 'json', 'limit': search_limit,
            'accept-language': 'zh-TW'
        }
        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                results = response.json()
                for item in results:
                    px = float(item['lon'])
                    py = float(item['lat'])
                    display_name = item.get('display_name', '').split(',')[0]

                    # 黑名單過濾
                    if is_blacklisted(display_name):
                        print(f"[黑名單] 排除：{display_name}")
                        continue

                    apx = px - lon_s
                    apy = py - lat_s
                    t = (apx * ax + apy * ay) / ab_length_sq
                    if 0.05 <= t <= 0.95:
                        proj_x = lon_s + t * ax
                        proj_y = lat_s + t * ay
                        perp_dist = math.sqrt((px - proj_x)**2 + (py - proj_y)**2)
                        max_deviation = 0.007 if direct_dist < 3.0 else 0.012
                        if perp_dist < max_deviation:
                            all_candidates.append({
                                'name': display_name,
                                'coords': [px, py],
                                'progress': t,
                                'type': search_query,
                            })
        except Exception as e:
            print(f"[錯誤] 順路篩選失敗 ({search_query}): {e}")

    # 去重（以座標四捨五入辨識）
    seen = set()
    unique_candidates = []
    for c in all_candidates:
        key = (round(c['coords'][0], 4), round(c['coords'][1], 4))
        if key not in seen:
            seen.add(key)
            unique_candidates.append(c)

    unique_candidates.sort(key=lambda k: k['progress'])

    # ── 步行可達性過濾（OSRM 驗證，排除行人不友善路段）────────────────
    walkable_candidates = _filter_by_walkability(unique_candidates, start_coords, end_coords)

    valid_waypoints = walkable_candidates[:max_waypoints]
    print(f"[幾何演算法決策] 最終精選出 {len(valid_waypoints)} 個沿途景點！")
    return valid_waypoints


# ── 以下為路線最佳化引擎（距離矩陣 + 最近鄰 + 2-opt）─────────────────────


def _get_distance_matrix(all_points):
    """
    用 OSRM /table 端點一次取得所有點對點的步行距離矩陣。
    回傳 N×N 的二維 list（單位：秒）。
    """
    coord_string = ";".join([f"{pt[0]},{pt[1]}" for pt in all_points])
    url = f"http://router.project-osrm.org/table/v1/foot/{coord_string}"
    try:
        response = requests.get(url, params={'annotations': 'duration'}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == 'Ok':
                return data['durations']
    except Exception as e:
        print(f"[錯誤] 距離矩陣取得失敗: {e}")
    return None


def _nearest_neighbor(matrix, start_idx, waypoint_indices, end_idx):
    """最近鄰貪心：從 start 出發，每次選最近未訪問的中繼點。"""
    unvisited = list(waypoint_indices)
    current = start_idx
    order = []
    while unvisited:
        nearest = min(unvisited, key=lambda idx: matrix[current][idx])
        order.append(nearest)
        unvisited.remove(nearest)
        current = nearest
    return order


def _two_opt(matrix, route):
    """2-opt 局部搜尋：反轉子段若能縮短總距離則接受，start/end 固定。"""
    best = route[:]
    improved = True
    while improved:
        improved = False
        for i in range(1, len(best) - 2):
            for j in range(i + 1, len(best) - 1):
                before = matrix[best[i-1]][best[i]] + matrix[best[j]][best[j+1]]
                after  = matrix[best[i-1]][best[j]] + matrix[best[i]][best[j+1]]
                if after < before - 1e-6:
                    best[i:j+1] = best[i:j+1][::-1]
                    improved = True
    return best


def _total_route_cost(matrix, route):
    return sum(matrix[route[k]][route[k+1]] for k in range(len(route) - 1))


def get_route_matrix_v2(start_coords, end_coords, waypoints_coords):
    """
    3. 最短路徑步行路由引擎
    流程：
      (1) OSRM /table  → 距離矩陣（1次呼叫）
      (2) 最近鄰貪心   → 初始中繼點排列
      (3) 2-opt 優化   → 消除交叉、縮短總距離
      (4) OSRM /route  → 用最佳排列取得實際路線（1次呼叫）
    共 2 次 API 呼叫。
    """
    if not waypoints_coords:
        all_points = [start_coords, end_coords]
        coord_string = ";".join([f"{pt[0]},{pt[1]}" for pt in all_points])
        url = f"http://router.project-osrm.org/route/v1/foot/{coord_string}"
        try:
            response = requests.get(url, params={'overview': 'full', 'geometries': 'geojson'}, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 'Ok':
                    route = data['routes'][0]
                    return {
                        "geometry": route['geometry']['coordinates'],
                        "distance": route['distance'],
                        "duration": route['duration'],
                        "optimized_order": [],
                    }
        except Exception as e:
            print(f"[錯誤] 直接路線失敗: {e}")
        return None

    all_points = [start_coords] + waypoints_coords + [end_coords]
    start_idx = 0
    end_idx = len(all_points) - 1
    waypoint_indices = list(range(1, end_idx))

    # (1) 距離矩陣
    matrix = _get_distance_matrix(all_points)
    if matrix is None:
        print("[警告] 距離矩陣失敗，改用原始順序")
        optimized_wp_indices = waypoint_indices
    else:
        # (2) 最近鄰貪心
        greedy_order = _nearest_neighbor(matrix, start_idx, waypoint_indices, end_idx)

        # (3) 2-opt 優化
        full_route = [start_idx] + greedy_order + [end_idx]
        optimized_route = _two_opt(matrix, full_route)
        optimized_wp_indices = optimized_route[1:-1]

        before_cost = _total_route_cost(matrix, [start_idx] + waypoint_indices + [end_idx])
        after_cost  = _total_route_cost(matrix, optimized_route)
        print(f"[路線優化] 原始成本={round(before_cost)}s → 優化後={round(after_cost)}s "
              f"(節省 {round(before_cost - after_cost)}s)")

    optimized_waypoints = [all_points[i] for i in optimized_wp_indices]

    # (4) 最終路線
    final_points = [start_coords] + optimized_waypoints + [end_coords]
    coord_string = ";".join([f"{pt[0]},{pt[1]}" for pt in final_points])
    url = f"http://router.project-osrm.org/route/v1/foot/{coord_string}"
    try:
        response = requests.get(url, params={'overview': 'full', 'geometries': 'geojson'}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == 'Ok':
                route = data['routes'][0]
                return {
                    "geometry": route['geometry']['coordinates'],
                    "distance": route['distance'],
                    "duration": route['duration'],
                    "optimized_order": optimized_wp_indices,
                }
    except Exception as e:
        print(f"[錯誤] 最終路線查詢失敗: {e}")
    return None