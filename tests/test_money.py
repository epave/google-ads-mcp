import pytest

from google_ads_mcp.money import format_money, from_micros, to_micros


def test_to_micros() -> None:
    assert to_micros(1.5) == 1_500_000


def test_from_micros() -> None:
    assert from_micros(2_500_000) == 2.5


def test_rejects_negative() -> None:
    with pytest.raises(ValueError):
        to_micros(-1)


def test_format_money() -> None:
    assert format_money(1_000_000, "USD") == "1.00 USD"
