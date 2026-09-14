from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.config import settings
from app.db import get_db
from app.deps import get_workspace
from app.models import ImportBatch, Job, Workspace, WorkspaceMode

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsIn(BaseModel):
    buffer: str | None = None
    reminder_cooldown_hours: int | None = None
    max_reminders_per_case: int | None = None
    auto_reminders_enabled: bool | None = None
    mode: str | None = None


@router.get("")
def get_settings(db: Session = Depends(get_db), workspace: Workspace = Depends(get_workspace)):
    from app.services.forecast_service import latest_snapshot

    snap = latest_snapshot(db, workspace)
    batches = (
        db.query(ImportBatch)
        .filter(ImportBatch.workspace_id == workspace.id)
        .order_by(ImportBatch.created_at.desc())
        .limit(20)
        .all()
    )
    jobs = (
        db.query(Job)
        .filter(Job.workspace_id == workspace.id)
        .order_by(Job.created_at.desc())
        .limit(20)
        .all()
    )
    connected = bool(settings.resend_api_key) and workspace.mode == WorkspaceMode.CONNECTED.value
    return {
        "workspace_id": workspace.id,
        "name": workspace.name,
        "base_currency": workspace.base_currency,
        "mode": workspace.mode,
        "buffer_minor": workspace.buffer_minor,
        "reminder_cooldown_hours": workspace.reminder_cooldown_hours,
        "max_reminders_per_case": workspace.max_reminders_per_case,
        "auto_reminders_enabled": workspace.auto_reminders_enabled,
        "cash_effective_at": snap.effective_at.isoformat() if snap else None,
        "cash_balance_minor": snap.balance_minor if snap else None,
        "email_connection": {
            "provider": "resend",
            "connected": connected,
            "simulation": workspace.mode == WorkspaceMode.SIMULATION.value,
            "label": "simulation — captured outgoing messages" if workspace.mode == WorkspaceMode.SIMULATION.value else (
                "Resend connected" if connected else "connected mode without API key (still capturing)"
            ),
        },
        "imports": [
            {
                "id": b.id,
                "kind": b.kind,
                "filename": b.filename,
                "status": b.status,
                "errors": b.errors,
                "committed_rows": b.committed_rows,
                "skipped_duplicates": b.skipped_duplicates,
                "created_at": b.created_at.isoformat(),
            }
            for b in batches
        ],
        "jobs": [
            {
                "id": j.id,
                "job_type": j.job_type,
                "status": j.status,
                "attempts": j.attempts,
                "last_error": j.last_error,
                "unique_key": j.unique_key,
            }
            for j in jobs
        ],
        "aws_builder_id_placeholder": settings.aws_builder_id or "YOUR_AWS_BUILDER_ID",
        "deployment_url_placeholder": settings.deployment_url or "https://YOUR_DEPLOYMENT_URL",
        "bedrock": {"model_id": settings.bedrock_model_id, "region": settings.aws_region},
    }


@router.post("")
def update_settings(
    body: SettingsIn,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_workspace),
):
    if body.buffer is not None:
        from runwaykeeper_forecasting.money import parse_minor_amount

        workspace.buffer_minor = parse_minor_amount(body.buffer, field="buffer")
    if body.reminder_cooldown_hours is not None:
        workspace.reminder_cooldown_hours = body.reminder_cooldown_hours
    if body.max_reminders_per_case is not None:
        workspace.max_reminders_per_case = body.max_reminders_per_case
    if body.auto_reminders_enabled is not None:
        workspace.auto_reminders_enabled = body.auto_reminders_enabled
    if body.mode is not None:
        if body.mode not in {WorkspaceMode.SIMULATION.value, WorkspaceMode.CONNECTED.value}:
            from fastapi import HTTPException

            raise HTTPException(400, "mode must be simulation or connected")
        workspace.mode = body.mode
    record_audit(db, workspace, event_type="settings_updated", entity_type="workspace", entity_id=workspace.id)
    db.commit()
    return {"ok": True, "mode": workspace.mode, "buffer_minor": workspace.buffer_minor}
