from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os

from routers import assistant, auth, ingestion, proposals, reminders, search, tasks
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
app.include_router(assistant.router)
app.include_router(proposals.router)
app.include_router(tasks.router)
app.include_router(reminders.router)
app.include_router(ingestion.router)
app.include_router(search.router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
