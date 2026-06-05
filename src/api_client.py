import requests
import math
import random
from src.custom_places import load_custom_places

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


# ── 白名單：只允許這些 OSM class 的地點進入候選 ──────────────────────────────
# 黑名單永遠補不完公司行號的種類，白名單才是根本解法。
# Nominatim 回傳的 'class' 欄位只要不在此集合內，一律排除。
OSM_CLASS_WHITELIST = {
    "leisure",      # 公園、運動場、綠地
    "amenity",      # 咖啡廳、圖書館、文化設施等
    "tourism",      # 景點、博物館、旅遊地標
    "historic",     # 古蹟、歷史建築
    "natural",      # 自然地景
    "landuse",      # 土地利用（公園綠地等）
    "shop",         # 商店（書店、賣場等，再由 type 細篩）
    "building",     # 圖書館、書店、美術館等可能被標為 building
    "highway",      # 步道、環湖路線等可能被標為 highway
    "office",       # 部分藝文/研究場館會被誤標為 office
    "railway",      # 展覽館、車站共構商圈可能被誤標為 railway
}

# ── 在白名單通過後，再用 type 黑名單排除不適合的商店類型 ─────────────────────
OSM_TYPE_BLACKLIST = {
    # 便利商店
    "convenience",
    # 金融
    "bank", "atm", "bureau_de_change",
    # 加油站、汽車相關
    "fuel", "car_wash", "car_repair", "car_rental",
    # 醫療
    "doctors", "dentist", "veterinary", "pharmacy",
    # 餐飲速食（非散步目的地）
    "fast_food",
    # 工業、電力、倉儲設施
    "substation", "power", "industrial", "works", "warehouse",
}

# ── 名稱關鍵字黑名單（最後防線，class 過不了就到這） ─────────────────────────
NAME_BLACKLIST = [
    "股份有限公司", "有限公司", "企業社", "工業社", "工廠", "製造",
    "郵局", "信用合作社", "農會", "漁會", "ATM",
    "7-ELEVEN", "7eleven", "711", "全家", "FamilyMart", "萊爾富", "OK超商",
    "變電", "電廠", "歇業", "永久歇業", "施工中", "機房", "倉庫",
]

NAME_ALLOWLIST_KEYWORDS = [
    "美術館", "博物館", "藝廊", "展覽館", "展覽", "文化中心", "藝術中心", "廣場",
    "市場", "市集", "公園", "庭園", "河岸", "河濱", "港濱", "綠地",
    "步道", "孔廟", "城隍廟", "廟", "宮", "書店", "書局", "圖書館",
]
BUILDING_ALLOWED_KEYWORDS = [
    "圖書館", "書店", "書局", "美術館", "博物館", "藝廊", "展覽館",
    "展覽", "文化中心", "藝術中心", "孔廟", "城隍廟",
]
HIGHWAY_ALLOWED_KEYWORDS = [
    "步道", "散步道", "環湖", "登山", "廣場", "廟前", "孔廟", "城隍廟",
    "公園", "港濱", "綠地",
]
OFFICE_ALLOWED_KEYWORDS = ["美術館", "博物館", "藝廊", "展覽館", "展覽", "文化中心", "藝術中心"]
RAILWAY_ALLOWED_KEYWORDS = ["展覽館", "展覽", "商圈", "市場", "市集", "美術館", "博物館"]
INDOOR_CATEGORIES = {"書店", "圖書館", "咖啡廳", "藝文空間"}
OUTDOOR_CATEGORIES = {"公園", "庭園", "河岸", "步道", "古蹟", "廟宇", "市集", "夜市"}


def is_blacklisted(name: str, osm_class: str = "", osm_type: str = "") -> bool:
    """
    三層過濾（由寬到嚴）：
    1. OSM class 不在白名單 → 排除（攔截所有公司行號、辦公室、工業區）
    2. OSM type 在黑名單   → 排除（過濾白名單內的不適合子類型）
    3. 名稱關鍵字命中      → 排除（最後防線）
    """
    name_lower = name.lower()
    if any(kw.lower() in name_lower for kw in NAME_BLACKLIST):
        return True
    if osm_type.lower() in OSM_TYPE_BLACKLIST:
        return True
    osm_class = osm_class.lower()
    if osm_class not in OSM_CLASS_WHITELIST:
        return not any(keyword in name for keyword in NAME_ALLOWLIST_KEYWORDS)
    if osm_class == "building" and not any(keyword in name for keyword in BUILDING_ALLOWED_KEYWORDS):
        return True
    if osm_class == "highway" and not any(keyword in name for keyword in HIGHWAY_ALLOWED_KEYWORDS):
        return True
    if osm_class == "office" and not any(keyword in name for keyword in OFFICE_ALLOWED_KEYWORDS):
        return True
    if osm_class == "railway" and not any(keyword in name for keyword in RAILWAY_ALLOWED_KEYWORDS):
        return True
    return False


