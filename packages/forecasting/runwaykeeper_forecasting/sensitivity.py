from __future__ import annotations

from datetime import date, datetime

from runwaykeeper_forecasting.engine import run_forecast
from runwaykeeper_forecasting.types import (
    ExpenseInput,
    InvoiceInput,
    PaymentInput,
    SensitivityResult,
)

SENSITIVITY_CAVEAT = (
    "Cash-gap sensitivity measures a hypothetical timing change for this invoice's "
    "remaining balance. It does not establish that contacting the customer causes payment, "
    "and it is not expected recovery or reminder effectiveness."
)


def cash_gap_sensitivity(
    *,
    invoice_id: str,
    proposed_arrival_date: date,
    as_of: date,
    opening_cash_minor: int,
    opening_effective_at: datetime,
    buffer_minor: int,
    invoices: list[InvoiceInput],
    payments: list[PaymentInput],
    expenses: list[ExpenseInput],
    historical_durations: list[int] | None = None,
    historical_events: list[bool] | None = None,
    n_scenarios: int = 2000,
    seed: int = 42,
) -> SensitivityResult:
    baseline = run_forecast(
        as_of=as_of,
        opening_cash_minor=opening_cash_minor,
        opening_effective_at=opening_effective_at,
        buffer_minor=buffer_minor,
        invoices=invoices,
        payments=payments,
        expenses=expenses,
        historical_durations=historical_durations,
        historical_events=historical_events,
        n_scenarios=n_scenarios,
        seed=seed,
    )
    counterfactual = run_forecast(
        as_of=as_of,
        opening_cash_minor=opening_cash_minor,
        opening_effective_at=opening_effective_at,
        buffer_minor=buffer_minor,
        invoices=invoices,
        payments=payments,
        expenses=expenses,
        historical_durations=historical_durations,
        historical_events=historical_events,
        n_scenarios=n_scenarios,
        seed=seed,
        forced_arrivals={invoice_id: proposed_arrival_date},
    )
    delta = (
        baseline.expected_max_buffer_deficit_minor
        - counterfactual.expected_max_buffer_deficit_minor
    )
    return SensitivityResult(
        invoice_id=invoice_id,
        proposed_arrival_date=proposed_arrival_date,
        baseline_expected_max_deficit_minor=baseline.expected_max_buffer_deficit_minor,
        counterfactual_expected_max_deficit_minor=counterfactual.expected_max_buffer_deficit_minor,
        cash_gap_sensitivity_minor=int(delta),
        label="cash-gap sensitivity",
        caveat=SENSITIVITY_CAVEAT,
    )
