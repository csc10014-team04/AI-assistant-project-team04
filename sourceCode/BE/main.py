# [pic: lam] fastapi server entrypoint, cors, router registration & health checks (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
import traceback
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import UTC_TZ, get_db
from routers import assistant, auth, ingestion, oauth, proposals, reminders, search, tasks
from services.ai_logging import LOG_PATH as AI_ERROR_LOG_PATH
from services.telemetry import collector

_DEBUG_RING_BUFFER: deque[dict] = deque(maxlen=100)  # in-memory buffer for recent http errors
_DEBUG_LOCK = threading.Lock()
BE_HTTP_ERROR_LOG_PATH = Path(
    os.getenv(
        "BE_HTTP_ERROR_LOG_PATH",
        str(Path(__file__).resolve().parent / "logs" / "be_http_errors.jsonl"),
    )
)


def _classify_error_source(status_code: int, payload: object) -> str:
    """classify http error origin so fe/be/testers know which layer raised it."""
    if status_code == 404 and isinstance(payload, dict) and payload.get("detail") == "Not Found":
        return "FASTAPI_ROUTER_URL_NOT_FOUND: FE goi sai duong dan URL hoac phuong thuc HTTP (chua vao code nghiep vu BE)"
    if status_code == 422:
        return "PYDANTIC_VALIDATION_ERROR: Du lieu FE gui len thieu truong hoac sai kieu du lieu so voi schema BE"
    if status_code in (401, 403):
        return "BE_AUTH_GUARD: Loi xac thuc hoac phien dang nhap (sai mat khau, thieu token hoac token het han)"
    if status_code >= 500:
        return "BE_UNHANDLED_EXCEPTION: Loi ngoai le chua bat ben trong code BE hoac ket noi DB"
    return "BE_BUSINESS_RULE_REJECTION: Code nghiep vu BE chu dong tu choi yeu cau theo quy tac he thong"


def _record_be_error(entry: dict) -> None:
    """store an error record in memory and append it as jsonl; disk errors must not break responses."""
    with _DEBUG_LOCK:
        _DEBUG_RING_BUFFER.append(entry)
        try:
            BE_HTTP_ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with BE_HTTP_ERROR_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass


def _read_recent_ai_errors(limit: int) -> list[dict]:
    """read up to `limit` newest ai failure records from ai_errors.jsonl."""
    if not AI_ERROR_LOG_PATH.exists():
        return []
    try:
        lines = AI_ERROR_LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    parsed: list[dict] = []
    for raw_line in lines[-limit:]:
        if not raw_line.strip():
            continue
        try:
            parsed.append(json.loads(raw_line))
        except json.JSONDecodeError:
            parsed.append({"raw_line": raw_line})
    parsed.reverse()
    return parsed


def _extract_be_origin(exc: Exception) -> str:
    """find the deepest traceback frame inside sourceCode/BE for quick fault localization."""
    frames = traceback.extract_tb(exc.__traceback__)
    be_root = str(Path(__file__).resolve().parent)
    for frame in reversed(frames):
        if frame.filename.startswith(be_root):
            return f"{Path(frame.filename).name}:{frame.lineno} in {frame.name}"
    if frames:
        last = frames[-1]
        return f"{Path(last.filename).name}:{last.lineno} in {last.name}"
    return "unknown"

@asynccontextmanager
async def lifespan(_: FastAPI):
    collector.start()  # no-op unless TELEMETRY_INTERVAL_SECONDS > 0
    try:
        yield
    finally:
        collector.stop()


app = FastAPI(
    lifespan=lifespan,
    title="University Life Assistant API",
    version="1.0.0",
    description="Backend API for schedule ingestion, conflict validation, and local search",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.getenv("CORS_ORIGINS", "").split(",") if o],  # native app needs no CORS; never "*" with credentials
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def diagnostic_error_middleware(request: Request, call_next):
    """capture 4xx/5xx http errors and unhandled exceptions for self-service fe/be/tester debugging."""
    request_id = uuid.uuid4().hex[:8]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        origin = _extract_be_origin(exc)
        tb_text = traceback.format_exc()
        error_source = _classify_error_source(500, None)
        entry = {
            "ts": datetime.now(UTC_TZ).isoformat(),
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query,
            "status_code": 500,
            "error_source": error_source,
            "origin": origin,
            "detail": f"{type(exc).__name__}: {exc}",
            "traceback": tb_text,
            "duration_ms": duration_ms,
        }
        _record_be_error(entry)
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Internal Server Error ({type(exc).__name__}: {exc})",
                "request_id": request_id,
                "error_source": error_source,
                "debug_origin": origin,
                "traceback": tb_text,
            },
            headers={
                "X-Request-ID": request_id,
                "X-Error-Source": error_source,
            },
        )

    response.headers["X-Request-ID"] = request_id
    if response.status_code >= 400 and request.url.path != "/api/v1/debug/logs":
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        body_chunks = [chunk async for chunk in response.body_iterator]
        body_bytes = b"".join(body_chunks)
        parsed_body: object = None
        if body_bytes:
            try:
                parsed_body = json.loads(body_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed_body = body_bytes.decode("utf-8", errors="replace")
        error_source = _classify_error_source(response.status_code, parsed_body)
        detail = parsed_body.get("detail", parsed_body) if isinstance(parsed_body, dict) else parsed_body
        _record_be_error(
            {
                "ts": datetime.now(UTC_TZ).isoformat(),
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query,
                "status_code": response.status_code,
                "error_source": error_source,
                "origin": "http_response",
                "detail": detail,
                "duration_ms": duration_ms,
            }
        )
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        headers["X-Request-ID"] = request_id
        headers["X-Error-Source"] = error_source
        return Response(
            content=body_bytes,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
    return response


app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(assistant.router)
app.include_router(proposals.router)
app.include_router(tasks.router)
app.include_router(reminders.router)
app.include_router(ingestion.router)
app.include_router(search.router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db", tags=["system"])
def health_db(db: Session = Depends(get_db)) -> dict[str, str]:
    """unlike /health this really talks to MySQL: 200 when `SELECT 1` works, 503 when the database is down."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(503, f"database unreachable: {type(exc).__name__}") from exc
    return {"status": "ok", "database": "ok"}


@app.get("/api/v1/debug/logs", tags=["system"])
def get_diagnostic_logs(
    limit: int = Query(default=30, ge=1, le=100, description="so luong ban ghi loi moi nhat can xem"),
) -> dict:
    """self-service diagnostics endpoint for testers, fe, and be without asking the host operator."""
    with _DEBUG_LOCK:
        recent_http = list(_DEBUG_RING_BUFFER)[-limit:]
    recent_http.reverse()
    recent_ai = _read_recent_ai_errors(limit)
    return {
        "summary": (
            "Cach doc nhanh: "
            "FASTAPI_ROUTER_URL_NOT_FOUND = FE goi sai URL; "
            "PYDANTIC_VALIDATION_ERROR = FE gui thieu hoac sai kieu du lieu; "
            "BE_BUSINESS_RULE_REJECTION = BE tu choi theo logic nghiep vu; "
            "BE_UNHANDLED_EXCEPTION = loi ben trong code BE (xem truong origin va traceback)."
        ),
        "http_error_count": len(recent_http),
        "ai_error_count": len(recent_ai),
        "recent_http_errors": recent_http,
        "recent_ai_errors": recent_ai,
    }
