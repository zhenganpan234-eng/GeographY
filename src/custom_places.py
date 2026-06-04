import json
import os

CUSTOM_PLACES_FILE = "custom_places.json"


def load_custom_places():
    if not os.path.exists(CUSTOM_PLACES_FILE):
        return []
    try:
        with open(CUSTOM_PLACES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save_custom_places(places):
    with open(CUSTOM_PLACES_FILE, "w", encoding="utf-8") as f:
        json.dump(places, f, ensure_ascii=False, indent=2)


def add_custom_place(place):
    places = load_custom_places()
    name = (place.get("name") or "").strip()
    if not name:
        return
    places = [
        item for item in places
        if (item.get("name") or "").strip().lower() != name.lower()
    ]
    places.insert(0, place)
    save_custom_places(places)


def delete_custom_place(name):
    key = (name or "").strip().lower()
    places = [
        item for item in load_custom_places()
        if (item.get("name") or "").strip().lower() != key
    ]
    save_custom_places(places)
