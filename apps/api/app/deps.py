from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Workspace


def get_workspace(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Workspace:
    key = x_api_key or settings.demo_api_key
    workspace = db.query(Workspace).filter(Workspace.api_key == key).one_or_none()
    if workspace is None:
        raise HTTPException(status_code=401, detail="Unknown workspace API key")
    return workspace
