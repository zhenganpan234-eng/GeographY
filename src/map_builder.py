import folium

def build_soul_map(route_geometry, social_energy):
    """
    利用 Folium 繪製互動式地圖，並根據社交能量切換 I人/E人 視覺風格
    """
    # 因為 OSRM 回傳的是 [經度, 緯度]，但 Folium 畫圖要求 [緯度, 經度]，所以要把每一組座標反轉
    folium_polyline = [[pt[1], pt[0]] for pt in route_geometry]
    
    # 找尋軌跡的中心點，作為地圖開啟時的預設中心
    center_lat = folium_polyline[0][0]
    center_lon = folium_polyline[0][1]
    
    # 根據社交能量決定地圖風格
    if int(social_energy) < 40:
        # I人模式：採用暗色調底圖
        map_tiles = 'CartoDB dark_matter'
        line_color = '#1a8cff'  # 幽靜深藍色
        mode_text = "I人模式：社交安全防護罩防禦中 🛡️"
    else:
        # E人模式：採用明亮色調底圖
        map_tiles = 'OpenStreetMap'
        line_color = '#ff4d94'  # 浪漫粉紅色
        mode_text = "偽E人模式：尋找命中注定的擦肩而過 💖"
        
    # 建立 Folium 地圖物件
    mymap = folium.Map(location=[center_lat, center_lon], zoom_start=14, tiles=map_tiles)
    
    # 在地圖上畫出 OSRM 沿著馬路的漂亮導航線條
    folium.PolyLine(
        locations=folium_polyline,
        color=line_color,
        weight=6,
        opacity=0.8,
        popup=mode_text
    ).add_to(mymap)
    
    # 在起點和終點加上大頭針標記
    folium.Marker(location=folium_polyline[0], popup="你的出發點", icon=folium.Icon(color='green')).add_to(mymap)
    folium.Marker(location=folium_polyline[-1], popup="靈魂目的地", icon=folium.Icon(color='red')).add_to(mymap)
    
    # 將地圖物件轉換成 HTML 字串，好讓網頁能夠直接渲染
    return mymap._repr_html_()