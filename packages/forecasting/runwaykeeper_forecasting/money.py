from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

MINOR_UNITS = 100
MONEY_QUANT = Decimal("0.01")


class MoneyError(ValueError):
    """Raised when an amount cannot be represented as integer minor units."""


def parse_minor_amount(value: str | int | Decimal, *, field: str = "amount") -> int:
    """Parse a human amount into integer minor units. Never uses binary floats."""
    if isinstance(value, int):
        return value
    try:
        decimal_value = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, AttributeError) as exc:
        raise MoneyError(f"{field} is not a valid amount: {value!r}") from exc
    if decimal_value != decimal_value.quantize(MONEY_QUANT):
        raise MoneyError(f"{field} has more than two decimal places: {value!r}")
    minor = (decimal_value * MINOR_UNITS).to_integral_value(rounding=ROUND_HALF_EVEN)
    return int(minor)


def minor_to_decimal_str(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    absolute = abs(minor)
    return f"{sign}{absolute // MINOR_UNITS}.{absolute % MINOR_UNITS:02d}"


def require_same_currency(left: str, right: str, *, context: str) -> None:
    if left != right:
        raise MoneyError(f"cross-currency {context} is not allowed: {left} vs {right}")
