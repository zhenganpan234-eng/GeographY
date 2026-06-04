import json
import os
from datetime import datetime

MEMORY_FILE = "place_memory.json"


def _empty_memory():
    return {
        "liked_places": [],
        "blocked_places": [],
        "visited_places": [],
    }


def load_place_memory():
    if not os.path.exists(MEMORY_FILE):
        return _empty_memory()
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _empty_memory()

    memory = _empty_memory()
    for key in memory:
        if isinstance(data.get(key), list):
            memory[key] = data[key]
    return memory


def save_place_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def _place_key(name):
    return (name or "").strip().lower()


def _upsert_place(items, place):
    key = _place_key(place.get("name"))
    if not key:
        return items
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    place = {
        "name": place.get("name"),
        "category": place.get("category") or place.get("type") or "",
        "coords": place.get("coords") or [],
        "saved_at": place.get("saved_at") or now,
    }
    existing = [item for item in items if _place_key(item.get("name")) != key]
    existing.insert(0, place)
    return existing[:200]


def like_place(place):
    memory = load_place_memory()
    memory["liked_places"] = _upsert_place(memory["liked_places"], place)
    save_place_memory(memory)


def block_place(place):
    memory = load_place_memory()
    memory["blocked_places"] = _upsert_place(memory["blocked_places"], place)
    save_place_memory(memory)


def mark_visited(places):
    memory = load_place_memory()
    for place in places:
        memory["visited_places"] = _upsert_place(memory["visited_places"], place)
    save_place_memory(memory)


def clear_memory_list(list_name):
    memory = load_place_memory()
    if list_name in memory:
        memory[list_name] = []
        save_place_memory(memory)


def remove_place(list_name, place_name):
    memory = load_place_memory()
    if list_name not in memory:
        return
    key = _place_key(place_name)
    memory[list_name] = [
        place for place in memory[list_name]
        if _place_key(place.get("name")) != key
    ]
    save_place_memory(memory)


def memory_sets(memory=None):
    memory = memory or load_place_memory()
    return {
        "liked": {_place_key(place.get("name")) for place in memory["liked_places"]},
        "blocked": {_place_key(place.get("name")) for place in memory["blocked_places"]},
        "visited": {_place_key(place.get("name")) for place in memory["visited_places"]},
    }
