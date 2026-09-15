from pathlib import Path

import pytest

from google_ads_mcp.errors import AdsError
from google_ads_mcp.store import reset_store_for_tests
from google_ads_mcp.tools.writes import set_campaign_status


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
