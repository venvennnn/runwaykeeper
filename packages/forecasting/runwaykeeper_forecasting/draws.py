from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from runwaykeeper_forecasting.survival import KaplanMeierCurve
from runwaykeeper_forecasting.types import AssumptionSet, InvoiceInput


def _clip_day(offset: int, horizon: int) -> int | None:
    if offset < 0:
        return 0
    if offset >= horizon:
        return None
    return offset


def assumption_offset_days(
    invoice: InvoiceInput,
    as_of: date,
    assumption: AssumptionSet,
    rng: np.random.Generator,
) -> int | None:
    """Draw days from as_of until remaining balance arrives. None = beyond horizon."""
    due_offset = (invoice.due_date - as_of).days
    if assumption is AssumptionSet.OPTIMISTIC:
        if due_offset > 0:
            return int(due_offset)
        return int(rng.integers(0, 4))
    if assumption is AssumptionSet.BASE:
        if due_offset > 0:
            return int(due_offset + rng.integers(0, 8))
        return int(rng.integers(3, 15))
    if assumption is AssumptionSet.DELAYED:
        if due_offset > 0:
            return int(due_offset + rng.integers(14, 36))
        return int(rng.integers(18, 50))
    raise ValueError(f"unsupported assumption for parametric draw: {assumption}")


def invoice_payment_day(
    invoice: InvoiceInput,
    as_of: date,
    assumption: AssumptionSet,
    horizon: int,
    rng: np.random.Generator,
    curve: KaplanMeierCurve | None,
) -> int | None:
    if invoice.outstanding_minor <= 0 or invoice.disputed:
        return None
    if assumption is AssumptionSet.EMPIRICAL and curve is not None:
        age = max((as_of - invoice.issue_date).days, 0)
        pmf, beyond = curve.remaining_cdf(age, horizon)
        draw = float(rng.random())
        if draw >= 1.0 - beyond:
            return None
        cumulative = np.cumsum(pmf)
        idx = int(np.searchsorted(cumulative, draw, side="left"))
        return _clip_day(idx, horizon)
    offset = assumption_offset_days(invoice, as_of, assumption, rng)
    if offset is None:
        return None
    return _clip_day(int(offset), horizon)


def mix_assumption(rng: np.random.Generator) -> AssumptionSet:
    """Mixture used for the 2,000 seeded scenarios (conditional on these weights)."""
    pick = float(rng.random())
    if pick < 0.25:
        return AssumptionSet.OPTIMISTIC
    if pick < 0.80:
        return AssumptionSet.BASE
    return AssumptionSet.DELAYED
