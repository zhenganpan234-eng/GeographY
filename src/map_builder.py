import folium

def build_soul_map(route_geometry, social_energy):
    """
    利用 Folium 繪製互動式地圖，並根據社交能量切換 I人/E人 視覺風格
    (已優化低能量模式下的地圖可讀性，兼顧文青感與清晰度)
    """
    # 座標反轉 [經, 緯] -> [緯, 經] 供 Folium 使用
    folium_polyline = [[pt[1], pt[0]] for pt in route_geometry]
    
    # 取得地圖中心點
    center_lat = folium_polyline[0][0]
    center_lon = folium_polyline[0][1]
    
    # 根據社交能量決定地圖風格
    if int(social_energy) < 40:
        # 🛡️ I人疲勞模式：改用極簡淡雅的灰色圖磚，不刺眼且路名極度清晰
        map_tiles = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
        map_attr = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
        line_color = '#0055ff'  # 提高飽和度的亮藍色（在淺色底圖上非常顯眼）
        mode_text = "I人模式：社交安全防護罩防禦中 🛡️"
    else:
        # 💖 E人充能模式：標準明亮地圖
        map_tiles = 'OpenStreetMap'
        map_attr = None
        line_color = '#ff1a75'  # 浪漫亮粉紅色
        mode_text = "偽E人模式：尋找命中注定的擦肩而過 💖"
        
    # 建立地圖物件
    mymap = folium.Map(location=[center_lat, center_lon], zoom_start=14, tiles=map_tiles, attr=map_attr)
    
    # 在地圖上畫出蜿蜒的情緒路線（加粗 weight 到 7，大幅提升閱讀性）
    folium.PolyLine(
        locations=folium_polyline,
        color=line_color,
        weight=7,
        opacity=0.85,
        popup=mode_text
    ).add_to(mymap)
    
    # 在起點和終點加上標記
    folium.Marker(location=folium_polyline[0], popup="你的出發點", icon=folium.Icon(color='green', icon='play')).add_to(mymap)
    folium.Marker(location=folium_polyline[-1], popup="靈魂目的地", icon=folium.Icon(color='red', icon='flag')).add_to(mymap)
    
    return mymap._repr_html_()