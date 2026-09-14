from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.audit import record_audit, utcnow
from app.config import settings
from app.ledger import invoice_outstanding, payment_status
from app.models import (
    CollectionCase,
    DeliveryStatus,
    Invoice,
    Message,
    Outbox,
    Workspace,
    WorkspaceMode,
)

logger = logging.getLogger(__name__)

INJECTION_MARKERS = (
    "ignore previous instructions",
    "reveal secrets",
    "change the recipient",
    "bypass tool",
    "system prompt",
)


def sanitize_email_body(body: str) -> str:
    """Inbound bodies are untrusted content. Store an excerpt, never follow instructions."""
    text = body.replace("\x00", "")
    lowered = text.lower()
    if any(marker in lowered for marker in INJECTION_MARKERS):
        return "[untrusted inbound content omitted: instruction-like payload]"
    return text[:500]


def contains_injection(body: str) -> bool:
    lowered = body.lower()
    return any(marker in lowered for marker in INJECTION_MARKERS)


def verify_resend_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    if not secret:
        return False
    if not signature_header:
        return False
    try:
        import svix.webhooks

        wh = svix.webhooks.Webhook(secret)
        # Caller should use svix verify with headers; this helper is a fallback HMAC.
    except Exception:
        pass
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature_header.removeprefix("sha256="))


def capture_or_send(
    db: Session,
    workspace: Workspace,
    *,
    case: CollectionCase,
    to_email: str,
    subject: str,
    body: str,
    idempotency_key: str,
    authorized_recipient: str,
) -> Message:
    if to_email.lower() != authorized_recipient.lower():
        raise PermissionError("backend guard: cannot change reminder recipient")
    invoice = db.get(Invoice, case.invoice_id)
    if payment_status(db, invoice) == "paid":
        raise ValueError("payment status changed; reminder not sent")
    existing = db.query(Message).filter(Message.idempotency_key == idempotency_key).one_or_none()
    if existing:
        return existing
    is_simulation = workspace.mode != WorkspaceMode.CONNECTED.value or not settings.resend_api_key
    now = utcnow()
    message = Message(
        id=str(uuid4()),
        workspace_id=workspace.id,
        case_id=case.id,
        direction="outbound",
        provider="resend" if not is_simulation else "simulation",
        from_email=settings.resend_from_email,
        to_email=to_email,
        subject=subject,
        body_excerpt=body[:500],
        delivery_status=DeliveryStatus.CAPTURED.value if is_simulation else DeliveryStatus.QUEUED.value,
        is_simulation=is_simulation,
        idempotency_key=idempotency_key,
        source_id=idempotency_key,
        source_ts=now,
        ingested_at=now,
        provenance="simulated" if is_simulation else "user_entered",
    )
    db.add(message)
    outbox = Outbox(
        id=str(uuid4()),
        workspace_id=workspace.id,
        action_key=idempotency_key,
        payload={"message_id": message.id, "to": to_email, "subject": subject, "body": body},
        status="pending" if not is_simulation else "captured",
        created_at=now,
        processed_at=now if is_simulation else None,
    )
    db.add(outbox)
    if is_simulation:
        message.delivery_status = DeliveryStatus.CAPTURED.value
        record_audit(
            db,
            workspace,
            event_type="message_captured",
            entity_type="message",
            entity_id=message.id,
            payload={"simulation": True, "delivery_label": "simulated capture — not real delivery"},
            case_version=case.version,
        )
        return message
    _send_resend(message, body, idempotency_key)
    outbox.status = "processed"
    outbox.processed_at = utcnow()
    return message


def _send_resend(message: Message, body: str, idempotency_key: str) -> None:
    import resend

    resend.api_key = settings.resend_api_key
    result = resend.Emails.send(
        {
            "from": settings.resend_from_email,
            "to": [message.to_email],
            "subject": message.subject,
            "text": body,
            "headers": {"Idempotency-Key": idempotency_key},
        }
    )
    message.provider_message_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
    message.delivery_status = DeliveryStatus.SENT.value
    message.is_simulation = False


def dispatch_outbox_message(db: Session, workspace: Workspace, payload: dict) -> None:
    message = db.get(Message, payload["message_id"])
    if message is None:
        return
    invoice = None
    if message.case_id:
        case = db.get(CollectionCase, message.case_id)
        invoice = db.get(Invoice, case.invoice_id) if case else None
        if invoice and payment_status(db, invoice) == "paid":
            message.delivery_status = DeliveryStatus.FAILED.value
            record_audit(
                db,
                workspace,
                event_type="send_aborted_paid",
                entity_type="message",
                entity_id=message.id,
                payload={"reason": "payment arrived before reminder dispatch"},
            )
            return
    if message.is_simulation:
        message.delivery_status = DeliveryStatus.CAPTURED.value
        return
    _send_resend(message, payload.get("body", ""), message.idempotency_key or message.id)


def persist_inbound(
    db: Session,
    workspace: Workspace,
    *,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
    provider_message_id: str | None,
    thread_id: str | None,
    case_id: str | None,
) -> Message:
    now = utcnow()
    message = Message(
        id=str(uuid4()),
        workspace_id=workspace.id,
        case_id=case_id,
        direction="inbound",
        provider="resend" if workspace.mode == WorkspaceMode.CONNECTED.value else "simulation",
        provider_message_id=provider_message_id,
        thread_id=thread_id,
        from_email=from_email,
        to_email=to_email,
        subject=subject[:255],
        body_excerpt=sanitize_email_body(body),
        delivery_status=DeliveryStatus.DELIVERED.value,
        is_simulation=workspace.mode != WorkspaceMode.CONNECTED.value,
        source_id=provider_message_id or str(uuid4()),
        source_ts=now,
        ingested_at=now,
        provenance="simulated" if workspace.mode != WorkspaceMode.CONNECTED.value else "imported",
    )
    db.add(message)
    db.flush()
    return message
