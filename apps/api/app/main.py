from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db, SessionLocal
from app.routers import approvals, cases, cash, events, forecasts, imports, overview, settings as settings_router, simulation
from app.seed import seed_workspace

app = FastAPI(title="RunwayKeeper API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(overview.router)
app.include_router(imports.router)
app.include_router(cash.router)
app.include_router(forecasts.router)
app.include_router(cases.router)
app.include_router(approvals.router)
app.include_router(settings_router.router)
app.include_router(events.router)
app.include_router(simulation.router)


@app.on_event("startup")
def startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        seed_workspace(db, reset=False)
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "runwaykeeper-api"}
