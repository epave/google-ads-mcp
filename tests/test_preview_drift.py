"""Tests for preview expiry, refresh, and keyword state drift."""

from __future__ import annotations

from pathlib import Path

import pytest

from google_ads_mcp.config import Settings
from google_ads_mcp.errors import AdsError
from google_ads_mcp.safety import SafetyGate
from google_ads_mcp.store import Store, reset_store_for_tests
from google_ads_mcp.tools import writes as writes_mod


def _settings(**overrides) -> Settings:
    data = {
        "write_enabled": True,
        "skip_confirm": False,
        "allowed_customer_ids": None,
        "budget_increase_cap": 0.2,
        "preview_ttl_seconds": 60,
    }
    data.update(overrides)
    return Settings.model_validate(data)


def test_preview_includes_expires_at(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.duckdb")
    gate = SafetyGate(_settings(), store)
    preview = gate.authorize_write(
        tool="set_campaign_status",
        customer_id="1234567890",
        args={"status": "PAUSED"},
        description="pause",
        dry_run=True,
    )
    assert preview["expires_in_seconds"] == 60
    assert "expires_at" in preview
    assert preview["expires_at"].endswith("Z")


def test_refresh_preview_extends_ttl(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.duckdb")
    gate = SafetyGate(_settings(preview_ttl_seconds=120), store)
    preview = gate.authorize_write(
        tool="set_campaign_status",
        customer_id="1234567890",
        args={"status": "PAUSED"},
        description="pause",
        dry_run=True,
    )
    refreshed = gate.refresh_preview(preview["confirm_token"])
    assert refreshed["status"] == "refreshed"
    assert refreshed["confirm_token"] == preview["confirm_token"]
    assert refreshed["expires_in_seconds"] == 120


def test_refresh_preview_rejects_expired(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    store = Store(tmp_path / "db.duckdb")
    gate = SafetyGate(_settings(preview_ttl_seconds=60), store)
    preview = gate.authorize_write(
        tool="set_campaign_status",
        customer_id="1234567890",
        args={"status": "PAUSED"},
        description="pause",
        dry_run=True,
    )
    past = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    store._conn.execute(
        "UPDATE preview_tokens SET expires_at = ? WHERE token = ?",
        [past, preview["confirm_token"]],
    )
    with pytest.raises(AdsError, match="expired"):
        gate.refresh_preview(preview["confirm_token"])


def test_keyword_drift_preserves_token(monkeypatch, tmp_path: Path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_SKIP_CONFIRM", "false")
    monkeypatch.delenv("GOOGLE_ADS_ALLOWED_CUSTOMER_IDS", raising=False)

    live = {
        "ad_group.id": 10,
        "ad_group_criterion.criterion_id": 99,
        "ad_group_criterion.status": "ENABLED",
        "ad_group_criterion.keyword.text": "shoes",
    }
    calls = {"n": 0}

    def fake_search(cid, query, login_customer_id=None):
        calls["n"] += 1
        # First observation (preview) returns keyword; apply path returns empty (removed).
        if calls["n"] == 1:
            return [live]
        return []

    monkeypatch.setattr(writes_mod, "search", fake_search)
    mutate_calls = {"n": 0}

    def boom(*a, **k):
        mutate_calls["n"] += 1
        raise AssertionError("mutate must not run on drift")

    monkeypatch.setattr(writes_mod, "run_ads_call", boom)
    monkeypatch.setattr(writes_mod, "get_client", lambda *a, **k: object())

    preview = writes_mod.set_keyword_status(
        customer_id="1234567890",
        ad_group_id="10",
        criterion_id="99",
        status="PAUSED",
        dry_run=True,
    )
    assert preview["status"] == "preview"
    token = preview["confirm_token"]

    with pytest.raises(AdsError, match="no longer exists"):
        writes_mod.set_keyword_status(
            customer_id="1234567890",
            ad_group_id="10",
            criterion_id="99",
            status="PAUSED",
            dry_run=False,
            confirm_token=token,
        )
    assert mutate_calls["n"] == 0

    # Token still usable after drift rejection — but keyword still missing.
    with pytest.raises(AdsError, match="no longer exists"):
        writes_mod.set_keyword_status(
            customer_id="1234567890",
            ad_group_id="10",
            criterion_id="99",
            status="PAUSED",
            dry_run=False,
            confirm_token=token,
        )


def test_keyword_dry_run_rejects_confirm_token(monkeypatch, tmp_path: Path) -> None:
    """confirm_token + dry_run=true must error, not mint a fresh preview."""
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "true")
    monkeypatch.delenv("GOOGLE_ADS_SKIP_CONFIRM", raising=False)

    live = {
        "ad_group.id": 10,
        "ad_group_criterion.criterion_id": 99,
        "ad_group_criterion.status": "ENABLED",
        "ad_group_criterion.keyword.text": "shoes",
    }

    monkeypatch.setattr(writes_mod, "search", lambda *a, **k: [live])
    monkeypatch.setattr(writes_mod, "get_client", lambda *a, **k: object())

    preview = writes_mod.set_keyword_status(
        customer_id="1234567890",
        ad_group_id="10",
        criterion_id="99",
        status="PAUSED",
        dry_run=True,
    )
    with pytest.raises(AdsError, match="dry_run=false"):
        writes_mod.set_keyword_status(
            customer_id="1234567890",
            ad_group_id="10",
            criterion_id="99",
            status="PAUSED",
            dry_run=True,
            confirm_token=preview["confirm_token"],
        )


def test_keyword_already_at_status_is_noop(monkeypatch, tmp_path: Path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_SKIP_CONFIRM", "false")
    monkeypatch.delenv("GOOGLE_ADS_ALLOWED_CUSTOMER_IDS", raising=False)

    def fake_search(cid, query, login_customer_id=None):
        return [
            {
                "ad_group.id": 10,
                "ad_group_criterion.criterion_id": 99,
                "ad_group_criterion.status": "PAUSED",
                "ad_group_criterion.keyword.text": "shoes",
            }
        ]

    monkeypatch.setattr(writes_mod, "search", fake_search)
    mutate_calls = {"n": 0}

    def boom(*a, **k):
        mutate_calls["n"] += 1
        raise AssertionError("mutate must not run for noop")

    monkeypatch.setattr(writes_mod, "run_ads_call", boom)

    preview = writes_mod.set_keyword_status(
        customer_id="1234567890",
        ad_group_id="10",
        criterion_id="99",
        status="PAUSED",
        dry_run=True,
    )
    result = writes_mod.set_keyword_status(
        customer_id="1234567890",
        ad_group_id="10",
        criterion_id="99",
        status="PAUSED",
        dry_run=False,
        confirm_token=preview["confirm_token"],
    )
    assert result["noop"] is True
    assert mutate_calls["n"] == 0


def test_keyword_noop_with_skip_confirm(monkeypatch, tmp_path: Path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_SKIP_CONFIRM", "true")
    monkeypatch.delenv("GOOGLE_ADS_ALLOWED_CUSTOMER_IDS", raising=False)

    def fake_search(cid, query, login_customer_id=None):
        return [
            {
                "ad_group.id": 10,
                "ad_group_criterion.criterion_id": 99,
                "ad_group_criterion.status": "PAUSED",
                "ad_group_criterion.keyword.text": "shoes",
            }
        ]

    monkeypatch.setattr(writes_mod, "search", fake_search)
    mutate_calls = {"n": 0}

    def boom(*a, **k):
        mutate_calls["n"] += 1
        raise AssertionError("mutate must not run for noop under skip_confirm")

    monkeypatch.setattr(writes_mod, "run_ads_call", boom)
    result = writes_mod.set_keyword_status(
        customer_id="1234567890",
        ad_group_id="10",
        criterion_id="99",
        status="PAUSED",
        dry_run=False,
    )
    assert result["noop"] is True
    assert mutate_calls["n"] == 0


def test_refresh_preview_audit_redacts_token(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.duckdb")
    gate = SafetyGate(_settings(), store)
    preview = gate.authorize_write(
        tool="set_campaign_status",
        customer_id="1234567890",
        args={"status": "PAUSED"},
        description="pause",
        dry_run=True,
    )
    token = preview["confirm_token"]
    gate.refresh_preview(token)
    events = store.list_recent_audit(limit=5)
    refresh_events = [e for e in events if e["action"] == "refresh_preview"]
    assert refresh_events
    payload = refresh_events[0]["payload"]
    assert "confirm_token" not in payload
    assert "confirm_token_fingerprint" in payload
    assert token not in str(payload)
    assert payload["confirm_token_fingerprint"] != token


def test_keyword_apply_observes_once(monkeypatch, tmp_path: Path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_SKIP_CONFIRM", "true")
    monkeypatch.delenv("GOOGLE_ADS_ALLOWED_CUSTOMER_IDS", raising=False)

    calls = {"n": 0}

    def fake_search(cid, query, login_customer_id=None):
        calls["n"] += 1
        return [
            {
                "ad_group.id": 10,
                "ad_group_criterion.criterion_id": 99,
                "ad_group_criterion.status": "ENABLED",
                "ad_group_criterion.keyword.text": "shoes",
            }
        ]

    monkeypatch.setattr(writes_mod, "search", fake_search)

    class FakeService:
        def ad_group_criterion_path(self, *a):
            return "customers/1/adGroupCriteria/10~99"

        def mutate_ad_group_criteria(self, **kwargs):
            from types import SimpleNamespace

            return SimpleNamespace(results=[SimpleNamespace(resource_name="rn")])

    class FakeClient:
        def get_service(self, name):
            return FakeService()

        def get_type(self, name):
            from tests.fakes import fake_ads_client

            return fake_ads_client().get_type(name)

        @property
        def enums(self):
            return fake_ads_client().enums

    from tests.fakes import fake_ads_client

    monkeypatch.setattr(writes_mod, "get_client", lambda *a, **k: FakeClient())
    monkeypatch.setattr(
        writes_mod,
        "run_ads_call",
        lambda fn, **kw: fn(**kw),
    )
    monkeypatch.setattr(
        writes_mod,
        "status_enum",
        lambda *a, **k: fake_ads_client().enums.AdGroupCriterionStatusEnum.PAUSED,
    )
    monkeypatch.setattr(writes_mod, "apply_update_mask", lambda *a, **k: None)

    writes_mod.set_keyword_status(
        customer_id="1234567890",
        ad_group_id="10",
        criterion_id="99",
        status="PAUSED",
        dry_run=False,
    )
    assert calls["n"] == 1


def test_keyword_removed_when_already_missing_is_noop(monkeypatch, tmp_path: Path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_SKIP_CONFIRM", "true")
    monkeypatch.delenv("GOOGLE_ADS_ALLOWED_CUSTOMER_IDS", raising=False)

    monkeypatch.setattr(writes_mod, "search", lambda *a, **k: [])
    mutate_calls = {"n": 0}

    def boom(*a, **k):
        mutate_calls["n"] += 1
        raise AssertionError("mutate must not run when keyword already missing")

    monkeypatch.setattr(writes_mod, "run_ads_call", boom)
    result = writes_mod.set_keyword_status(
        customer_id="1234567890",
        ad_group_id="10",
        criterion_id="99",
        status="REMOVED",
        force=True,
        dry_run=False,
    )
    assert result["noop"] is True
    assert result["observed_state"] is None
    assert mutate_calls["n"] == 0


def test_keyword_removed_status_is_drift(monkeypatch, tmp_path: Path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_SKIP_CONFIRM", "false")
    monkeypatch.delenv("GOOGLE_ADS_ALLOWED_CUSTOMER_IDS", raising=False)

    enabled = {
        "ad_group.id": 10,
        "ad_group_criterion.criterion_id": 99,
        "ad_group_criterion.status": "ENABLED",
        "ad_group_criterion.keyword.text": "shoes",
    }
    removed = {**enabled, "ad_group_criterion.status": "REMOVED"}
    calls = {"n": 0}

    def fake_search(cid, query, login_customer_id=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return [enabled]
        return [removed]

    monkeypatch.setattr(writes_mod, "search", fake_search)
    mutate_calls = {"n": 0}

    def boom(*a, **k):
        mutate_calls["n"] += 1
        raise AssertionError("mutate must not run on REMOVED drift")

    monkeypatch.setattr(writes_mod, "run_ads_call", boom)
    monkeypatch.setattr(writes_mod, "get_client", lambda *a, **k: object())

    preview = writes_mod.set_keyword_status(
        customer_id="1234567890",
        ad_group_id="10",
        criterion_id="99",
        status="PAUSED",
        dry_run=True,
    )
    token = preview["confirm_token"]
    with pytest.raises(AdsError, match="no longer exists"):
        writes_mod.set_keyword_status(
            customer_id="1234567890",
            ad_group_id="10",
            criterion_id="99",
            status="PAUSED",
            dry_run=False,
            confirm_token=token,
        )
    assert mutate_calls["n"] == 0
    # Token preserved for retry after drift.
    with pytest.raises(AdsError, match="no longer exists"):
        writes_mod.set_keyword_status(
            customer_id="1234567890",
            ad_group_id="10",
            criterion_id="99",
            status="PAUSED",
            dry_run=False,
            confirm_token=token,
        )


def test_get_asset_review_status_is_readonly(monkeypatch) -> None:
    from google_ads_mcp.tools import assets as assets_mod

    monkeypatch.setattr(
        assets_mod,
        "search",
        lambda *a, **k: [
            {
                "asset.id": 1,
                "asset.policy_summary.approval_status": "APPROVED",
                "asset.policy_summary.review_status": "REVIEWED",
            },
            {
                "asset.id": 2,
                "asset.policy_summary.approval_status": "DISAPPROVED",
                "asset.policy_summary.review_status": "REVIEWED",
            },
            {
                "asset.id": 3,
                "asset.policy_summary.approval_status": "UNDER_REVIEW",
                "asset.policy_summary.review_status": "REVIEW_IN_PROGRESS",
            },
        ],
    )
    result = assets_mod.get_asset_review_status("1234567890", asset_ids=["1", "2", "3"])
    statuses = {
        r["asset.policy_summary.approval_status"]
        for r in result["assets"]
    }
    assert "APPROVED" in statuses
    assert "DISAPPROVED" in statuses
    assert "UNDER_REVIEW" in statuses