# ── 景點分類與搜尋關鍵字：中文優先，英文備援 ────────────────────────────────
SEARCH_KEYWORDS = {
    "公園": ["公園", "park"],
    "庭園": ["庭園", "花園", "garden"],
    "河岸": ["河岸", "河濱", "河堤", "waterfront"],
    "步道": ["步道", "trail"],
    "咖啡廳": ["咖啡廳", "咖啡", "cafe"],
    "書店": ["書店", "書局", "bookstore"],
    "圖書館": ["圖書館", "library"],
    "藝文空間": ["藝廊", "美術館", "展覽", "gallery", "museum"],
    "古蹟": ["古蹟", "歷史建築", "historic"],
    "廟宇": ["廟", "宮", "temple"],
    "市集": ["市場", "市集", "market"],
    "夜市": ["夜市", "night market"],
    "商圈": ["商圈", "shopping district"],
}

MOOD_CATEGORY_WEIGHTS = {
    "放鬆": {
        "公園": 1.0, "庭園": 1.0, "河岸": 0.9, "步道": 0.8,
        "咖啡廳": 0.8, "書店": 0.7, "圖書館": 0.7,
        "藝文空間": 0.5, "古蹟": 0.5, "廟宇": 0.4,
        "市集": 0.3, "夜市": 0.2, "商圈": 0.3,
    },
    "文青": {
        "書店": 1.0, "咖啡廳": 0.9, "圖書館": 0.8,
        "藝文空間": 0.9, "古蹟": 0.7, "庭園": 0.6,
        "公園": 0.5, "河岸": 0.5, "步道": 0.4,
        "廟宇": 0.5, "市集": 0.4, "夜市": 0.3, "商圈": 0.4,
    },
    "探索": {
        "古蹟": 1.0, "廟宇": 0.9, "藝文空間": 0.8,
        "市集": 0.8, "河岸": 0.6, "書店": 0.5,
        "公園": 0.5, "咖啡廳": 0.5, "庭園": 0.5,
        "步道": 0.7, "夜市": 0.6, "商圈": 0.6, "圖書館": 0.4,
    },
    "社交": {
        "市集": 1.0, "夜市": 1.0, "商圈": 0.9,
        "咖啡廳": 0.7, "藝文空間": 0.6,
        "公園": 0.4, "河岸": 0.4, "庭園": 0.3,
        "書店": 0.3, "圖書館": 0.2, "古蹟": 0.5, "廟宇": 0.5, "步道": 0.3,
    },
    "療癒": {
        "公園": 1.0, "庭園": 1.0, "河岸": 0.9,
        "圖書館": 0.8, "書店": 0.7, "咖啡廳": 0.7,
        "步道": 0.8, "古蹟": 0.5, "藝文空間": 0.5,
        "廟宇": 0.5, "市集": 0.3, "夜市": 0.2, "商圈": 0.3,
    },
}

MOOD_QUERY_MAP = {
    mood: [category for category, _ in sorted(weights.items(), key=lambda item: item[1], reverse=True)]
    for mood, weights in MOOD_CATEGORY_WEIGHTS.items()
}

CATEGORY_STAY_MINUTES = {
    "公園": (15, 30),
    "庭園": (15, 30),
    "河岸": (20, 30),
    "步道": (30, 60),

    "咖啡廳": (30, 70),
    "書店": (20, 70),
    "圖書館": (30, 70),

    "藝文空間": (30, 70),
    "古蹟": (20, 40),
    "廟宇": (15, 30),

    "市集": (30, 60),
    "夜市": (30, 70),
    "商圈": (30, 70),
}

QUIET_CATEGORIES = {"公園", "庭園", "河岸", "步道", "圖書館", "書店", "咖啡廳", "藝文空間"}
SOCIAL_CATEGORIES = {"商圈", "市集", "夜市", "咖啡廳", "藝文空間", "公園", "庭園", "河岸", "步道"}


def _haversine_distance(lon1, lat1, lon2, lat2):
    """兩點間的直線距離（公尺）"""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def _suggest_stay_minutes(category, total_minutes):
    low, high = CATEGORY_STAY_MINUTES.get(category, (8, 15))
    if total_minutes <= 45:
        return round_to_5(low)
    if total_minutes >= 120:
        return round_to_5(high)
    ratio = (total_minutes - 45) / 75
    return round_to_5(low + (high - low) * ratio)


