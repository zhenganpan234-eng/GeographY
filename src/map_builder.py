import folium

def build_soul_map(route_geometry, social_energy, waypoint_details):
    """
    利用 Folium 繪製互動式地圖
    waypoint_details: 包含篩選後中繼點名稱與座標的 list, 格式如 [{'name': '...', 'coords': [lon, lat]}]
    """
    folium_polyline = [[pt[1], pt[0]] for pt in route_geometry]
    center_lat = folium_polyline[0][0]
    center_lon = folium_polyline[0][1]
    
    # 根據社交能量決定地圖風格
    if int(social_energy) < 40:
        map_tiles = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
        map_attr = '&copy; OpenStreetMap &copy; CARTO'
        line_color = '#0055ff'
        mode_text = "I人模式：社交安全防護罩防禦中 🛡️"
        icon_color = 'cadetblue' # 沉靜的藍綠色
    else:
        map_tiles = 'OpenStreetMap'
        map_attr = None
        line_color = '#ff1a75'
        mode_text = "偽E人模式：尋找命中注定的擦肩而過 💖"
        icon_color = 'orange' # 活潑的橘色
        
    mymap = folium.Map(location=[center_lat, center_lon], zoom_start=15, tiles=map_tiles, attr=map_attr)
    
    # 畫出情緒路線
    folium.PolyLine(locations=folium_polyline, color=line_color, weight=7, opacity=0.85, popup=mode_text).add_to(mymap)
    
    # 1. 標示【相關景點中繼點】的大頭針 (新功能 🌟)
    for idx, wp in enumerate(waypoint_details, 1):
        # wp['coords'] 是 [lon, lat]，Folium 需要 [lat, lon]
        wp_lat = wp['coords'][1]
        wp_lon = wp['coords'][0]
        
        popup_html = f"<b>📍 情緒站點 {idx}: {wp['name']}</b><br><span style='color:#666;'>順路造訪的療癒角落</span>"
        
        folium.Marker(
            location=[wp_lat, wp_lon],
            popup=folium.Popup(popup_html, max_width=250),
            # 使用數字標籤讓使用者跟左側列表對照
            icon=folium.Icon(color=icon_color, icon='heart' if int(social_energy) >= 40 else 'eye-close')
        ).add_to(mymap)
    
    # 2. 起終點 Marker
    folium.Marker(location=folium_polyline[0], popup="你的出發點", icon=folium.Icon(color='green', icon='play')).add_to(mymap)
    folium.Marker(location=folium_polyline[-1], popup="靈魂目的地", icon=folium.Icon(color='red', icon='flag')).add_to(mymap)
    
    return mymap._repr_html_()