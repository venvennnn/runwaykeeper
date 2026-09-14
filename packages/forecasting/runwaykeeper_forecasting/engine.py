from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median

import numpy as np

from runwaykeeper_forecasting.draws import invoice_payment_day, mix_assumption
from runwaykeeper_forecasting.survival import KaplanMeierCurve, fit_kaplan_meier
from runwaykeeper_forecasting.types import (
    AssumptionSet,
    DailyBand,
    ExpenseInput,
    ForecastResult,
    InvoiceInput,
    PaymentInput,
)

DEFAULT_SCENARIOS = 2000
DEFAULT_HORIZON = 30
DEFAULT_MIN_INVOICES = 50
DEFAULT_MIN_EVENTS = 20

SCENARIO_DISCLAIMER = (
    "Scenario frequencies are conditional on the stated optimistic, base, and "
    "delayed-payment assumptions (and an empirical Kaplan–Meier curve when gates "
    "are met). They are not calibrated probabilities unless independently validated."
)

BASE_LIMITATION = (
    "The base scenario assumes no unrecorded new sales during the 30-day window."
)


def _day_index(value: date, as_of: date, horizon: int) -> int | None:
    offset = (value - as_of).days
    if offset < 0:
        return 0
    if offset >= horizon:
        return None
    return offset


def _settled_net_by_day(
    payments: list[PaymentInput],
    expenses: list[ExpenseInput],
    opening_effective_at: datetime,
    as_of: date,
    horizon: int,
) -> tuple[np.ndarray, int]:
    """Cash movements after the opening snapshot. Earlier receipts never increase opening cash."""
    flows = np.zeros(horizon, dtype=np.int64)
    notes_net = 0
    as_of_dt = datetime.combine(as_of, datetime.min.time()).replace(
        tzinfo=opening_effective_at.tzinfo
    )
    for payment in payments:
        if payment.settled_at <= opening_effective_at:
            continue
        settled_date = payment.settled_at.date()
        if settled_date > as_of + timedelta(days=horizon - 1):
            continue
        idx = _day_index(settled_date, as_of, horizon)
        if idx is None:
            continue
        flows[idx] += payment.amount_minor
        if payment.settled_at <= as_of_dt:
            notes_net += payment.amount_minor
    for expense in expenses:
        if expense.settled_at is None:
            continue
        if expense.settled_at <= opening_effective_at:
            continue
        settled_date = expense.settled_at.date()
        idx = _day_index(settled_date, as_of, horizon)
        if idx is None:
            continue
        flows[idx] -= expense.amount_minor
        if expense.settled_at <= as_of_dt:
            notes_net -= expense.amount_minor
    return flows, int(notes_net)


def _scheduled_outflows(
    expenses: list[ExpenseInput],
    opening_effective_at: datetime,
    as_of: date,
    horizon: int,
) -> np.ndarray:
    outflows = np.zeros(horizon, dtype=np.int64)
    for expense in expenses:
        if expense.settled_at is not None:
            continue
        idx = _day_index(expense.due_date, as_of, horizon)
        if idx is None:
            continue
        outflows[idx] += expense.amount_minor
    return outflows


def _named_path(
    invoices: list[InvoiceInput],
    as_of: date,
    horizon: int,
    assumption: AssumptionSet,
    rng: np.random.Generator,
    curve: KaplanMeierCurve | None,
) -> np.ndarray:
    receipts = np.zeros(horizon, dtype=np.int64)
    for invoice in invoices:
        day = invoice_payment_day(invoice, as_of, assumption, horizon, rng, curve)
        if day is not None:
            receipts[day] += invoice.outstanding_minor
    return receipts


