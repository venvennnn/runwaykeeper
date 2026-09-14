from datetime import UTC, date, datetime

import numpy as np

from runwaykeeper_forecasting.engine import run_forecast
from runwaykeeper_forecasting.money import parse_minor_amount
from runwaykeeper_forecasting.sensitivity import cash_gap_sensitivity
from runwaykeeper_forecasting.survival import fit_kaplan_meier
from runwaykeeper_forecasting.types import ExpenseInput, InvoiceInput, PaymentInput


def _invoice(i: str, outstanding: int, due: date, issue: date | None = None, disputed: bool = False) -> InvoiceInput:
    return InvoiceInput(
        invoice_id=i,
        customer_id="c1",
        issue_date=issue or date(2026, 7, 1),
        due_date=due,
        currency="USD",
        gross_minor=outstanding * 2 if outstanding else 100,
        outstanding_minor=outstanding,
        disputed=disputed,
    )


def test_money_rejects_float_like_extra_decimals():
    assert parse_minor_amount("12.34") == 1234
    try:
        parse_minor_amount("12.345")
        assert False
    except ValueError:
        pass


def test_opening_cash_not_increased_by_prior_settlement():
    opening_at = datetime(2026, 9, 1, tzinfo=UTC)
    result = run_forecast(
        as_of=date(2026, 9, 14),
        opening_cash_minor=3_825_000,
        opening_effective_at=opening_at,
        buffer_minor=3_000_000,
        invoices=[_invoice("inv-1", 1_840_000, date(2026, 8, 20))],
        payments=[
            PaymentInput(
                payment_id="p1",
                amount_minor=1_840_000,
                currency="USD",
                settled_at=datetime(2026, 8, 28, tzinfo=UTC),
                reference="INV-1",
            )
        ],
        expenses=[
            ExpenseInput("e1", "payroll", 2_200_000, date(2026, 9, 15), True, None),
        ],
        n_scenarios=200,
        seed=42,
    )
    assert result.opening_cash_minor == 3_825_000
    assert result.subsequent_settled_net_minor == 0
    allocated = run_forecast(
        as_of=date(2026, 9, 14),
        opening_cash_minor=3_825_000,
        opening_effective_at=opening_at,
        buffer_minor=3_000_000,
        invoices=[_invoice("inv-1", 0, date(2026, 8, 20))],
        payments=[
            PaymentInput(
                payment_id="p1",
                amount_minor=1_840_000,
                currency="USD",
                settled_at=datetime(2026, 8, 28, tzinfo=UTC),
            )
        ],
        expenses=[
            ExpenseInput("e1", "payroll", 2_200_000, date(2026, 9, 15), True, None),
        ],
        n_scenarios=200,
        seed=42,
    )
    assert allocated.opening_cash_minor == 3_825_000
    assert allocated.outstanding_minor == 0
    assert allocated.median_path_minimum_minor <= result.median_path_minimum_minor


def test_forecast_is_reproducible():
    kwargs = dict(
        as_of=date(2026, 9, 14),
        opening_cash_minor=3_825_000,
        opening_effective_at=datetime(2026, 9, 1, tzinfo=UTC),
        buffer_minor=3_000_000,
        invoices=[_invoice("inv-1", 1_840_000, date(2026, 8, 20)), _invoice("inv-2", 750_000, date(2026, 9, 10))],
        payments=[],
        expenses=[ExpenseInput("e1", "payroll", 2_200_000, date(2026, 9, 15), True, None)],
        n_scenarios=200,
        seed=42,
    )
    a = run_forecast(**kwargs)
    b = run_forecast(**kwargs)
    assert [d.p50_minor for d in a.days] == [d.p50_minor for d in b.days]
    assert a.breach_probability == b.breach_probability


