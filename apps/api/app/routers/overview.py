from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_workspace
from app.ledger import invoice_outstanding
from app.models import Invoice, Job, Workspace
from app.services.forecast_service import latest_snapshot
from app.services.ranking import rank_followups

router = APIRouter(prefix="/api/overview", tags=["overview"])


@router.get("")
def overview(db: Session = Depends(get_db), workspace: Workspace = Depends(get_workspace)):
    from app.models import ForecastRun

    snap = latest_snapshot(db, workspace)
    run = (
        db.query(ForecastRun)
        .filter(ForecastRun.workspace_id == workspace.id, ForecastRun.is_what_if.is_(False))
        .order_by(ForecastRun.created_at.desc())
        .first()
    )
    what_if = (
        db.query(ForecastRun)
        .filter(ForecastRun.workspace_id == workspace.id, ForecastRun.is_what_if.is_(True))
        .order_by(ForecastRun.created_at.desc())
        .first()
    )
    outstanding = sum(invoice_outstanding(db, inv) for inv in db.query(Invoice).filter(Invoice.workspace_id == workspace.id))
    next_job = (
        db.query(Job)
        .filter(Job.workspace_id == workspace.id, Job.status.in_(["pending", "leased"]))
        .order_by(Job.run_after)
        .first()
    )
    return {
        "workspace": workspace.name,
        "mode": workspace.mode,
        "base_currency": workspace.base_currency,
        "current_cash_minor": snap.balance_minor if snap else None,
        "cash_effective_at": snap.effective_at.isoformat() if snap else None,
        "buffer_minor": workspace.buffer_minor,
        "outstanding_minor": outstanding,
        "forecast": None if run is None else run.result,
        "what_if_forecast": None if what_if is None else what_if.result,
        "ranked": rank_followups(db, workspace)[:5],
        "next_background_check": None if next_job is None else {
            "job_type": next_job.job_type,
            "run_after": next_job.run_after.isoformat(),
            "status": next_job.status,
        },
    }