def _contributors_for_day(
    day: date,
    invoices: list[InvoiceInput],
    expenses: list[ExpenseInput],
    median_days: dict[str, int | None],
    as_of: date,
    opening_effective_at: datetime,
) -> list[dict]:
    items: list[dict] = []
    for invoice in invoices:
        pay_day = median_days.get(invoice.invoice_id)
        if pay_day is None:
            continue
        if as_of + timedelta(days=pay_day) != day:
            continue
        items.append(
            {
                "kind": "inflow",
                "id": invoice.invoice_id,
                "label": f"Remaining balance invoice {invoice.invoice_id}",
                "amount_minor": invoice.outstanding_minor,
                "timing_note": (
                    "Partial invoices forecast remaining balance only; timing is an approximation."
                    if invoice.outstanding_minor < invoice.gross_minor
                    else "Simulated remaining receipt (not yet settled)."
                ),
            }
        )
    for expense in expenses:
        if expense.settled_at is not None and expense.settled_at <= opening_effective_at:
            continue
        target = expense.settled_at.date() if expense.settled_at else expense.due_date
        if target < as_of:
            target = as_of
        if target != day:
            continue
        items.append(
            {
                "kind": "outflow",
                "id": expense.expense_id,
                "label": expense.description,
                "amount_minor": -expense.amount_minor,
                "timing_note": (
                    "Settled outflow"
                    if expense.settled_at
                    else ("Confirmed obligation" if expense.confirmed else "Estimated obligation")
                ),
            }
        )
    return items


