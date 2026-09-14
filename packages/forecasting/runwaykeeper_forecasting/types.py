from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class AssumptionSet(str, Enum):
    OPTIMISTIC = "optimistic"
    BASE = "base"
    DELAYED = "delayed"
    EMPIRICAL = "empirical"


@dataclass(frozen=True)
class InvoiceInput:
    invoice_id: str
    customer_id: str
    issue_date: date
    due_date: date
    currency: str
    gross_minor: int
    outstanding_minor: int
    disputed: bool = False


@dataclass(frozen=True)
class PaymentInput:
    payment_id: str
    amount_minor: int
    currency: str
    settled_at: datetime
    customer_id: str | None = None
    reference: str | None = None


@dataclass(frozen=True)
class ExpenseInput:
    expense_id: str
    description: str
    amount_minor: int
    due_date: date
    confirmed: bool
    settled_at: datetime | None = None


@dataclass
class DailyBand:
    day: date
    p10_minor: int
    p50_minor: int
    p90_minor: int
    median_inflow_minor: int
    median_outflow_minor: int
    contributors: list[dict] = field(default_factory=list)


@dataclass
class ForecastResult:
    as_of: date
    horizon_days: int
    opening_cash_minor: int
    opening_effective_at: datetime
    buffer_minor: int
    assumption_set: str
    days: list[DailyBand]
    breach_probability: float
    median_path_minimum_minor: int
    expected_max_buffer_deficit_minor: int
    data_quality_notes: list[str]
    empirical_curve_enabled: bool
    probability_mass_beyond_horizon: float
    unsupported_horizons: list[str]
    scenario_disclaimer: str
    named_paths: dict[str, list[int]]
    shared_delay_path: list[int]
    n_scenarios: int
    seed: int
    outstanding_minor: int
    subsequent_settled_net_minor: int


@dataclass
class SensitivityResult:
    invoice_id: str
    proposed_arrival_date: date
    baseline_expected_max_deficit_minor: int
    counterfactual_expected_max_deficit_minor: int
    cash_gap_sensitivity_minor: int
    label: str
    caveat: str
