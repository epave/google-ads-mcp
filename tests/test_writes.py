from pathlib import Path
from types import SimpleNamespace

import pytest

from google_ads_mcp.errors import AdsError
from google_ads_mcp.store import reset_store_for_tests
from google_ads_mcp.tools import writes as writes_mod
from google_ads_mcp.tools.writes import set_campaign_status
from tests.fakes import fake_ads_client


def _isolate_store(monkeypatch, tmp_path: Path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "false")
    monkeypatch.delenv("GOOGLE_ADS_ALLOWED_CUSTOMER_IDS", raising=False)


def test_status_is_normalized_in_confirm_args(monkeypatch, tmp_path: Path) -> None:
    _isolate_store(monkeypatch, tmp_path)
    preview = set_campaign_status(
        customer_id="1234567890",
        campaign_id="111",
        status="paused",
        dry_run=True,
    )
    assert preview["args"]["status"] == "PAUSED"
    assert preview["args"]["force"] is False
    again = set_campaign_status(
        customer_id="1234567890",
        campaign_id="111",
        status="PAUSED",
        dry_run=True,
    )
    assert again["args"] == preview["args"]


def test_removed_preview_requires_force(monkeypatch, tmp_path: Path) -> None:
    _isolate_store(monkeypatch, tmp_path)
    with pytest.raises(AdsError, match="force=true"):
        set_campaign_status(
            customer_id="1234567890",
            campaign_id="111",
            status="REMOVED",
            dry_run=True,
        )
    preview = set_campaign_status(
        customer_id="1234567890",
        campaign_id="111",
        status="removed",
        force=True,
        dry_run=True,
    )
    assert preview["status"] == "preview"
    assert preview["args"]["status"] == "REMOVED"
    assert preview["args"]["force"] is True


def _apply_status(monkeypatch, tmp_path: Path, *, status: str, force: bool = False):
    _isolate_store(monkeypatch, tmp_path)
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_ADS_SKIP_CONFIRM", "true")
    captured: list[object] = []

    def fake_run_ads_call(method, **kwargs):
        captured.extend(kwargs.get("operations") or [])
        resource = captured[-1].remove if status.upper() == "REMOVED" else captured[-1].update.resource_name
        return SimpleNamespace(results=[SimpleNamespace(resource_name=resource)])

    monkeypatch.setattr(writes_mod, "get_client", lambda login_customer_id=None: fake_ads_client())
    monkeypatch.setattr(writes_mod, "run_ads_call", fake_run_ads_call)
    result = set_campaign_status(
        customer_id="1234567890",
        campaign_id="111",
        status=status,
        force=force,
        dry_run=False,
    )
    return result, captured


def test_campaign_removed_uses_remove_operation(monkeypatch, tmp_path: Path) -> None:
    result, captured = _apply_status(monkeypatch, tmp_path, status="REMOVED", force=True)
    assert len(captured) == 1
    operation = captured[0]
    assert operation.remove == "customers/1234567890/campaigns/111"
    assert not operation._pb.HasField("update")
    assert result["campaign_status"] == "REMOVED"
    assert result["resource_name"] == "customers/1234567890/campaigns/111"


def test_campaign_pause_still_updates_status(monkeypatch, tmp_path: Path) -> None:
    result, captured = _apply_status(monkeypatch, tmp_path, status="PAUSED")
    assert len(captured) == 1
    operation = captured[0]
    assert operation._pb.HasField("update")
    assert operation.update.resource_name == "customers/1234567890/campaigns/111"
    assert operation.update.status.name == "PAUSED"
    assert not operation._pb.HasField("remove")
    assert result["campaign_status"] == "PAUSED"
