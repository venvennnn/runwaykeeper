from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit import record_audit, utcnow
from app.db import get_db
from app.deps import get_workspace
from app.models import CashSnapshot, ProvenanceType, Workspace

router = APIRouter(prefix="/api/cash", tags=["cash"])


class CashIn(BaseModel):
    balance: str
    effective_at: datetime
    source: str = "owner_entry"


@router.get("/snapshot")
def get_snapshot(db: Session = Depends(get_db), workspace: Workspace = Depends(get_workspace)):
    from app.services.forecast_service import latest_snapshot

    snap = latest_snapshot(db, workspace)
    if snap is None:
        return None
    return {
        "id": snap.id,
        "balance_minor": snap.balance_minor,
        "effective_at": snap.effective_at.isoformat(),
        "source": snap.source,
        "provenance": snap.provenance,
    }


@router.post("/snapshot")
def set_snapshot(
    body: CashIn,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_workspace),
):
    from runwaykeeper_forecasting.money import MoneyError, parse_minor_amount

    try:
        minor = parse_minor_amount(body.balance, field="balance")
    except MoneyError as exc:
        raise HTTPException(400, str(exc)) from exc
    effective = body.effective_at
    if effective.tzinfo is None:
        from datetime import UTC

        effective = effective.replace(tzinfo=UTC)
    snap = CashSnapshot(
        id=str(uuid4()),
        workspace_id=workspace.id,
        balance_minor=minor,
        effective_at=effective,
        source=body.source,
        source_id=f"cash:{effective.isoformat()}",
        source_ts=utcnow(),
        ingested_at=utcnow(),
        provenance=ProvenanceType.USER_ENTERED.value,
    )
    db.add(snap)
    record_audit(db, workspace, event_type="cash_snapshot", entity_type="cash_snapshot", entity_id=snap.id)
    db.commit()
    return {"id": snap.id, "balance_minor": snap.balance_minor, "effective_at": snap.effective_at.isoformat()}
