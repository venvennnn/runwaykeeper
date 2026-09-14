from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Allocation,
    ApprovalStatus,
    CollectionCase,
    CollectionState,
    Invoice,
    Payment,
    Workspace,
)
from runwaykeeper_forecasting.money import MoneyError, require_same_currency


class LedgerError(ValueError):
    pass


def allocated_to_invoice(db: Session, invoice_id: str) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(Allocation.allocated_amount_minor), 0)).where(
            Allocation.invoice_id == invoice_id,
            Allocation.approval_status != ApprovalStatus.REJECTED.value,
        )
    )
    return int(total or 0)


def allocated_from_payment(db: Session, payment_id: str) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(Allocation.allocated_amount_minor), 0)).where(
            Allocation.payment_id == payment_id,
            Allocation.approval_status != ApprovalStatus.REJECTED.value,
        )
    )
    return int(total or 0)


def invoice_outstanding(db: Session, invoice: Invoice) -> int:
    return int(invoice.gross_amount_minor - allocated_to_invoice(db, invoice.id))


def payment_status(db: Session, invoice: Invoice) -> str:
    outstanding = invoice_outstanding(db, invoice)
    if outstanding <= 0:
        return "paid"
    if outstanding < invoice.gross_amount_minor:
        return "partial"
    return "unpaid"


def create_allocation(
    db: Session,
    workspace: Workspace,
    *,
    payment: Payment,
    invoice: Invoice,
    amount_minor: int,
    evidence: dict,
    source_id: str,
    source_ts: datetime,
    provenance: str,
    approval_status: str = ApprovalStatus.APPROVED.value,
) -> Allocation:
    if amount_minor <= 0:
        raise LedgerError("allocated amount must be positive")
    require_same_currency(payment.currency, invoice.currency, context="allocation")
    if invoice.currency != workspace.base_currency:
        raise LedgerError("invoice currency must match workspace base currency")
    existing = (
        db.query(Allocation)
        .filter(Allocation.payment_id == payment.id, Allocation.invoice_id == invoice.id)
        .first()
    )
    if existing is not None:
        raise LedgerError("duplicate allocation for this payment and invoice")
    remaining_payment = payment.amount_minor - allocated_from_payment(db, payment.id)
    remaining_invoice = invoice_outstanding(db, invoice)
    if amount_minor > remaining_payment:
        raise LedgerError("payment would be over-allocated")
    if amount_minor > remaining_invoice:
        raise LedgerError("invoice would be over-allocated")
    allocation = Allocation(
        id=str(uuid4()),
        workspace_id=workspace.id,
        payment_id=payment.id,
        invoice_id=invoice.id,
        allocated_amount_minor=amount_minor,
        matching_evidence=evidence,
        approval_status=approval_status,
        source_id=source_id,
        source_ts=source_ts,
        ingested_at=source_ts,
        provenance=provenance,
    )
    db.add(allocation)
    db.flush()
    _sync_case_after_allocation(db, invoice)
    return allocation


def _sync_case_after_allocation(db: Session, invoice: Invoice) -> None:
    case = db.query(CollectionCase).filter(CollectionCase.invoice_id == invoice.id).one_or_none()
    if case is None:
        return
    if payment_status(db, invoice) == "paid":
        case.collection_state = CollectionState.CLOSED.value
        case.version += 1
    elif case.collection_state == CollectionState.CLOSED.value:
        case.collection_state = CollectionState.NEEDS_REVIEW.value
        case.version += 1


def find_unambiguous_match(
    db: Session,
    workspace: Workspace,
    *,
    customer_id: str | None,
    currency: str,
    amount_minor: int,
    reference: str | None,
) -> tuple[Payment | None, Invoice | None, str]:
    """Return (payment, invoice, reason) for an exact ledger match.

    Automatic allocation is allowed only when customer, currency, amount, and a
    unique invoice reference all support one match.
    """
    invoices = db.query(Invoice).filter(Invoice.workspace_id == workspace.id).all()
    ref = (reference or "").strip().upper()
    ref_hits = [
        inv
        for inv in invoices
        if ref and (inv.external_reference.upper() == ref or inv.external_reference.upper() in ref)
    ]
    if len(ref_hits) != 1:
        return None, None, "invoice reference is missing or not unique"
    invoice = ref_hits[0]
    if customer_id and invoice.customer_id != customer_id:
        return None, None, "customer identity does not match the referenced invoice"
    if invoice.currency != currency:
        return None, None, "currency mismatch"
    outstanding = invoice_outstanding(db, invoice)
    payments = db.query(Payment).filter(Payment.workspace_id == workspace.id).all()
    candidates = []
    for payment in payments:
        remaining = payment.amount_minor - allocated_from_payment(db, payment.id)
        if remaining <= 0:
            continue
        if payment.currency != currency:
            continue
        if customer_id and payment.customer_id and payment.customer_id != customer_id:
            continue
        if remaining == amount_minor or remaining == outstanding == amount_minor:
            pay_ref = (payment.reference or "").upper()
            if invoice.external_reference.upper() in pay_ref or pay_ref == ref:
                candidates.append(payment)
    if len(candidates) != 1:
        return None, invoice, "payment match is ambiguous or missing"
    payment = candidates[0]
    if payment.currency != invoice.currency:
        return None, invoice, "currency mismatch"
    return payment, invoice, "unambiguous match"