def run_forecast(
    *,
    as_of: date,
    opening_cash_minor: int,
    opening_effective_at: datetime,
    buffer_minor: int,
    invoices: list[InvoiceInput],
    payments: list[PaymentInput],
    expenses: list[ExpenseInput],
    historical_durations: list[int] | None = None,
    historical_events: list[bool] | None = None,
    n_scenarios: int = DEFAULT_SCENARIOS,
    horizon_days: int = DEFAULT_HORIZON,
    seed: int = 42,
    min_invoices: int = DEFAULT_MIN_INVOICES,
    min_events: int = DEFAULT_MIN_EVENTS,
    forced_arrivals: dict[str, date] | None = None,
    shared_delay_days: int = 14,
) -> ForecastResult:
    """Deterministic numerical forecast. The LLM must not alter returned values."""
    rng = np.random.default_rng(seed)
    notes: list[str] = [BASE_LIMITATION]
    curve = None
    if historical_durations and historical_events:
        curve = fit_kaplan_meier(
            historical_durations,
            historical_events,
            min_invoices=min_invoices,
            min_events=min_events,
            pooled=True,
        )
    empirical_enabled = curve is not None
    if empirical_enabled:
        notes.append(
            f"Empirical Kaplan–Meier curve enabled from pooled history "
            f"({curve.n_invoices} invoices, {curve.n_events} full-payment events). "
            "Gates are implementation thresholds, not a reliability guarantee."
        )
    else:
        notes.append(
            "Empirical time-to-pay curve is disabled: need at least "
            f"{min_invoices} eligible invoices and {min_events} observed full-payment events."
        )

    settled_flows, subsequent_net = _settled_net_by_day(
        payments, expenses, opening_effective_at, as_of, horizon_days
    )
    scheduled = _scheduled_outflows(expenses, opening_effective_at, as_of, horizon_days)
    open_invoices = [inv for inv in invoices if inv.outstanding_minor > 0 and not inv.disputed]
    outstanding = sum(inv.outstanding_minor for inv in invoices if inv.outstanding_minor > 0)

    forced_arrivals = forced_arrivals or {}
    paths = np.zeros((n_scenarios, horizon_days), dtype=np.int64)
    beyond_flags = np.zeros(n_scenarios, dtype=np.float64)
    invoice_day_samples: dict[str, list[int | None]] = {inv.invoice_id: [] for inv in open_invoices}

    for s in range(n_scenarios):
        assumption = mix_assumption(rng)
        if empirical_enabled and float(rng.random()) < 0.35:
            assumption = AssumptionSet.EMPIRICAL
        receipts = np.zeros(horizon_days, dtype=np.int64)
        beyond_mass = 0.0
        for invoice in open_invoices:
            if invoice.invoice_id in forced_arrivals:
                idx = _day_index(forced_arrivals[invoice.invoice_id], as_of, horizon_days)
                invoice_day_samples[invoice.invoice_id].append(idx)
                if idx is not None:
                    receipts[idx] += invoice.outstanding_minor
                else:
                    beyond_mass += 1.0
                continue
            day = invoice_payment_day(
                invoice, as_of, assumption, horizon_days, rng, curve
            )
            invoice_day_samples[invoice.invoice_id].append(day)
            if day is None:
                beyond_mass += 1.0
            else:
                receipts[day] += invoice.outstanding_minor
        beyond_flags[s] = beyond_mass / max(len(open_invoices), 1)
        net = settled_flows + receipts - scheduled
        paths[s] = opening_cash_minor + np.cumsum(net)

    p10 = np.percentile(paths, 10, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p90 = np.percentile(paths, 90, axis=0)
    path_mins = paths.min(axis=1)
    median_path_min = int(np.median(path_mins))
    deficits = np.clip(buffer_minor - path_mins, a_min=0, a_max=None)
    expected_max_deficit = int(np.round(deficits.mean()))
    breach_probability = float(np.mean(path_mins < buffer_minor))

    named_rng = np.random.default_rng(seed + 17)
    named_paths: dict[str, list[int]] = {}
    for name, assumption in (
        ("optimistic", AssumptionSet.OPTIMISTIC),
        ("base", AssumptionSet.BASE),
        ("delayed", AssumptionSet.DELAYED),
    ):
        receipts = _named_path(open_invoices, as_of, horizon_days, assumption, named_rng, curve)
        named_paths[name] = (
            opening_cash_minor + np.cumsum(settled_flows + receipts - scheduled)
        ).tolist()

    delay_receipts = np.zeros(horizon_days, dtype=np.int64)
    delay_rng = np.random.default_rng(seed + 99)
    for invoice in open_invoices:
        day = invoice_payment_day(
            invoice, as_of, AssumptionSet.BASE, horizon_days, delay_rng, curve
        )
        if day is None:
            continue
        delayed = day + shared_delay_days
        if delayed < horizon_days:
            delay_receipts[delayed] += invoice.outstanding_minor
    shared_delay_path = (
        opening_cash_minor + np.cumsum(settled_flows + delay_receipts - scheduled)
    ).tolist()
    notes.append(
        "A shared-delay stress path shifts every base receipt later by "
        f"{shared_delay_days} days to capture correlated late payments that independent draws understate."
    )

    median_days: dict[str, int | None] = {}
    for invoice_id, samples in invoice_day_samples.items():
        observed = [d for d in samples if d is not None]
        median_days[invoice_id] = int(median(observed)) if observed else None

    days: list[DailyBand] = []
    for i in range(horizon_days):
        day = as_of + timedelta(days=i)
        contributors = _contributors_for_day(
            day, open_invoices, expenses, median_days, as_of, opening_effective_at
        )
        median_inflow = sum(c["amount_minor"] for c in contributors if c["kind"] == "inflow")
        median_outflow = sum(-c["amount_minor"] for c in contributors if c["kind"] == "outflow")
        days.append(
            DailyBand(
                day=day,
                p10_minor=int(np.round(p10[i])),
                p50_minor=int(np.round(p50[i])),
                p90_minor=int(np.round(p90[i])),
                median_inflow_minor=int(median_inflow),
                median_outflow_minor=int(median_outflow),
                contributors=contributors,
            )
        )

    mass_beyond = float(beyond_flags.mean())
    unsupported: list[str] = []
    if mass_beyond > 0:
        unsupported.append(
            "Some invoices retain probability mass beyond the 30-day window; "
            "they are not forced to pay inside the forecast."
        )
    if any(inv.outstanding_minor < inv.gross_minor for inv in open_invoices):
        notes.append(
            "Partially paid invoices contribute only the remaining balance; payment timing is approximated."
        )

    return ForecastResult(
        as_of=as_of,
        horizon_days=horizon_days,
        opening_cash_minor=opening_cash_minor,
        opening_effective_at=opening_effective_at,
        buffer_minor=buffer_minor,
        assumption_set="mixture(optimistic,base,delayed[,empirical])",
        days=days,
        breach_probability=breach_probability,
        median_path_minimum_minor=median_path_min,
        expected_max_buffer_deficit_minor=expected_max_deficit,
        data_quality_notes=notes,
        empirical_curve_enabled=empirical_enabled,
        probability_mass_beyond_horizon=mass_beyond,
        unsupported_horizons=unsupported,
        scenario_disclaimer=SCENARIO_DISCLAIMER,
        named_paths=named_paths,
        shared_delay_path=shared_delay_path,
        n_scenarios=n_scenarios,
        seed=seed,
        outstanding_minor=int(outstanding),
        subsequent_settled_net_minor=subsequent_net,
    )
