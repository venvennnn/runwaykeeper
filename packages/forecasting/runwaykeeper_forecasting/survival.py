from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class KaplanMeierCurve:
    """Right-censored time-to-full-payment curve. Times are integer days from issue."""

    times: np.ndarray
    survival: np.ndarray
    n_invoices: int
    n_events: int
    pooled: bool

    def survival_at(self, t: int) -> float:
        if t <= 0:
            return 1.0
        idx = int(np.searchsorted(self.times, t, side="right") - 1)
        if idx < 0:
            return 1.0
        return float(self.survival[idx])

    def remaining_cdf(self, age_days: int, max_horizon: int) -> tuple[np.ndarray, float]:
        """Conditional payment-day probabilities for days 0..max_horizon-1 given unpaid at age.

        Returns (pmf over horizon days, remaining mass beyond horizon).
        """
        s_age = max(self.survival_at(age_days), 1e-12)
        pmf = np.zeros(max_horizon, dtype=np.float64)
        prev = 1.0
        for k in range(max_horizon):
            s_next = self.survival_at(age_days + k + 1) / s_age
            s_next = min(max(s_next, 0.0), prev)
            pmf[k] = prev - s_next
            prev = s_next
        beyond = max(prev, 0.0)
        total = float(pmf.sum() + beyond)
        if total <= 0:
            return pmf, 1.0
        return pmf / total, beyond / total


def fit_kaplan_meier(
    durations: list[int],
    events: list[bool],
    *,
    min_invoices: int,
    min_events: int,
    pooled: bool,
) -> KaplanMeierCurve | None:
    n = len(durations)
    n_events = sum(1 for event in events if event)
    if n < min_invoices or n_events < min_events:
        return None
    order = np.argsort(np.asarray(durations, dtype=np.int64))
    times = np.asarray(durations, dtype=np.int64)[order]
    died = np.asarray(events, dtype=bool)[order]
    unique_times = []
    survival = []
    s = 1.0
    i = 0
    at_risk = n
    while i < n:
        t = int(times[i])
        d = 0
        c = 0
        while i < n and int(times[i]) == t:
            if died[i]:
                d += 1
            else:
                c += 1
            i += 1
        if at_risk > 0 and d > 0:
            s *= 1.0 - d / at_risk
        unique_times.append(t)
        survival.append(s)
        at_risk -= d + c
    return KaplanMeierCurve(
        times=np.asarray(unique_times, dtype=np.int64),
        survival=np.asarray(survival, dtype=np.float64),
        n_invoices=n,
        n_events=n_events,
        pooled=pooled,
    )
