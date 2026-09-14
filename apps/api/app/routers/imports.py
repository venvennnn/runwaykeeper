from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.cases import enqueue_job
from app.db import get_db
from app.deps import get_workspace
from app.imports import maybe_auto_allocate_payment, preview_and_commit
from app.models import Payment, Workspace

router = APIRouter(prefix="/api/imports", tags=["imports"])


@router.post("/{kind}")
async def import_csv(
    kind: str,
    commit: bool = Form(False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_workspace),
):
    if kind not in {"customers", "invoices", "payments", "expenses"}:
        raise HTTPException(400, "unsupported import kind")
    content = (await file.read()).decode("utf-8")
    provenance = "simulated" if workspace.mode == "simulation" else "imported"
    try:
        batch = preview_and_commit(
            db,
            workspace,
            kind=kind,
            filename=file.filename or "upload.csv",
            content=content,
            provenance=provenance,
            commit=commit,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if commit and not batch.errors:
        if kind == "payments":
            for payment in db.query(Payment).filter(Payment.workspace_id == workspace.id):
                maybe_auto_allocate_payment(db, workspace, payment)
        enqueue_job(
            db,
            workspace,
            "recompute_forecast",
            {"trigger": "import"},
            unique_key=f"forecast-after-import:{batch.id}",
        )
        enqueue_job(
            db,
            workspace,
            "run_agent",
            {"trigger": "import"},
            unique_key=f"agent-after-import:{batch.id}",
        )
        record_audit(db, workspace, event_type="import_committed", entity_type="import", entity_id=batch.id, payload={"kind": kind})
    db.commit()
    return {
        "id": batch.id,
        "status": batch.status,
        "errors": batch.errors,
        "committed_rows": batch.committed_rows,
        "skipped_duplicates": batch.skipped_duplicates,
    }
