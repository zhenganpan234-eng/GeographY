# 🧩 SoulPath — 情緒導航與療癒探索系統

> "Navigation systems optimize efficiency, but humans optimize emotional comfort."

## 專案簡介

SoulPath 是一個以**情緒與心理感受為核心**的步行導航 Web App。  
使用者可依照社交能量、當下心境，生成適合自己的散步路線，而不只是最快的路。

---

## 功能特色

| 功能 | 說明 |
|------|------|
| 🎭 五種心境模式 | 放鬆 / 文青 / 探索 / 社交 / 療癒 |
| ⚡ 社交能量儀表 | 0~100 滑桿，低能量自動切換 I 人路線 |
| 🗺️ 情緒化地圖主題 | 每種心境對應不同地圖配色與圖示 |
| 📊 路線情緒分析 | 人群暴露度、安靜分數、情緒恢復力、路線人格標籤 |
| ⭐ 收藏路線 | 儲存喜歡的路線，支援重新規劃與刪除 |
| 🚶 步行可達性過濾 | 用 OSRM 自動排除行人不友善路段 |
| 🔄 路線順序最佳化 | 距離矩陣 + 最近鄰貪心 + 2-opt，不繞路 |

---

## 使用的 API

- **Nominatim API** — 地名解析、附近地標搜尋
- **OSRM API** — 真實步行路線規劃、距離矩陣
- **Folium / Leaflet** — 互動式地圖渲染

---

## 專案結構

```
SoulPath/
├── app.py                  # Flask 主程式（路由控制）
├── src/
│   ├── api_client.py       # Nominatim + OSRM API、路線最佳化演算法
│   ├── map_builder.py      # Folium 地圖繪製
│   ├── route_stats.py      # 路線情緒統計分析
│   └── saved_routes.py     # 收藏路線（JSON 讀寫）
├── templates/
│   ├── index.html          # 主頁面
│   └── saved.html          # 收藏路線頁面
├── saved_routes.json       # 本地資料檔（自動產生，不進 git）
├── requirements.txt
└── README.md
```

---

## 安裝與執行

```bash
pip install -r requirements.txt
python app.py
```

開啟瀏覽器前往 `http://localhost:5000`

---

## 資料儲存

收藏路線統一使用 `saved_routes.json` 儲存於本地，最多保留 20 條。  
此檔案由程式自動產生，**不納入 git 版本控制**。

---

## 開發團隊

- 林芳宇
- 潘政安