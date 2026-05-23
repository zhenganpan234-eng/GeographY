# 網頁的啟動核心
from flask import Flask, render_template, request
# 從 src 資料夾裡的 api_client.py 引入你寫好的 get_mood_places 函式
from src.api_client import get_mood_places

app = Flask(__name__)

# 1. 首頁路由：當使用者打開網頁時，顯示 index.html 畫面
@app.route('/')
def home():
    return render_template('index.html')

# 2. 搜尋路由：接收網頁表單傳過來的數據
@app.route('/search', methods=['POST'])
def search():
    # 抓取網頁上拉桿和選單的值
    social_energy = request.form.get('social_energy')
    mood = request.form.get('mood')
    
    # 呼叫 Peter 寫的後端演算法，去跟 Nominatim API 要資料
    candidates = get_mood_places(mood, social_energy)
    
    # 先將抓到的資料結果直接印在網頁上，方便我們檢查資料結構
    return {
        "status": "成功接收數據！",
        "user_mood": mood,
        "user_social_energy": social_energy,
        "nominatim_results": candidates
    }

if __name__ == '__main__':
    # 啟動本地測試伺服器，debug=True 代表改程式網頁會自動重新整理
    app.run(debug=True, port=5000)