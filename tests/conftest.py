import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path('/tmp/runwaykeeper-pytest.db')}")
os.environ.setdefault("DEMO_API_KEY", "rk_demo_harbor_studio")
os.environ.setdefault("FORECAST_SCENARIOS", "40")

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine, init_db
from app.main import app
from app.models import Base, Invoice, Payment, Workspace
from app.seed import seed_workspace, uid


@pytest.fixture(autouse=True)
def _reset_seed_per_test(db):
    seed_workspace(db, reset=True)
    yield


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    try:
        seed_workspace(db, reset=True)
    finally:
        db.close()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def auth():
    return {"X-API-Key": "rk_demo_harbor_studio"}
