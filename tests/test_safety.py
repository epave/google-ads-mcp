from pathlib import Path

import pytest

from google_ads_mcp.config import Settings
from google_ads_mcp.errors import AdsError
from google_ads_mcp.safety import SafetyGate
from google_ads_mcp.store import Store


def _settings(**overrides) -> Settings:
    data = {
        "write_enabled": False,
        "skip_confirm": False,
        "allowed_customer_ids": "1234567890",
        "budget_increase_cap": 0.2,
        "preview_ttl_seconds": 60,
    }
    data.update(overrides)
    return Settings.model_validate(data)


def test_allowlist_rejects_unknown_customer(tmp_path: Path) -> None:
    gate = SafetyGate(_settings(), Store(tmp_path / "db.duckdb"))
    with pytest.raises(AdsError):
        gate.assert_customer_allowed("000")


def test_preview_then_apply(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.duckdb")
    gate = SafetyGate(_settings(write_enabled=True), store)
    preview = gate.authorize_write(
        tool="set_campaign_status",
        customer_id="123-456-7890",
        args={"status": "PAUSED"},
        description="pause",
        dry_run=True,
    )
    assert preview["status"] == "preview"
    applied = gate.authorize_write(
        tool="set_campaign_status",
        customer_id="1234567890",
        args={"status": "PAUSED"},
        description="pause",
        dry_run=False,
        confirm_token=preview["confirm_token"],
    )
    assert applied["status"] == "authorized"


def test_writes_disabled(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.duckdb")
    gate = SafetyGate(_settings(write_enabled=False, skip_confirm=True), store)
    with pytest.raises(AdsError):
        gate.authorize_write(
            tool="set_campaign_status",
            customer_id="1234567890",
            args={},
            description="x",
            dry_run=False,
        )


def test_confirm_token_binds_args(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.duckdb")
    gate = SafetyGate(_settings(write_enabled=True), store)
    preview = gate.authorize_write(
        tool="set_campaign_status",
        customer_id="1234567890",
        args={"campaign_id": "1", "status": "PAUSED"},
        description="pause",
        dry_run=True,
    )
    with pytest.raises((AdsError, ValueError)):
        gate.authorize_write(
            tool="set_campaign_status",
            customer_id="1234567890",
            args={"campaign_id": "2", "status": "ENABLED"},
            description="enable other",
            dry_run=False,
            confirm_token=preview["confirm_token"],
        )


def test_confirm_token_rejected_on_dry_run(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.duckdb")
    gate = SafetyGate(_settings(write_enabled=True), store)
    preview = gate.authorize_write(
        tool="set_campaign_status",
        customer_id="1234567890",
        args={"status": "PAUSED"},
        description="pause",
        dry_run=True,
    )
    with pytest.raises(AdsError, match="dry_run=false"):
        gate.authorize_write(
            tool="set_campaign_status",
            customer_id="1234567890",
            args={"status": "PAUSED"},
            description="pause",
            dry_run=True,
            confirm_token=preview["confirm_token"],
        )


def test_budget_cap(tmp_path: Path) -> None:
    gate = SafetyGate(_settings(), Store(tmp_path / "db.duckdb"))
    with pytest.raises(AdsError):
        gate.assert_budget_increase_ok(10, 20, force=False)
    gate.assert_budget_increase_ok(10, 20, force=True)


def test_removed_requires_force() -> None:
    from google_ads_mcp.safety import require_force_for_removed

    with pytest.raises(AdsError, match="force=true"):
        require_force_for_removed("removed", force=False)
    assert require_force_for_removed("removed", force=True) == "REMOVED"
    assert require_force_for_removed("paused", force=False) == "PAUSED"
