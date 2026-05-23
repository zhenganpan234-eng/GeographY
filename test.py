# 全新修正版的 test.py
import requests

# 1. 測試 Nominatim (加入更真實的瀏覽器偽裝)
url_geo = "https://nominatim.openstreetmap.org/search"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

params_geo = {
    'q': '台灣大學',
    'format': 'json',
    'limit': 1
}

res_geo = requests.get(url_geo, headers=headers, params=params_geo)

print("--- Nominatim 資料 ---")
if res_geo.status_code == 200:
    print(res_geo.json())
else:
    print(f"被阻擋了，錯誤代碼: {res_geo.status_code}，內容: {res_geo.text[:100]}")

# 2. 測試 OSRM (從台北車站走到台北101)
url_route = "http://router.project-osrm.org/route/v1/foot/121.517,25.047;121.564,25.033"
res_route = requests.get(url_route, params={'overview': 'full', 'geometries': 'geojson'})

print("\n--- OSRM 資料 ---")
print(res_route.json())