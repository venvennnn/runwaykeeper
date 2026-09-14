from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.cases import enqueue_job
from app.config import settings
from app.db import get_db
from app.deps import get_workspace
from app.email_adapter import persist_inbound, verify_resend_signature
from app.models import CollectionCase, Customer, Invoice, Message, Workspace, WorkspaceMode
from app.services.orchestration import run_workspace_agent

router = APIRouter(tags=["events"])


class InboundIn(BaseModel):
    from_email: str
    subject: str
    body: str
    invoice_reference: str | None = None
    provider_message_id: str | None = None


def _resolve_case(db: Session, workspace: Workspace, from_email: str, invoice_reference: str | None) -> str | None:
    if invoice_reference:
        invoice = (
            db.query(Invoice)
            .filter(
                Invoice.workspace_id == workspace.id,
                Invoice.external_reference == invoice_reference,
            )
            .one_or_none()
        )
        if invoice and invoice.case:
            return invoice.case.id
    customer = (
        db.query(Customer)
        .filter(Customer.workspace_id == workspace.id, Customer.email == from_email)
        .one_or_none()
    )
    if customer is None:
        return None
    invoice = (
        db.query(Invoice)
        .filter(Invoice.workspace_id == workspace.id, Invoice.customer_id == customer.id)
        .order_by(Invoice.due_date)
        .first()
    )
    if invoice and invoice.case:
        return invoice.case.id
    return None


@router.post("/api/simulation/inbound")
def simulation_inbound(
    body: InboundIn,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_workspace),
):
    if workspace.mode != WorkspaceMode.SIMULATION.value:
        raise HTTPException(403, "inbound test-event route is restricted to simulation mode")
    case_id = _resolve_case(db, workspace, body.from_email, body.invoice_reference)
    message = persist_inbound(
        db,
        workspace,
        from_email=body.from_email,
        to_email="inbox@harbor.simulation",
        subject=body.subject,
        body=body.body,
        provider_message_id=body.provider_message_id,
        thread_id=None,
        case_id=case_id,
    )
    result = run_workspace_agent(
        db,
        workspace,
        trigger="inbound_email",
        case_id=case_id,
        inbound_excerpt=body.body[:400],
    )
    if "already paid" in body.body.lower() and case_id:
        from app.ledger import create_allocation, find_unambiguous_match, invoice_outstanding
        from app.models import Payment
        from app.audit import utcnow
        from app.models import ProvenanceType

        invoice = db.get(CollectionCase, case_id)
        inv = db.get(Invoice, invoice.invoice_id)
        payment, matched, reason = find_unambiguous_match(
            db,
            workspace,
            customer_id=inv.customer_id,
            currency=inv.currency,
            amount_minor=invoice_outstanding(db, inv) or inv.gross_amount_minor,
            reference=inv.external_reference,
        )
        if payment and matched:
            try:
                create_allocation(
                    db,
                    workspace,
                    payment=payment,
                    invoice=matched,
                    amount_minor=min(payment.amount_minor, invoice_outstanding(db, matched) or payment.amount_minor),
                    evidence={"rule": "unambiguous_already_paid", "reason": reason},
                    source_id=f"inbound-alloc:{payment.id}",
                    source_ts=utcnow(),
                    provenance=ProvenanceType.SIMULATED.value,
                )
                result["reconciled"] = True
                result["included_in_opening_cash"] = True
            except Exception as exc:  # noqa: BLE001
                result["reconcile_error"] = str(exc)
        else:
            result["reconciled"] = False
            result["match_reason"] = reason
            from app.models import Approval, ApprovalStatus
            from uuid import uuid4
            from app.audit import utcnow as now

            db.add(
                Approval(
                    id=str(uuid4()),
                    workspace_id=workspace.id,
                    case_id=case_id,
                    kind="allocation_conflict",
                    title="Ambiguous payment match",
                    summary=reason,
                    proposed_payload={"invoice_id": inv.id},
                    evidence={"reason": reason},
                    status=ApprovalStatus.PENDING.value,
                    case_version_at_creation=invoice.version,
                    created_at=now(),
                )
            )
    enqueue_job(db, workspace, "recompute_forecast", {"trigger": "inbound"}, unique_key=f"forecast-inbound:{message.id}")
    db.commit()
    return {"message_id": message.id, "agent": result}


@router.post("/api/events/resend")
async def resend_webhook(
    request: Request,
    db: Session = Depends(get_db),
    svix_signature: str | None = Header(default=None, alias="svix-signature"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    raw = await request.body()
    if settings.resend_webhook_secret:
        verified = False
        try:
            from svix.webhooks import Webhook

            headers = {
                "svix-id": request.headers.get("svix-id", ""),
                "svix-timestamp": request.headers.get("svix-timestamp", ""),
                "svix-signature": svix_signature or "",
            }
            Webhook(settings.resend_webhook_secret).verify(raw, headers)
            verified = True
        except Exception:
            verified = verify_resend_signature(raw, svix_signature, settings.resend_webhook_secret)
        if not verified:
            raise HTTPException(401, "invalid webhook signature")
    payload = json.loads(raw.decode("utf-8") or "{}")
    event_type = payload.get("type")
    existing = (
        db.query(Message)
        .filter_by(provider_message_id=str(payload.get("data", {}).get("email_id") or payload.get("id") or ""))
        .one_or_none()
    )
    if existing:
        return {"duplicate": True, "message_id": existing.id}
    workspace = db.query(Workspace).filter(Workspace.api_key == (x_api_key or settings.demo_api_key)).one_or_none()
    if workspace is None:
        raise HTTPException(401, "unknown workspace")
    if event_type == "email.received":
        data = payload.get("data") or {}
        persist_inbound(
            db,
            workspace,
            from_email=(data.get("from") or "unknown@example.test"),
            to_email=",".join(data.get("to") or []),
            subject=data.get("subject") or "",
            body="",
            provider_message_id=data.get("email_id"),
            thread_id=None,
            case_id=None,
        )
        enqueue_job(db, workspace, "run_agent", {"trigger": "inbound_email"}, unique_key=f"agent-webhook:{data.get('email_id')}")
        db.commit()
    return {"ok": True, "type": event_type}
