from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware

import os

from database import get_db
from routers import assistant, auth, ingestion, oauth, proposals, reminders, search, tasks
from services.telemetry import collector

@asynccontextmanager
async def lifespan(_: FastAPI):
    collector.start()  # no-op unless TELEMETRY_INTERVAL_SECONDS > 0
    yield
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
