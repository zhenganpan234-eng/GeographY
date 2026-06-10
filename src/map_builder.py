import folium

# ── 每個 mood 對應的地圖主題設定 ──────────────────────────────────────────
MOOD_THEMES = {
    "放鬆": {
        "tiles": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        "attr": "&copy; OpenStreetMap &copy; CARTO",
        "line_color": "#5b8dee",
        "icon_color": "cadetblue",
        "icon_name": "leaf",
    },
    "文青": {
        "tiles": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        "attr": "&copy; OpenStreetMap &copy; CARTO",
        "line_color": "#9b59b6",
        "icon_color": "purple",
        "icon_name": "book",
    },
    "探索": {
        "tiles": "OpenStreetMap",
        "attr": None,
        "line_color": "#e67e22",
        "icon_color": "orange",
        "icon_name": "search",
    },
    "社交": {
        "tiles": "OpenStreetMap",
        "attr": None,
        "line_color": "#ff1a75",
        "icon_color": "red",
        "icon_name": "heart",
    },
    "療癒": {
        "tiles": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        "attr": "&copy; OpenStreetMap &copy; CARTO",
        "line_color": "#27ae60",
        "icon_color": "green",
        "icon_name": "tree-conifer",
    },
}

# 社交能量低強制覆蓋為 I 人主題
I_PERSON_THEME = {
    "tiles": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    "attr": "&copy; OpenStreetMap &copy; CARTO",
    "line_color": "#0055ff",
    "icon_color": "cadetblue",
    "icon_name": "eye-close",
}


def build_soul_map(route_geometry, social_energy, waypoint_details, mood="放鬆", route_segments=None, end_label="回到出發地附近"):
    """
    利用 Folium 繪製互動式地圖。
    - 依 mood 和 social_energy 切換地圖主題
    - 中繼點大頭針帶編號 popup
    - 起點與回程終點清楚標示
    """
    folium_polyline = [[pt[1], pt[0]] for pt in route_geometry]
    center_lat = folium_polyline[0][0]
    center_lon = folium_polyline[0][1]

    # 選擇主題
    if int(social_energy) < 40:
        theme = I_PERSON_THEME
        mode_text = "I人防護罩模式 🛡️ — 最小人潮暴露路線"
    else:
        theme = MOOD_THEMES.get(mood, MOOD_THEMES["放鬆"])
        mode_labels = {
            "放鬆": "放鬆漫步模式 🌿",
            "文青": "文青探索模式 📚",
            "探索": "城市探險模式 🗺️",
            "社交": "命定相遇模式 💫",
            "療癒": "心靈療癒模式 🌸",
        }
        mode_text = mode_labels.get(mood, "SoulPath 模式")

    mymap = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=15,
        tiles=theme["tiles"],
        attr=theme.get("attr") or "",
    )

    # 路線分段
    drew_segment = False
    if route_segments:
        for idx, segment in enumerate(route_segments, 1):
            geometry = segment.get("geometry") or []
            if not geometry:
                continue
            leg_polyline = [[pt[1], pt[0]] for pt in geometry]
            distance_text = f"{segment.get('distance_km', 0)} km"
            segment_text = f"步行 {segment.get('walking_minutes', '?')} 分鐘 ｜ {distance_text} ｜ {mode_text}"
            folium.PolyLine(
                locations=leg_polyline,
                color=theme["line_color"],
                weight=7,
                opacity=0.85,
                popup=folium.Popup(segment_text, max_width=300),
                tooltip=segment_text,
            ).add_to(mymap)
            drew_segment = True
    if not drew_segment:
        folium.PolyLine(
            locations=folium_polyline,
            color=theme["line_color"],
            weight=7,
            opacity=0.85,
            popup=folium.Popup(mode_text, max_width=300),
            tooltip=mode_text,
        ).add_to(mymap)

    # 中繼點大頭針
    for idx, wp in enumerate(waypoint_details, 1):
        wp_lat = wp['coords'][1]
        wp_lon = wp['coords'][0]
        wp_type = wp.get('type', '')
        stay_minutes = wp.get('stay_minutes')
        stay_text = f"｜建議停留 {stay_minutes} 分鐘" if stay_minutes else ""
        inbound = route_segments[idx - 1] if route_segments and idx - 1 < len(route_segments) else {}
        walk_text = ""
        if inbound:
            walk_text = f"<br><span style='color:#888; font-size:12px;'>前一段：步行 {inbound.get('walking_minutes')} 分鐘｜{inbound.get('distance_km')} km</span>"
        popup_html = (
            f"<b>📍 情緒站點 {idx}: {wp['name']}</b><br>"
            f"<span style='color:#888; font-size:12px;'>類型：{wp_type}{stay_text}｜城市療癒角落</span>"
            f"{walk_text}<br><a href='#stop-{idx * 2 + 1}'>查看行程說明</a>"
        )
        folium.Marker(
            location=[wp_lat, wp_lon],
            popup=folium.Popup(popup_html, max_width=260),
            tooltip=f"{wp['name']}｜{wp_type}",
            icon=folium.DivIcon(
                html=(
                    "<div style='width:28px;height:28px;border-radius:50%;"
                    f"background:{theme['line_color']};color:white;border:2px solid white;"
                    "box-shadow:0 2px 8px rgba(0,0,0,.28);display:flex;"
                    "align-items:center;justify-content:center;font-weight:700;"
                    "font-size:13px;'>"
                    f"{idx}</div>"
                ),
                icon_size=(28, 28),
                icon_anchor=(14, 14),
            ),
        ).add_to(mymap)

    # 起點
    folium.Marker(
        location=folium_polyline[0],
        popup="📍 你的出發點",
        tooltip="出發點",
        icon=folium.Icon(color='green', icon='play', prefix='glyphicon'),
    ).add_to(mymap)

    # 終點
    folium.Marker(
        location=folium_polyline[-1],
        popup=f"🏁 {end_label}",
        tooltip=end_label,
        icon=folium.Icon(color='red', icon='flag', prefix='glyphicon'),
    ).add_to(mymap)

    return mymap._repr_html_()