def test_partial_invoice_forecasts_remaining_only():
    result = run_forecast(
        as_of=date(2026, 9, 14),
        opening_cash_minor=1_000_000,
        opening_effective_at=datetime(2026, 9, 1, tzinfo=UTC),
        buffer_minor=500_000,
        invoices=[
            InvoiceInput(
                invoice_id="p",
                customer_id="c",
                issue_date=date(2026, 8, 1),
                due_date=date(2026, 8, 31),
                currency="USD",
                gross_minor=310_000,
                outstanding_minor=210_000,
            )
        ],
        payments=[],
        expenses=[],
        n_scenarios=50,
        seed=1,
    )
    assert result.outstanding_minor == 210_000
    assert any("remaining balance" in n.lower() or "partial" in n.lower() for n in result.data_quality_notes)


def test_disputed_excluded_from_simulated_receipts():
    result = run_forecast(
        as_of=date(2026, 9, 14),
        opening_cash_minor=1_000_000,
        opening_effective_at=datetime(2026, 9, 1, tzinfo=UTC),
        buffer_minor=500_000,
        invoices=[_invoice("d", 900_000, date(2026, 8, 1), disputed=True)],
        payments=[],
        expenses=[],
        n_scenarios=20,
        seed=1,
    )
    assert result.outstanding_minor == 900_000
    assert all(band.median_inflow_minor == 0 for band in result.days)


def test_km_gates_and_right_censoring():
    durations = [10] * 10 + [20] * 10
    events = [True] * 10 + [False] * 10
    assert fit_kaplan_meier(durations, events, min_invoices=50, min_events=20, pooled=True) is None
    durations = list(range(50)) + list(range(20))
    events = [True] * 20 + [False] * 50
    curve = fit_kaplan_meier(durations, events, min_invoices=50, min_events=20, pooled=True)
    assert curve is not None
    pmf, beyond = curve.remaining_cdf(5, 30)
    assert np.isclose(pmf.sum() + beyond, 1.0)
    assert beyond >= 0


def test_cash_gap_sensitivity_uses_identical_seed():
    kwargs = dict(
        as_of=date(2026, 9, 14),
        opening_cash_minor=500_000,
        opening_effective_at=datetime(2026, 9, 1, tzinfo=UTC),
        buffer_minor=800_000,
        invoices=[_invoice("inv-1", 400_000, date(2026, 8, 20))],
        payments=[],
        expenses=[ExpenseInput("e1", "payroll", 700_000, date(2026, 9, 15), True, None)],
        n_scenarios=200,
        seed=7,
    )
    result = cash_gap_sensitivity(invoice_id="inv-1", proposed_arrival_date=date(2026, 9, 14), **kwargs)
    assert result.label == "cash-gap sensitivity"
    assert "reminder effectiveness" not in result.caveat.lower() or "does not" in result.caveat.lower()
    assert result.cash_gap_sensitivity_minor >= 0


def test_scheduled_expenses_are_not_actual_cash_until_settled():
    opening_at = datetime(2026, 9, 1, tzinfo=UTC)
    result = run_forecast(
        as_of=date(2026, 9, 14),
        opening_cash_minor=1_000_000,
        opening_effective_at=opening_at,
        buffer_minor=0,
        invoices=[],
        payments=[],
        expenses=[ExpenseInput("e1", "rent", 100_000, date(2026, 8, 15), True, None)],
        n_scenarios=10,
        seed=1,
    )
    assert result.subsequent_settled_net_minor == 0
    settled = run_forecast(
        as_of=date(2026, 9, 14),
        opening_cash_minor=1_000_000,
        opening_effective_at=opening_at,
        buffer_minor=0,
        invoices=[],
        payments=[],
        expenses=[
            ExpenseInput(
                "e1",
                "rent",
                100_000,
                date(2026, 9, 10),
                True,
                datetime(2026, 9, 10, tzinfo=UTC),
            )
        ],
        n_scenarios=10,
        seed=1,
    )
    assert settled.subsequent_settled_net_minor == -100_000