def round_to_5(minutes):
    return max(5, round(minutes / 5) * 5)


def _extract_place_name(item):
    namedetails = item.get("namedetails") or {}
    name = (
        namedetails.get("name:zh")
        or namedetails.get("name:zh-TW")
        or namedetails.get("name")
        or item.get("name")
        or item.get("display_name", "").split(",")[0]
    )
    return name.strip() or item.get("display_name", "未命名地點").split(",")[0]


def _place_key(name):
    return (name or "").strip().lower()


def _distance_score(walk_minutes):
    if walk_minutes <= 5:
        return 1.25
    if walk_minutes <= 10:
        return 1.0
    if walk_minutes <= 20:
        return 0.55
    return 0.15


def _score_candidate(candidate, mood, social_energy, category_counts, search_radius_m, memory, exploration_mode, environment_preference):
    distance_score = _distance_score(candidate.get("direct_walk_minutes", 999))
    mood_score = MOOD_CATEGORY_WEIGHTS.get(mood, {}).get(candidate["category"], 0.45)

    energy = int(social_energy)
    if energy < 40:
        social_score = 1.25 if candidate["category"] in QUIET_CATEGORIES else 0.05
    elif energy >= 70:
        social_score = 1.2 if candidate["category"] in SOCIAL_CATEGORIES else 0.35
    else:
        social_score = 0.85

    rarity_score = 1 / max(category_counts.get(candidate["category"], 1), 1)
    stay = candidate["stay_minutes"]
    stay_value_score = 1 if 5 <= stay <= 30 else 0.65

    key = _place_key(candidate["name"])
    liked = key in memory.get("liked", set())
    visited = key in memory.get("visited", set())
    memory_bonus = 0

    if exploration_mode == "回憶模式":
        if liked and visited:
            memory_bonus += 120
        elif visited:
            memory_bonus += 75
        elif liked:
            memory_bonus += 45
        else:
            memory_bonus -= 10
    elif exploration_mode == "平衡模式":
        if liked:
            memory_bonus += 15
        if not visited:
            memory_bonus += 15
    elif exploration_mode == "探索模式":
        if not visited:
            memory_bonus += 35
        if liked:
            memory_bonus -= 10

    if energy < 35 and candidate["category"] in SOCIAL_CATEGORIES:
        memory_bonus -= 25
    if energy >= 75 and candidate["category"] in QUIET_CATEGORIES:
        memory_bonus -= 10

    environment_bonus = 0
    if environment_preference == "偏好室內":
        environment_bonus = 20 if candidate["category"] in INDOOR_CATEGORIES or candidate.get("environment") == "室內" else 0
    elif environment_preference == "偏好戶外":
        environment_bonus = 20 if candidate["category"] in OUTDOOR_CATEGORIES or candidate.get("environment") == "戶外" else 0

    score = (
        distance_score * 70
        + mood_score * 30
        + social_score * 35
        + rarity_score * 12
        + stay_value_score * 8
        + memory_bonus
        + environment_bonus
        + random.uniform(0, 8)
    )
    return score


def _recommendation_reason(candidate, mood, social_energy, memory, exploration_mode):
    key = _place_key(candidate["name"])
    if key in memory.get("blocked", set()):
        return ""
    if (
        exploration_mode == "回憶模式"
        and key in memory.get("liked", set())
        and key in memory.get("visited", set())
    ):
        return "你曾造訪且喜歡這個景點，回憶模式會優先推薦。"
    if exploration_mode == "回憶模式" and key in memory.get("liked", set()):
        return "你曾喜歡這個景點，適合回來慢慢走一遍。"
    if exploration_mode == "回憶模式" and key in memory.get("visited", set()):
        return "你曾造訪過這裡，適合回憶模式。"
    if exploration_mode == "探索模式" and key not in memory.get("visited", set()):
        return "你尚未探索過這個地點。"
    if int(social_energy) < 40 and candidate["category"] in QUIET_CATEGORIES:
        return "符合低社交能量需求，環境相對安靜。"
    if candidate["category"] in {"書店", "圖書館", "咖啡廳"}:
        return "適合停留，也和目前心境相容。"
    if candidate["category"] in {"公園", "庭園", "河岸", "步道"}:
        return "有自然或開放空間，適合作為療癒停留點。"
    return f"符合「{mood}」偏好的 {candidate['category']} 類景點。"


