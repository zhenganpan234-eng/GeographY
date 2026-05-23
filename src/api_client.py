import requests

def get_mood_places(mood, social_energy):
    """
    根據使用者選擇的情緒(Mood)和社交能量(Social Energy)，
    決定要去 Nominatim 搜尋什麼種類的周邊設施。
    """
    url_geo = "https://nominatim.openstreetmap.org/search"
    
    # 偽裝成瀏覽器，防止被 Nominatim 官方阻擋
    headers = {
        'User-Agent': 'SoulPathApp/1.0 (peter@example.com) ComputerScienceProject'
    }
    
    # 實作 Proposal 的核心邏輯：
    # 如果社交能量太低（例如小於 40），不管選什麼情緒，一律強制去安靜無人的地方充電！
    if int(social_energy) < 40:
        # 搜尋新竹或台北附近的公園或圖書館
        search_query = "公園" 
    else:
        # 如果社交能量充沛，則根據情緒(Mood)來分類搜尋
        if mood == "文青":
            search_query = "書店"
        elif mood == "社交":
            search_query = "商圈"
        elif mood == "放鬆":
            search_query = "咖啡廳"
        else:
            search_query = "景點"
            
    # 設定 Nominatim 的參數 (預設搜尋台灣本島的目標項目，限制 3 筆)
    params = {
        'q': search_query,
        'format': 'json',
        'limit': 3
    }
    
    print(f"[後端邏輯] 當前情緒: {mood}, 社交能量: {social_energy} -> 決定搜尋: {search_query}")
    
    response = requests.get(url_geo, headers=headers, params=params)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"[錯誤] API請求失敗，狀態碼: {response.status_code}")
        return []