"""Currency helpers. Google Ads API stores money in micros (1 unit = 1e6 micros)."""

from __future__ import annotations

MICROS = 1_000_000


def to_micros(amount: float | int) -> int:
    """Convert a human currency amount to micros."""
    if amount < 0:
        raise ValueError("amount must be >= 0")
    return int(round(float(amount) * MICROS))


def from_micros(micros: int | float | None) -> float:
    """Convert micros to a human currency amount."""
    if micros is None:
        return 0.0
    return float(micros) / MICROS


def format_money(micros: int | float | None, currency: str | None = None) -> str:
    amount = from_micros(micros)
    if currency:
        return f"{amount:,.2f} {currency}"
    return f"{amount:,.2f}"
