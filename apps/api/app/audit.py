from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import AuditEvent, Workspace


def utcnow() -> datetime:
    return datetime.now(UTC)


def record_audit(
    db: Session,
    workspace: Workspace,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str | None = None,
    payload: dict | None = None,
    case_version: int | None = None,
    tool_name: str | None = None,
    model_usage: dict | None = None,
    latency_ms: int | None = None,
    evidence_ids: list | None = None,
) -> AuditEvent:
    event = AuditEvent(
        id=str(uuid4()),
        workspace_id=workspace.id,
        event_id=str(uuid4()),
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        payload=payload or {},
        case_version=case_version,
        tool_name=tool_name,
        model_usage=model_usage,
        latency_ms=latency_ms,
        evidence_ids=evidence_ids,
        created_at=utcnow(),
    )
    db.add(event)
    return event
