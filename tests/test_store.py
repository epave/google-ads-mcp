from pathlib import Path

import duckdb

from google_ads_mcp.store import Store


def test_duckdb_is_2_0() -> None:
    version = duckdb.version()
    assert "2.0.0" in version


def test_audit_and_preview_roundtrip(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.duckdb")
    store.record_audit(
        tool="set_campaign_status",
        action="preview",
        customer_id="123",
        payload={"hello": "world"},
    )
    events = store.list_recent_audit()
    assert events[0]["tool"] == "set_campaign_status"
    assert events[0]["payload"]["hello"] == "world"

    token = store.create_preview(
        tool="set_campaign_status",
        customer_id="123",
        args={"campaign_id": "9"},
        description="pause",
        ttl_seconds=60,
    )
    consumed = store.consume_preview(token, tool="set_campaign_status", customer_id="123")
    assert consumed["campaign_id"] == "9"


def test_dashboard_snapshot_variant(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.duckdb")
    store.save_dashboard_snapshot("123", {"campaigns": [{"campaign_id": 1, "spend_7d": 10}]})
    previous = store.previous_dashboard_snapshot("123")
    assert previous is not None
    assert previous["campaigns"][0]["spend_7d"] == 10
