from pathlib import Path

from google_ads_mcp.store import reset_store_for_tests
from google_ads_mcp.tools import dashboard as dashboard_mod


def _assert_status_filter_is_selected(query: str) -> None:
    """Ads API requires a WHERE field to also appear in SELECT."""
    if "WHERE" not in query or "campaign.status" not in query.split("WHERE", 1)[1]:
        return
    select_clause = query.split("FROM", 1)[0]
    assert "campaign.status" in select_clause, query


def test_dashboard_markdown_formats_source_micros(monkeypatch, tmp_path: Path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")

    def fake_search(cid, query, login_customer_id=None):
        _assert_status_filter_is_selected(query)
        if "customer.manager" in query:
            return [
                {
                    "customer.id": 1,
                    "customer.descriptive_name": "Acme",
                    "customer.manager": False,
                }
            ]
        if "FROM recommendation" in query:
            return []
        if "FROM campaign_asset" in query:
            return [
                {"campaign.id": 9, "campaign_asset.field_type": "CALLOUT"},
            ]
        if "search_budget_lost_impression_share" in query:
            return [
                {
                    "campaign.id": 9,
                    "metrics.search_budget_lost_impression_share": 0.1,
                    "metrics.search_rank_lost_impression_share": 0.2,
                }
            ]
        if "metrics.cost_micros" not in query:
            return [
                {
                    "campaign.id": 9,
                    "campaign.name": "Spring",
                    "campaign.status": "ENABLED",
                    "campaign.primary_status": "ELIGIBLE",
                    "campaign.primary_status_reasons": [],
                    "campaign.advertising_channel_type": "SEARCH",
                    "campaign_budget.amount_micros": 12_345_678,
                }
            ]
        return [
            {
                "campaign.id": 9,
                "metrics.cost_micros": 2_300_000,
                "metrics.clicks": 3,
                "metrics.impressions": 10,
                "metrics.conversions": 0,
                "metrics.conversions_value": 0,
            }
        ]

    monkeypatch.setattr(dashboard_mod, "search", fake_search)
    payload = dashboard_mod.get_campaign_dashboard("1234567890", persist_snapshot=False)
    assert "12.35" in payload["markdown"]
    assert "2.30" in payload["markdown"]
    dashboard_mod.get_campaign_dashboard(
        "1234567890", include_paused=True, persist_snapshot=False
    )
