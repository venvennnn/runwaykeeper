from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.audit import record_audit, utcnow
from app.config import settings
from app.models import Workspace
from runwaykeeper_agent.coordinator import run_coordinator


def run_workspace_agent(
    db: Session,
    workspace: Workspace,
    *,
    trigger: str,
    case_id: str | None = None,
    inbound_excerpt: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = run_coordinator(
        db=db,
        workspace=workspace,
        trigger=trigger,
        case_id=case_id,
        inbound_excerpt=inbound_excerpt,
        model_id=settings.bedrock_model_id,
        region=settings.aws_region,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    record_audit(
        db,
        workspace,
        event_type="agent_run",
        entity_type="workspace",
        entity_id=workspace.id,
        payload={
            "trigger": trigger,
            "case_id": case_id,
            "action": result.get("action"),
            "tool_calls": result.get("tool_calls", []),
        },
        tool_name="coordinator",
        model_usage=result.get("model_usage"),
        latency_ms=latency_ms,
        evidence_ids=result.get("evidence_ids"),
    )
    db.flush()
    return result
