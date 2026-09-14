from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.audit import utcnow
from app.cases import cooldown_reason, ensure_case
from app.ledger import invoice_outstanding, payment_status
from app.models import CollectionCase, CollectionState, Invoice, Workspace
from app.services.forecast_service import sensitivity_for_invoice


def refresh_cases(db: Session, workspace: Workspace) -> list[CollectionCase]:
    invoices = db.query(Invoice).filter(Invoice.workspace_id == workspace.id).all()
    now = utcnow()
    cases = []
    for invoice in invoices:
        case = ensure_case(db, workspace, invoice)
        status = payment_status(db, invoice)
        if status == "paid" and case.collection_state != CollectionState.CLOSED.value:
            case.collection_state = CollectionState.CLOSED.value
            case.version += 1
        elif status != "paid" and case.collection_state == CollectionState.CLOSED.value:
            case.collection_state = CollectionState.NEEDS_REVIEW.value
            case.version += 1
        elif (
            status != "paid"
            and invoice.due_date < now.date()
            and case.collection_state == CollectionState.MONITORING.value
        ):
            case.collection_state = CollectionState.FOLLOWUP_DUE.value
            case.next_action_at = now
            case.version += 1
        blocked = cooldown_reason(db, workspace, case)
        proposed = now.date() + timedelta(days=3)
        if status != "paid" and case.collection_state != CollectionState.DISPUTED.value:
            result = sensitivity_for_invoice(db, workspace, invoice, proposed)
            case.cash_gap_sensitivity_minor = result.cash_gap_sensitivity_minor
            overdue_days = max((now.date() - invoice.due_date).days, 0)
            case.priority_reason = (
                f"cash-gap sensitivity {result.cash_gap_sensitivity_minor} minor units; "
                f"{overdue_days} days overdue"
                + (f"; filtered: {blocked}" if blocked else "")
            )
        cases.append(case)
    db.flush()
    return cases


def rank_followups(db: Session, workspace: Workspace) -> list[dict]:
    refresh_cases(db, workspace)
    rows = []
    now = utcnow()
    cases = db.query(CollectionCase).filter(CollectionCase.workspace_id == workspace.id).all()
    for case in cases:
        invoice = db.get(Invoice, case.invoice_id)
        blocked = cooldown_reason(db, workspace, case)
        if blocked:
            continue
        if payment_status(db, invoice) == "paid":
            continue
        outstanding = invoice_outstanding(db, invoice)
        overdue = max((now.date() - invoice.due_date).days, 0)
        rows.append(
            {
                "case_id": case.id,
                "invoice_id": invoice.id,
                "external_reference": invoice.external_reference,
                "customer_id": invoice.customer_id,
                "customer_name": invoice.customer.display_name,
                "outstanding_minor": outstanding,
                "collection_state": case.collection_state,
                "payment_status": payment_status(db, invoice),
                "cash_gap_sensitivity_minor": case.cash_gap_sensitivity_minor,
                "days_overdue": overdue,
                "priority_reason": case.priority_reason,
                "evidence": {
                    "invoice_id": invoice.id,
                    "due_date": invoice.due_date.isoformat(),
                    "gross_amount_minor": invoice.gross_amount_minor,
                },
            }
        )
    rows.sort(key=lambda r: (-r["cash_gap_sensitivity_minor"], -r["days_overdue"]))
    return rows
