"""
Save Liked Routes 收藏路線模組
對應 Proposal 第 7 項：Save Liked Routes
使用 JSON 檔案做輕量持久化儲存。
"""
import json
import os
from datetime import datetime

SAVE_FILE = "saved_routes.json"

def load_saved_routes():
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_route(start_place, end_place, mood, social_energy, distance, duration, waypoints, relaxation_minutes=None, exploration_mode=None, max_walk_minutes=None, environment_preference=None):
    routes = load_saved_routes()
    new_route = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "start": start_place,
        "end": end_place,
        "mood": mood,
        "social_energy": int(social_energy),
        "distance_km": distance,
        "duration_min": duration,
        "relaxation_minutes": relaxation_minutes or duration,
        "exploration_mode": exploration_mode or "平衡模式",
        "max_walk_minutes": max_walk_minutes or 12,
        "environment_preference": environment_preference or "不限",
        "waypoints": [wp["name"] for wp in waypoints],
    }
    routes.insert(0, new_route)
    # 最多保留 20 條
    routes = routes[:20]
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(routes, f, ensure_ascii=False, indent=2)
    return new_route["id"]

def delete_route(route_id):
    routes = load_saved_routes()
    routes = [r for r in routes if r["id"] != route_id]
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(routes, f, ensure_ascii=False, indent=2)
