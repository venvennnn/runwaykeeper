from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_workspace
from app.ledger import invoice_outstanding, payment_status
from app.models import AuditEvent, CollectionCase, Invoice, Message, Workspace
from app.services.ranking import rank_followups, refresh_cases

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.get("")
def list_cases(db: Session = Depends(get_db), workspace: Workspace = Depends(get_workspace)):
    refresh_cases(db, workspace)
    db.commit()
    rows = []
    for case in db.query(CollectionCase).filter(CollectionCase.workspace_id == workspace.id):
        invoice = db.get(Invoice, case.invoice_id)
        rows.append(_case_payload(db, case, invoice))
    rows.sort(key=lambda r: (-r["cash_gap_sensitivity_minor"], r["external_reference"]))
    return {"cases": rows, "ranked": rank_followups(db, workspace)}


@router.get("/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db), workspace: Workspace = Depends(get_workspace)):
    case = (
        db.query(CollectionCase)
        .filter(CollectionCase.workspace_id == workspace.id, CollectionCase.id == case_id)
        .one_or_none()
    )
    if case is None:
        raise HTTPException(404, "case not found")
    invoice = db.get(Invoice, case.invoice_id)
    messages = (
        db.query(Message)
        .filter(Message.workspace_id == workspace.id, Message.case_id == case.id)
        .order_by(Message.source_ts)
        .all()
    )
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.workspace_id == workspace.id, AuditEvent.entity_id == case.id)
        .order_by(AuditEvent.created_at)
        .all()
    )
    payload = _case_payload(db, case, invoice)
    payload["messages"] = [
        {
            "id": m.id,
            "direction": m.direction,
            "subject": m.subject,
            "body_excerpt": m.body_excerpt,
            "delivery_status": m.delivery_status,
            "is_simulation": m.is_simulation,
            "delivery_label": (
                "simulated capture — not real delivery" if m.is_simulation else m.delivery_status
            ),
            "at": m.source_ts.isoformat(),
        }
        for m in messages
    ]
    payload["timeline"] = [
        {
            "id": e.id,
            "event_type": e.event_type,
            "payload": e.payload,
            "tool_name": e.tool_name,
            "at": e.created_at.isoformat(),
            "case_version": e.case_version,
        }
        for e in events
    ]
    return payload


def _case_payload(db: Session, case: CollectionCase, invoice: Invoice) -> dict:
    customer = invoice.customer
    return {
        "id": case.id,
        "invoice_id": invoice.id,
        "external_reference": invoice.external_reference,
        "customer_name": customer.display_name,
        "customer_email": customer.email,
        "email_verified": customer.email_verified,
        "contact_permission": customer.contact_permission,
        "collection_state": case.collection_state,
        "payment_status": payment_status(db, invoice),
        "outstanding_minor": invoice_outstanding(db, invoice),
        "gross_amount_minor": invoice.gross_amount_minor,
        "due_date": invoice.due_date.isoformat(),
        "issue_date": invoice.issue_date.isoformat(),
        "priority_reason": case.priority_reason,
        "cash_gap_sensitivity_minor": case.cash_gap_sensitivity_minor,
        "promise_date": case.promise_date.isoformat() if case.promise_date else None,
        "dispute_reason": case.dispute_reason,
        "version": case.version,
        "reminder_count": case.reminder_count,
        "next_action_at": case.next_action_at.isoformat() if case.next_action_at else None,
        "provenance": invoice.provenance,
        "source_id": invoice.source_id,
    }
