from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.audit import record_audit, utcnow
from app.ledger import invoice_outstanding, payment_status
from app.models import (
    CollectionCase,
    CollectionState,
    Invoice,
    Job,
    JobStatus,
    Workspace,
)


CLOSED_STATES = {CollectionState.CLOSED.value}
UNPAID_GUARD_STATES = {
    CollectionState.PROMISED.value,
    CollectionState.AWAITING_REPLY.value,
}


def ensure_case(db: Session, workspace: Workspace, invoice: Invoice) -> CollectionCase:
    existing = (
        db.query(CollectionCase)
        .filter(CollectionCase.workspace_id == workspace.id, CollectionCase.invoice_id == invoice.id)
        .one_or_none()
    )
    if existing:
        return existing
    now = utcnow()
    outstanding = invoice_outstanding(db, invoice)
    state = CollectionState.CLOSED.value if outstanding <= 0 else CollectionState.MONITORING.value
    if outstanding > 0 and invoice.due_date < now.date():
        state = CollectionState.FOLLOWUP_DUE.value
    case = CollectionCase(
        id=str(uuid4()),
        workspace_id=workspace.id,
        invoice_id=invoice.id,
        collection_state=state,
        next_action_at=now if state == CollectionState.FOLLOWUP_DUE.value else None,
        version=1,
        reminder_count=0,
        source_id=f"case:{invoice.source_id}",
        source_ts=now,
        ingested_at=now,
        provenance=invoice.provenance,
    )
    db.add(case)
    db.flush()
    return case


def assert_transition(case: CollectionCase, new_state: str, invoice_status: str) -> None:
    if new_state == CollectionState.CLOSED.value and invoice_status != "paid":
        raise ValueError("backend guard: cannot close an unpaid case from a promise or email assertion")
    if invoice_status != "paid" and case.collection_state == CollectionState.CLOSED.value:
        raise ValueError("closed cases that are no longer paid must move to needs_review")


def apply_state(
    db: Session,
    workspace: Workspace,
    case: CollectionCase,
    new_state: str,
    *,
    reason: str,
    extra: dict | None = None,
) -> CollectionCase:
    invoice = db.get(Invoice, case.invoice_id)
    status = payment_status(db, invoice)
    assert_transition(case, new_state, status)
    case.collection_state = new_state
    case.version += 1
    if extra:
        if "promise_date" in extra:
            case.promise_date = extra["promise_date"]
        if "dispute_reason" in extra:
            case.dispute_reason = extra["dispute_reason"]
        if "next_action_at" in extra:
            case.next_action_at = extra["next_action_at"]
        if extra.get("clear_promise"):
            case.promise_date = None
    record_audit(
        db,
        workspace,
        event_type="case_transition",
        entity_type="case",
        entity_id=case.id,
        payload={"new_state": new_state, "reason": reason, "payment_status": status},
        case_version=case.version,
    )
    return case


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def cooldown_reason(db: Session, workspace: Workspace, case: CollectionCase) -> str | None:
    from app.ledger import payment_status as pay_status

    invoice = db.get(Invoice, case.invoice_id)
    status = pay_status(db, invoice)
    if status == "paid":
        return "settled"
    if case.collection_state == CollectionState.DISPUTED.value:
        return "disputed"
    customer = invoice.customer
    if not customer.email_verified or not customer.contact_permission:
        return "unverified-recipient"
    now = utcnow()
    cooldown = _as_utc(case.cooldown_until)
    if cooldown and cooldown > now:
        return "cooldown-blocked"
    if case.reminder_count >= workspace.max_reminders_per_case:
        return "cooldown-blocked"
    return None


def enqueue_job(
    db: Session,
    workspace: Workspace,
    job_type: str,
    payload: dict,
    unique_key: str,
    run_after: datetime | None = None,
) -> Job:
    existing = (
        db.query(Job)
        .filter(Job.workspace_id == workspace.id, Job.unique_key == unique_key)
        .one_or_none()
    )
    if existing:
        return existing
    job = Job(
        id=str(uuid4()),
        workspace_id=workspace.id,
        job_type=job_type,
        payload=payload,
        status=JobStatus.PENDING.value,
        unique_key=unique_key,
        run_after=run_after or utcnow(),
        max_attempts=5,
        attempts=0,
    )
    db.add(job)
    db.flush()
    return job
