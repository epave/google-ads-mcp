from pathlib import Path

from google_ads_mcp.store import reset_store_for_tests
from google_ads_mcp.tools import dashboard as dashboard_mod


def _assert_dashboard_query_shape(query: str) -> None:
    """Catalog may filter on status (and must select it). Secondary queries use IDs."""
    if "FROM customer" in query or "FROM recommendation" in query:
        return
    where = query.split("WHERE", 1)[1] if "WHERE" in query else ""
    select_clause = query.split("FROM", 1)[0]
    if "campaign.status" in where:
        assert "campaign.status" in select_clause, query
        assert "campaign_budget.amount_micros" in query  # catalog query
    else:
        # Metric / asset follow-ups must not reintroduce a status WHERE.
        assert "campaign.status" not in where, query
        if "segments.date" in query or "FROM campaign_asset" in query:
            assert "campaign.id IN (" in query, query


def test_dashboard_markdown_formats_source_micros(monkeypatch, tmp_path: Path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    queries: list[str] = []

    def fake_search(cid, query, login_customer_id=None):
        queries.append(query)
        _assert_dashboard_query_shape(query)
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
    assert any("campaign.id IN (9)" in q for q in queries)
    assert any(
        "campaign.status" in q.split("WHERE", 1)[0] and "campaign_budget.amount_micros" in q
        for q in queries
        if "WHERE" in q and "FROM campaign " in q
    )
    dashboard_mod.get_campaign_dashboard(
        "1234567890", include_paused=True, persist_snapshot=False
    )
