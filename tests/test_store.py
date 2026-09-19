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

    token, expires_at = store.create_preview(
        tool="set_campaign_status",
        customer_id="123",
        args={"campaign_id": "9"},
        description="pause",
        ttl_seconds=60,
        observed_state={"status": "ENABLED"},
    )
    assert expires_at is not None
    peeked = store.peek_preview(token, tool="set_campaign_status", customer_id="123")
    assert peeked["observed_state"]["status"] == "ENABLED"
    consumed = store.consume_preview(token, tool="set_campaign_status", customer_id="123")
    assert consumed["campaign_id"] == "9"


def test_dashboard_snapshot_variant(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.duckdb")
    store.save_dashboard_snapshot("123", {"campaigns": [{"campaign_id": 1, "spend_7d": 10}]})
    previous = store.previous_dashboard_snapshot("123")
    assert previous is not None
    assert previous["campaigns"][0]["spend_7d"] == 10


def test_refresh_preview_clears_observed_state(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.duckdb")
    token, _ = store.create_preview(
        tool="set_keyword_status",
        customer_id="123",
        args={"ad_group_id": "10", "criterion_id": "99", "status": "PAUSED"},
        description="pause",
        ttl_seconds=60,
        observed_state={"status": "ENABLED"},
    )
    cleared = store.refresh_preview(token, ttl_seconds=60, observed_state=None)
    assert cleared["observed_state"] is None
    peeked = store.peek_preview(token, tool="set_keyword_status", customer_id="123")
    assert peeked["observed_state"] is None


def test_refresh_preview_preserves_observed_when_unset(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.duckdb")
    token, _ = store.create_preview(
        tool="set_keyword_status",
        customer_id="123",
        args={"ad_group_id": "10", "criterion_id": "99", "status": "PAUSED"},
        description="pause",
        ttl_seconds=60,
        observed_state={"status": "ENABLED"},
    )
    refreshed = store.refresh_preview(token, ttl_seconds=90)
    assert refreshed["observed_state"]["status"] == "ENABLED"
    peeked = store.peek_preview(token, tool="set_keyword_status", customer_id="123")
    assert peeked["observed_state"]["status"] == "ENABLED"


def test_refresh_preview_fails_when_token_consumed(tmp_path: Path) -> None:
    import pytest

    store = Store(tmp_path / "state.duckdb")
    token, _ = store.create_preview(
        tool="set_campaign_status",
        customer_id="123",
        args={"status": "PAUSED"},
        description="pause",
        ttl_seconds=60,
    )
    store.consume_preview(token, tool="set_campaign_status", customer_id="123")
    with pytest.raises(ValueError, match="already been used"):
        store.refresh_preview(token, ttl_seconds=60)


def test_refresh_preview_fails_when_update_claims_zero_rows(tmp_path: Path) -> None:
    """SELECT may see unused; concurrent consume must still make refresh fail."""
    import pytest

    store = Store(tmp_path / "state.duckdb")
    token, _ = store.create_preview(
        tool="set_campaign_status",
        customer_id="123",
        args={"status": "PAUSED"},
        description="pause",
        ttl_seconds=60,
        observed_state={"status": "ENABLED"},
    )
    real = store._conn
    saw_select = {"done": False}

    class CachedRow:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class ConnProxy:
        def execute(self, query, parameters=None):
            result = (
                real.execute(query, parameters)
                if parameters is not None
                else real.execute(query)
            )
            if (
                not saw_select["done"]
                and "SELECT" in query
                and "FROM preview_tokens WHERE token" in query
            ):
                saw_select["done"] = True
                row = result.fetchone()
                real.execute(
                    "UPDATE preview_tokens SET used_at = CURRENT_TIMESTAMP WHERE token = ?",
                    [token],
                )
                return CachedRow(row)
            return result

        def __getattr__(self, name):
            return getattr(real, name)

    store._conn = ConnProxy()  # type: ignore[assignment]
    with pytest.raises(ValueError, match="already been used"):
        store.refresh_preview(token, ttl_seconds=60, observed_state={"status": "PAUSED"})

