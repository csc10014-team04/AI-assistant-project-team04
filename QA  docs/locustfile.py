import random
from datetime import datetime, timedelta, timezone
from locust import HttpUser, between, task

VN = timezone(timedelta(hours=7))

PROMPTS = [
    "schedule 2 hours study tomorrow",
    "plan 90 minutes project work tomorrow afternoon",
    "schedule 1 hour reading this weekend",
    "xếp 2 tiếng học bài ngày mai",
]


class SingleStudentUser(HttpUser):
    wait_time = between(1, 2)  # nghỉ 1-2s giữa mỗi lượt thao tác

    def on_start(self):
        """Chạy 1 lần khi user bắt đầu: đăng ký tài khoản tạm và lấy JWT token."""
        username = f"qa_sim_{random.randint(100000, 999999)}"
        res = self.client.post(
            "/api/v1/auth/register",
            json={
                "username": username,
                "password": "Passw0rd!",
                "display_name": f"QA_{username}",
            },
            name="/api/v1/auth/register",
        )
        res.raise_for_status()
        token = res.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}

    @task(3)
    def schedule_with_ai(self):
        """Gửi prompt xếp lịch; nếu có proposal thì confirm hoặc reject."""
        with self.client.post(
            "/api/v1/assistant/understand",
            headers=self.headers,
            json={"prompt": random.choice(PROMPTS)},
            name="/api/v1/assistant/understand",
            catch_response=True,
        ) as res:
            if res.status_code != 200:
                res.failure(f"HTTP {res.status_code}")
                return
            proposal = res.json().get("proposal")

        if proposal and proposal.get("id"):
            action = random.choice(["confirm", "reject"])
            self.client.post(
                f"/api/v1/proposals/{proposal['id']}/{action}",
                headers=self.headers,
                name=f"/api/v1/proposals/{{id}}/{action}",
            )

    @task(2)
    def check_free_slots(self):
        """Tìm giờ trống ngày mai (không dùng LLM)."""
        start = (datetime.now(VN) + timedelta(days=1)).replace(
            hour=6, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(hours=16)
        self.client.post(
            "/api/v1/search/free-slots",
            headers=self.headers,
            json={
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "duration_minutes": 60,
                "respect_preferences": True,
            },
            name="/api/v1/search/free-slots",
        )