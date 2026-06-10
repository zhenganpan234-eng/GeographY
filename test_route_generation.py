from app import _generate_route_context


TEST_CASES = [
    ("新竹火車站", 3.0, 20, "放鬆", 80, "平衡模式", "不限"),
    ("新竹市文化局", 3.0, 20, "放鬆", 80, "平衡模式", "不限"),
    ("清華大學", 3.0, 15, "療癒", 30, "平衡模式", "不限"),
    ("台北大巨蛋", 3.0, 20, "探索", 80, "平衡模式", "不限"),
]


for start, hours, max_walk, mood, energy, mode, env in TEST_CASES:
    relaxation_minutes = round(hours * 60)

    context, error = _generate_route_context(
        start,
        hours,
        relaxation_minutes,
        str(energy),
        mood,
        mode,
        env,
        max_walk,
    )

    print("\n====================")
    print("測資：", start)
    print("error:", error)

    if context:
        print("總時間:", context["duration"])
        print("步行:", context["walking_minutes"])
        print("停留:", context["stay_minutes"])
        print("緩衝:", context["buffer_minutes"])
        print("景點數:", len(context["waypoints"]))

        for segment in context["route_segments"]:
            print(segment["from"], "->", segment["to"], segment["walking_minutes"], "min")

        for waypoint in context["waypoints"]:
            print(waypoint["name"], waypoint["category"], waypoint["stay_minutes"])
