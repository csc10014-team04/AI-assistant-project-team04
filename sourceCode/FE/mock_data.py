mock_events = [
    
    # ---- 4 sự kiện gốc ----
    {
        "id": 105, "title": "Cấu trúc dữ liệu", "room": "E201", "kind": "CLASS",
        "start_time": "2026-10-26T13:30:00+07:00", "end_time": "2026-10-26T15:30:00+07:00",
        "is_hard": True, "is_important": False
    },
    {
        "id": 106, "title": "Nộp BTL Kivy", "room": "", "kind": "DEADLINE",
        "start_time": "2026-10-29T23:59:00+07:00", "end_time": "2026-10-29T23:59:00+07:00",
        "is_hard": True, "is_important": True
    },
    {
        "id": 107, "title": "Họp Team Frontend", "room": "Meet", "kind": "CLASS",
        "start_time": "2026-10-29T14:00:00+07:00", "end_time": "2026-10-29T15:00:00+07:00",
        "is_hard": False, "is_important": True
    },
    {
        "id": 108, "title": "Thi AI", "room": "A305", "kind": "EXAM",
        "start_time": "2026-10-31T09:00:00+07:00", "end_time": "2026-10-31T11:00:00+07:00",
        "is_hard": True, "is_important": True
    },
    # ---- 8 sự kiện thêm mới để test ----
    {
        "id": 109, "title": "Học Kỹ năng mềm", "room": "B104", "kind": "CLASS",
        "start_time": "2026-11-02T07:30:00+07:00", "end_time": "2026-11-02T09:30:00+07:00",
        "is_hard": False, "is_important": False
    },
    {
        "id": 110, "title": "Đăng ký tín chỉ", "room": "Online", "kind": "DEADLINE",
        "start_time": "2026-11-05T12:00:00+07:00", "end_time": "2026-11-05T12:00:00+07:00",
        "is_hard": False, "is_important": True
    },
    {
        "id": 111, "title": "Hội thảo AI & Robotics", "room": "Hội trường A", "kind": "EVENT",
        "start_time": "2026-11-06T08:00:00+07:00", "end_time": "2026-11-06T11:30:00+07:00",
        "is_hard": False, "is_important": True
    },
    {
        "id": 112, "title": "Thi giữa kỳ Mạng máy tính", "room": "C202", "kind": "EXAM",
        "start_time": "2026-11-10T13:00:00+07:00", "end_time": "2026-11-10T14:30:00+07:00",
        "is_hard": True, "is_important": True
    },
    {
        "id": 113, "title": "Thể dục (Bơi lội)", "room": "Hồ bơi", "kind": "CLASS",
        "start_time": "2026-11-11T15:00:00+07:00", "end_time": "2026-11-11T17:00:00+07:00",
        "is_hard": False, "is_important": False
    },
    {
        "id": 114, "title": "Nộp báo cáo thực tập", "room": "", "kind": "DEADLINE",
        "start_time": "2026-11-15T17:00:00+07:00", "end_time": "2026-11-15T17:00:00+07:00",
        "is_hard": True, "is_important": True
    },
    {
        "id": 115, "title": "Giao lưu sinh viên quốc tế", "room": "Sân vận động", "kind": "EVENT",
        "start_time": "2026-11-20T18:00:00+07:00", "end_time": "2026-11-20T21:00:00+07:00",
        "is_hard": False, "is_important": False
    },
    {
        "id": 116, "title": "Bảo vệ Đồ án tốt nghiệp", "room": "F101", "kind": "EXAM",
        "start_time": "2026-12-05T07:30:00+07:00", "end_time": "2026-12-05T11:30:00+07:00",
        "is_hard": True, "is_important": True
    },
    # --- Cùng ngày 26/10/2026 (Thứ 2) ---
    {
        "id": 201,
        "title": "Giải thuật nâng cao",
        "room": "E202",
        "kind": "CLASS",
        "start_time": "2026-10-26T08:00:00+07:00",
        "end_time": "2026-10-26T10:00:00+07:00",
        "is_hard": True,
        "is_important": False
    },
    {
        "id": 202,
        "title": "Nộp bài tập Tuần 5",
        "room": "",
        "kind": "DEADLINE",
        "start_time": "2026-10-26T21:00:00+07:00",
        "end_time": "2026-10-26T21:00:00+07:00",
        "is_hard": False,
        "is_important": True
    },

    # --- Cùng ngày 27/10/2026 (Thứ 3) ---
    {
        "id": 203,
        "title": "Thực hành Mạng máy tính",
        "room": "Lab 3",
        "kind": "CLASS",
        "start_time": "2026-10-29T09:30:00+07:00",
        "end_time": "2026-10-29T11:30:00+07:00",
        "is_hard": True,
        "is_important": False
    },
    {
        "id": 204,
        "title": "Hội thảo Định hướng Nghề nghiệp",
        "room": "Hội trường B",
        "kind": "EVENT",
        "start_time": "2026-10-29T05:00:00+07:00",
        "end_time": "2026-10-29T06:30:00+07:00",
        "is_hard": False,
        "is_important": False
    },

    # --- Cùng ngày 29/10/2026 (Thứ 5) ---
    {
        "id": 205,
        "title": "Thi giữa kỳ Tiếng Anh",
        "room": "B102",
        "kind": "EXAM",
        "start_time": "2026-10-29T08:00:00+07:00",
        "end_time": "2026-10-29T09:30:00+07:00",
        "is_hard": True,
        "is_important": True
    },
    {
        "id": 206,
        "title": "Review Code Backend",
        "room": "Discord",
        "kind": "TASK",
        "start_time": "2026-10-29T16:00:00+07:00",
        "end_time": "2026-10-29T17:30:00+07:00",
        "is_hard": False,
        "is_important": False
    },

    # --- Cùng ngày 31/10/2026 (Thứ 7) ---
    {
        "id": 207,
        "title": "Nộp Slide Thuyết trình AI",
        "room": "",
        "kind": "DEADLINE",
        "start_time": "2026-10-31T07:00:00+07:00",
        "end_time": "2026-10-31T07:00:00+07:00",
        "is_hard": True,
        "is_important": True
    },
    {
        "id": 208,
        "title": "Sinh hoạt CLB IT",
        "room": "Sân C2",
        "kind": "EVENT",
        "start_time": "2026-10-31T15:00:00+07:00",
        "end_time": "2026-10-31T17:00:00+07:00",
        "is_hard": False,
        "is_important": False
    }
]