def _dedupe_candidates(candidates):
    seen = set()
    unique_candidates = []
    for candidate in candidates:
        key = (round(candidate["coords"][0], 4), round(candidate["coords"][1], 4))
        if key not in seen:
            seen.add(key)
            unique_candidates.append(candidate)
    return unique_candidates


def _curated_candidates(start_coords, total_minutes, max_walk_minutes, memory):
    candidates = []
    lon_s, lat_s = start_coords
    max_distance_m = max_walk_minutes * 60 * WALK_SPEED_MS * 0.75
    for place in load_custom_places():
        if _place_key(place["name"]) in memory.get("blocked", set()):
            continue
        px, py = place["coords"]
        if abs(float(px)) < 90 < abs(float(py)):
            px, py = py, px
        distance_m = _haversine_distance(lon_s, lat_s, px, py)
        direct_walk_minutes = distance_m / WALK_SPEED_MS / 60
        if distance_m > max_distance_m:
            continue
        low, high = CATEGORY_STAY_MINUTES.get(place["category"], (15, 30))
        stay_minutes = round_to_5(high if total_minutes >= 120 else low if total_minutes <= 45 else round((low + high) / 2))
        candidates.append({
            "name": place["name"],
            "display_name": place["name"],
            "coords": [px, py],
            "type": place["category"],
            "category": place["category"],
            "osm_class": "curated",
            "osm_type": "curated",
            "environment": place.get("environment", ""),
            "distance_m": distance_m,
            "direct_walk_minutes": direct_walk_minutes,
            "stay_minutes": stay_minutes,
            "max_stay_minutes": high,
            "curated": True,
        })
    return candidates


