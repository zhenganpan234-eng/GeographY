"""
Route Statistics 路線人格分析模組
對應 Proposal 第 4 項：Route Statistics（路線人格分析）
"""

def compute_route_stats(waypoint_details, social_energy, mood, distance_km, duration_min):
    """
    根據路線特性計算情緒統計數據。
    回傳一個 dict，供 template 顯示。
    """
    energy = int(social_energy)

    # ── 1. Crowd Exposure（人群暴露度，0~100）──────────────────────────
    # 依照 mood 和 social_energy 估算
    mood_crowd = {
        "放鬆": 20,
        "文青": 25,
        "探索": 40,
        "社交": 75,
        "療癒": 10,
    }
    base_crowd = mood_crowd.get(mood, 30)
    # 社交能量高 → 願意人多的地方 → 暴露度上升；上下界都夾住
    crowd_exposure = max(0, min(100, int(base_crowd + (energy - 50) * 0.4)))

    # ── 2. Quietness Score（安靜分數，0~100）──────────────────────────
    quietness = max(0, min(100, 100 - crowd_exposure))

    # ── 3. Bookstores Passed（途經書店數量）──────────────────────────
    bookstore_count = sum(
        1 for wp in waypoint_details
        if any(kw in wp.get('name', '') for kw in ['書店', '書局', '誠品', '書', 'Books'])
        or wp.get('type') == '書店'
    )

    # ── 4. Emotional Recovery Score（情緒恢復分數，0~100）────────────
    # 安靜 + 步行時間 + 療癒/放鬆 mood → 恢復力高
    mood_recovery = {
        "放鬆": 80,
        "文青": 65,
        "探索": 50,
        "社交": 30,
        "療癒": 95,
    }
    base_recovery = mood_recovery.get(mood, 60)
    # 步行超過 20 分鐘有加分
    walk_bonus = min(15, max(0, (duration_min - 20) // 5 * 3))
    recovery_score = max(0, min(100, base_recovery + walk_bonus))

    # ── 5. Awkward Eye Contact Chance（尷尬對視機率，趣味功能）────────
    # 人群暴露度高 → 機率高；限制在 1~99
    awkward_chance = max(1, min(99, int(crowd_exposure * 0.6)))

    # ── 6. 路線人格標籤 ───────────────────────────────────────────────
    if energy < 40:
        personality = "隱世獨行者 🌙"
        personality_desc = "你是一個珍惜獨處的靈魂，本次路線已為你清空了99%的人潮。"
    elif energy < 70 and mood in ("放鬆", "文青", "療癒"):
        personality = "文藝漫遊者 📚"
        personality_desc = "半社交半獨處，你在城市角落中尋找屬於自己的節奏。"
    elif mood == "探索":
        personality = "城市探險家 🗺️"
        personality_desc = "你對未知充滿好奇，每條巷子都可能是驚喜。"
    elif mood == "社交" or energy >= 70:
        personality = "命定相遇者 💫"
        personality_desc = "你敞開心扉擁抱人群，相信每個擦肩都是緣分。"
    else:
        personality = "療癒流浪者 🌿"
        personality_desc = "你需要的不是目的地，而是沿途的呼吸空間。"

    return {
        "crowd_exposure": crowd_exposure,
        "quietness": quietness,
        "bookstore_count": bookstore_count,
        "recovery_score": recovery_score,
        "awkward_chance": awkward_chance,
        "personality": personality,
        "personality_desc": personality_desc,
    }