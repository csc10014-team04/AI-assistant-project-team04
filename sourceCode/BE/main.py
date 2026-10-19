from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import auth, ingestion, search

app = FastAPI(
    title="University Life Assistant API",
    version="1.0.0",
    description="Backend API for schedule ingestion, conflict validation, and local search",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(ingestion.router)
app.include_router(search.router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
