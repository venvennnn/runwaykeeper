from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cases import enqueue_job
from app.db import get_db
from app.deps import get_workspace
from app.models import ForecastRun, Workspace
from app.services.forecast_service import persist_forecast

router = APIRouter(prefix="/api/forecasts", tags=["forecasts"])


@router.get("/latest")
def latest_forecast(
    what_if: bool = False,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_workspace),
):
    run = (
        db.query(ForecastRun)
        .filter(ForecastRun.workspace_id == workspace.id, ForecastRun.is_what_if == what_if)
        .order_by(ForecastRun.created_at.desc())
        .first()
    )
    if run is None:
        return None
    return {"id": run.id, "created_at": run.created_at.isoformat(), "assumptions": run.assumptions, **run.result}


@router.post("/run")
def run_forecast_endpoint(
    what_if_promise_case_id: str | None = None,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_workspace),
):
    try:
        forced = None
        if what_if_promise_case_id:
            from app.models import CollectionCase

            case = db.get(CollectionCase, what_if_promise_case_id)
            if case is None or case.workspace_id != workspace.id:
                raise HTTPException(404, "case not found")
            if case.promise_date:
                forced = {case.invoice_id: case.promise_date}
        run = persist_forecast(
            db,
            workspace,
            is_what_if=bool(forced),
            promise_case_id=what_if_promise_case_id,
            forced_arrivals=forced,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    enqueue_job(db, workspace, "run_agent", {"trigger": "forecast"}, unique_key=f"agent-forecast:{run.id}")
    db.commit()
    return {"id": run.id, **run.result}
