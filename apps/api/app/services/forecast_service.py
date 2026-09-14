from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.audit import utcnow
from app.config import settings
from app.ledger import allocated_to_invoice, invoice_outstanding
from app.models import (
    CollectionCase,
    CollectionState,
    Expense,
    ForecastRun,
    Invoice,
    Payment,
    Workspace,
)
from runwaykeeper_forecasting.engine import run_forecast
from runwaykeeper_forecasting.sensitivity import cash_gap_sensitivity
from runwaykeeper_forecasting.types import ExpenseInput, InvoiceInput, PaymentInput


def _serialize_datetime(value: datetime | date | None):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat()


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def load_inputs(db: Session, workspace: Workspace) -> tuple[list[InvoiceInput], list[PaymentInput], list[ExpenseInput], list[int], list[bool]]:
    invoices = db.query(Invoice).filter(Invoice.workspace_id == workspace.id).all()
    payments = db.query(Payment).filter(Payment.workspace_id == workspace.id).all()
    expenses = db.query(Expense).filter(Expense.workspace_id == workspace.id).all()
    invoice_inputs = []
    durations = []
    events = []
    as_of = utcnow().date()
    for invoice in invoices:
        outstanding = invoice_outstanding(db, invoice)
        case = db.query(CollectionCase).filter(CollectionCase.invoice_id == invoice.id).one_or_none()
        disputed = bool(case and case.collection_state == CollectionState.DISPUTED.value)
        invoice_inputs.append(
            InvoiceInput(
                invoice_id=invoice.id,
                customer_id=invoice.customer_id,
                issue_date=invoice.issue_date,
                due_date=invoice.due_date,
                currency=invoice.currency,
                gross_minor=invoice.gross_amount_minor,
                outstanding_minor=max(outstanding, 0),
                disputed=disputed,
            )
        )
        paid = outstanding <= 0
        if paid:
            last_payment = None
            from app.models import Allocation

            allocs = db.query(Allocation).filter(Allocation.invoice_id == invoice.id).all()
            if allocs:
                pay_ids = [a.payment_id for a in allocs]
                pays = db.query(Payment).filter(Payment.id.in_(pay_ids)).all()
                if pays:
                    last_payment = max(_as_utc(p.settled_at) for p in pays)
            end = last_payment.date() if last_payment else invoice.due_date
            durations.append(max((end - invoice.issue_date).days, 0))
            events.append(True)
        else:
            durations.append(max((as_of - invoice.issue_date).days, 0))
            events.append(False)
    payment_inputs = [
        PaymentInput(
            payment_id=p.id,
            amount_minor=p.amount_minor,
            currency=p.currency,
            settled_at=_as_utc(p.settled_at),
            customer_id=p.customer_id,
            reference=p.reference,
        )
        for p in payments
    ]
    expense_inputs = [
        ExpenseInput(
            expense_id=e.id,
            description=e.description,
            amount_minor=e.amount_minor,
            due_date=e.due_date,
            confirmed=e.confirmed,
            settled_at=_as_utc(e.settled_at),
        )
        for e in expenses
    ]
    return invoice_inputs, payment_inputs, expense_inputs, durations, events


def latest_snapshot(db: Session, workspace: Workspace):
    from app.models import CashSnapshot

    return (
        db.query(CashSnapshot)
        .filter(CashSnapshot.workspace_id == workspace.id)
        .order_by(CashSnapshot.effective_at.desc())
        .first()
    )


def persist_forecast(
    db: Session,
    workspace: Workspace,
    *,
    is_what_if: bool = False,
    promise_case_id: str | None = None,
    forced_arrivals: dict | None = None,
) -> ForecastRun:
    snapshot = latest_snapshot(db, workspace)
    if snapshot is None:
        raise ValueError("opening cash snapshot is required")
    invoices, payments, expenses, durations, events = load_inputs(db, workspace)
    result = run_forecast(
        as_of=utcnow().date(),
        opening_cash_minor=snapshot.balance_minor,
        opening_effective_at=_as_utc(snapshot.effective_at),
        buffer_minor=workspace.buffer_minor,
        invoices=invoices,
        payments=payments,
        expenses=expenses,
        historical_durations=durations,
        historical_events=events,
        n_scenarios=settings.forecast_scenarios,
        horizon_days=settings.forecast_horizon_days,
        seed=settings.forecast_seed,
        min_invoices=settings.km_min_invoices,
        min_events=settings.km_min_events,
        forced_arrivals=forced_arrivals,
    )
    payload = {
        "as_of": result.as_of.isoformat(),
        "horizon_days": result.horizon_days,
        "opening_cash_minor": result.opening_cash_minor,
        "opening_effective_at": result.opening_effective_at.isoformat(),
        "buffer_minor": result.buffer_minor,
        "assumption_set": result.assumption_set,
        "days": [
            {
                "day": band.day.isoformat(),
                "p10_minor": band.p10_minor,
                "p50_minor": band.p50_minor,
                "p90_minor": band.p90_minor,
                "median_inflow_minor": band.median_inflow_minor,
                "median_outflow_minor": band.median_outflow_minor,
                "contributors": band.contributors,
            }
            for band in result.days
        ],
        "breach_probability": result.breach_probability,
        "median_path_minimum_minor": result.median_path_minimum_minor,
        "expected_max_buffer_deficit_minor": result.expected_max_buffer_deficit_minor,
        "data_quality_notes": result.data_quality_notes,
        "empirical_curve_enabled": result.empirical_curve_enabled,
        "probability_mass_beyond_horizon": result.probability_mass_beyond_horizon,
        "unsupported_horizons": result.unsupported_horizons,
        "scenario_disclaimer": result.scenario_disclaimer,
        "named_paths": result.named_paths,
        "shared_delay_path": result.shared_delay_path,
        "n_scenarios": result.n_scenarios,
        "seed": result.seed,
        "outstanding_minor": result.outstanding_minor,
        "subsequent_settled_net_minor": result.subsequent_settled_net_minor,
        "freshness": utcnow().isoformat(),
        "is_what_if": is_what_if,
        "promise_case_id": promise_case_id,
    }
    run = ForecastRun(
        id=str(uuid4()),
        workspace_id=workspace.id,
        assumptions={
            "mixture": "optimistic 25% / base 55% / delayed 20%, plus empirical when enabled",
            "seed": settings.forecast_seed,
            "n_scenarios": settings.forecast_scenarios,
        },
        result=payload,
        is_what_if=is_what_if,
        promise_case_id=promise_case_id,
        created_at=utcnow(),
    )
    db.add(run)
    db.flush()
    return run


def sensitivity_for_invoice(db: Session, workspace: Workspace, invoice: Invoice, proposed: date):
    snapshot = latest_snapshot(db, workspace)
    invoices, payments, expenses, durations, events = load_inputs(db, workspace)
    return cash_gap_sensitivity(
        invoice_id=invoice.id,
        proposed_arrival_date=proposed,
        as_of=utcnow().date(),
        opening_cash_minor=snapshot.balance_minor,
        opening_effective_at=_as_utc(snapshot.effective_at),
        buffer_minor=workspace.buffer_minor,
        invoices=invoices,
        payments=payments,
        expenses=expenses,
        historical_durations=durations,
        historical_events=events,
        n_scenarios=settings.forecast_scenarios,
        seed=settings.forecast_seed,
    )
