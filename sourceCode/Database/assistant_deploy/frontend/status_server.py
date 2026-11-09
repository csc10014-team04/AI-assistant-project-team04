"""
Status page served by the `frontend` container (docker-compose, port 80).

`main.py` in this folder is a Kivy desktop window and cannot run inside a container (no display); the container used to
start `uvicorn main:app`, which does not exist, so it crashed at start. This small web page replaces it: open
http://<host>/ and it shows whether the backend and its database answer.
"""
import html
import os

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8080").rstrip("/")  # service name inside the compose network

app = FastAPI(title="University Life Assistant - status")


def _probe(path: str) -> tuple[bool, str]:
    try:
        r = httpx.get(f"{BACKEND_URL}{path}", timeout=3.0)
        return r.status_code == 200, f"HTTP {r.status_code}"
    except httpx.HTTPError as exc:
        return False, type(exc).__name__


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def status_page() -> str:
    rows = []
    for label, path in (("Backend", "/health"), ("Database (through the backend)", "/health/db")):
        ok, detail = _probe(path)
        rows.append(f"<tr><td>{html.escape(label)}</td><td>{'OK' if ok else 'DOWN'}</td><td>{html.escape(detail)}</td></tr>")
    return (
        "<!doctype html><html lang='vi'><head><meta charset='utf-8'><title>University Life Assistant</title></head><body>"
        "<h1>University Life Assistant: trạng thái hệ thống</h1>"
        f"<p>Backend: {html.escape(BACKEND_URL)}</p>"
        "<table border='1' cellpadding='6'><tr><th>Thành phần</th><th>Trạng thái</th><th>Chi tiết</th></tr>"
        + "".join(rows) + "</table></body></html>"
    )