def get_exploration_waypoints(start_coords, mood, social_energy, relaxation_minutes, memory=None, exploration_mode="平衡模式", max_walk_minutes=12, environment_preference="不限"):
    """
    依「起點 + 放鬆時長」建立城市療癒探索候選池。
    回傳已含停留時間、實際名稱與類別的 waypoint 清單，以及時間預算。
    """
    url = "https://nominatim.openstreetmap.org/search"
    headers = {'User-Agent': 'SoulPath/1.0 (time-based healing walk planner)'}

    memory = memory or {"liked": set(), "blocked": set(), "visited": set()}
    total_minutes = max(1, int(relaxation_minutes))
    max_walk_minutes = max(1, int(max_walk_minutes))
    buffer_minutes = min(8, max(3, round(total_minutes * 0.06)))
    usable_minutes = total_minutes - buffer_minutes
    target_stay_budget = max(10, round(usable_minutes)) # * 0.42 deleted
    target_walk_budget = usable_minutes - target_stay_budget

    max_waypoints = max(1, min(10, math.ceil(total_minutes / 20)))

    max_distance_m = max_walk_minutes * 60 * WALK_SPEED_MS * 0.75
    search_radius_m = _clamp(min(target_walk_budget * 45, max_distance_m), 350, 6500)
    lat_buffer = search_radius_m / 111000
    lon_buffer = search_radius_m / (111000 * max(math.cos(math.radians(start_coords[1])), 0.25))
    lon_s, lat_s = start_coords
    left, right = lon_s - lon_buffer, lon_s + lon_buffer
    bottom, top = lat_s - lat_buffer, lat_s + lat_buffer

    categories = list(SEARCH_KEYWORDS.keys())

    all_candidates = _curated_candidates(start_coords, total_minutes, max_walk_minutes, memory)
    for category in categories:
        for search_query in SEARCH_KEYWORDS[category]:
            params = {
                "q": search_query,
                "countrycodes": "tw",
                "viewbox": f"{left},{top},{right},{bottom}",
                "bounded": 1,
                "format": "json",
                "limit": 8,
                "accept-language": "zh-TW",
                "namedetails": 1,
            }
            try:
                response = requests.get(url, headers=headers, params=params, timeout=10)
                if response.status_code != 200:
                    continue
                for item in response.json():
                    px = float(item["lon"])
                    py = float(item["lat"])
                    name = _extract_place_name(item)
                    display_name = item.get("display_name", name)
                    osm_class = item.get("class", "")
                    osm_type = item.get("type", "")
                    if _place_key(name) in memory.get("blocked", set()):
                        print(f"[個人黑名單] 排除：{name}")
                        continue
                    if is_blacklisted(name, osm_class, osm_type):
                        print(f"[候選過濾] 排除 [{osm_class}/{osm_type}]：{name}")
                        continue

                    distance_m = _haversine_distance(lon_s, lat_s, px, py)
                    direct_walk_minutes = distance_m / WALK_SPEED_MS / 60
                    if distance_m < 80 or distance_m > search_radius_m or direct_walk_minutes > max_walk_minutes:
                        continue

                    stay_low, stay_high = CATEGORY_STAY_MINUTES.get(category, (15, 30))
                    all_candidates.append({
                        "name": name,
                        "display_name": display_name,
                        "coords": [px, py],
                        "type": category,
                        "category": category,
                        "osm_class": osm_class,
                        "osm_type": osm_type,
                        "environment": "室內" if category in INDOOR_CATEGORIES else "戶外" if category in OUTDOOR_CATEGORIES else "",
                        "distance_m": distance_m,
                        "direct_walk_minutes": direct_walk_minutes,
                        "stay_minutes": _suggest_stay_minutes(category, total_minutes),
                        "max_stay_minutes": stay_high,
                    })
            except Exception as e:
                print(f"[錯誤] 周邊候選搜尋失敗 ({search_query}): {e}")

    unique_candidates = _dedupe_candidates(all_candidates)
    if not unique_candidates:
        return [], {
            "total": total_minutes,
            "walking": 0,
            "stay": 0,
            "buffer": buffer_minutes,
        }

    category_counts = {}
    for candidate in unique_candidates:
        category_counts[candidate["category"]] = category_counts.get(candidate["category"], 0) + 1

    for candidate in unique_candidates:
        candidate["score"] = _score_candidate(
            candidate, mood, social_energy, category_counts, search_radius_m, memory, exploration_mode, environment_preference
        )
        candidate["recommendation_reason"] = _recommendation_reason(
            candidate, mood, social_energy, memory, exploration_mode
        )

    unique_candidates.sort(key=lambda c: c["score"], reverse=True)
    pool = unique_candidates[:min(len(unique_candidates), 18)]

    selected = []
    used_categories = set()
    stay_total = 0
    for candidate in pool:
        if len(selected) >= max_waypoints:
            break
        if (
            candidate["category"] in used_categories
            and len(used_categories) < len(categories)
            and len(selected) < max(3, max_waypoints // 2)
        ):
            continue
        projected_stay = stay_total + candidate["stay_minutes"]
        if projected_stay > target_stay_budget and selected:
            continue
        approx_walk_minutes = ((candidate["distance_m"] * 2) / WALK_SPEED_MS) / 60
        if selected:
            farthest = max([wp["distance_m"] for wp in selected] + [candidate["distance_m"]])
            approx_walk_minutes = ((farthest * 2.4) / WALK_SPEED_MS) / 60
        if approx_walk_minutes <= max_walk_minutes * max(1.5, len(selected) + 1):
            selected.append(candidate)
            used_categories.add(candidate["category"])
            stay_total = projected_stay

    if not selected:
        selected = pool[:1]
        stay_total = selected[0]["stay_minutes"]

    return selected, {
        "total": total_minutes,
        "walking": max(0, total_minutes - stay_total - buffer_minutes),
        "stay": stay_total,
        "buffer": buffer_minutes,
    }


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
                    osm_class = item.get('class', '')
                    osm_type  = item.get('type', '')

                    # 黑名單過濾（名稱 + OSM class/type 雙重檢查）
                    if is_blacklisted(display_name, osm_class, osm_type):
                        print(f"[黑名單] 排除 [{osm_class}/{osm_type}]：{display_name}")
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


def get_route_matrix_v2(start_coords, end_coords, waypoints_coords, optimize=True):
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
                        "legs": route.get("legs", []),
                        "leg_geometries": [route['geometry']['coordinates']],
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
    if not optimize:
        optimized_wp_indices = waypoint_indices
    elif matrix is None:
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
        response = requests.get(
            url,
            params={'overview': 'full', 'geometries': 'geojson', 'steps': 'true'},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == 'Ok':
                route = data['routes'][0]
                leg_geometries = []
                for leg in route.get("legs", []):
                    coords = []
                    for step in leg.get("steps", []):
                        step_coords = step.get("geometry", {}).get("coordinates", [])
                        if coords and step_coords and coords[-1] == step_coords[0]:
                            coords.extend(step_coords[1:])
                        else:
                            coords.extend(step_coords)
                    leg_geometries.append(coords)
                return {
                    "geometry": route['geometry']['coordinates'],
                    "distance": route['distance'],
                    "duration": route['duration'],
                    "legs": route.get("legs", []),
                    "leg_geometries": leg_geometries,
                    "optimized_order": optimized_wp_indices,
                }
    except Exception as e:
        print(f"[錯誤] 最終路線查詢失敗: {e}")
    return None
