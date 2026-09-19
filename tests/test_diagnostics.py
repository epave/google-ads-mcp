"""Tests for campaign diagnostics and local findings."""

from __future__ import annotations

from google_ads_mcp.diagnostics import (
    ORIGIN_GOOGLE,
    ORIGIN_LOCAL,
    build_campaign_diagnostics,
    collect_local_findings,
    compact_diagnostic_summary,
)


def test_local_findings_missing_callouts_not_google() -> None:
    findings = collect_local_findings(
        campaign={
            "campaign.status": "ENABLED",
            "campaign.primary_status": "ELIGIBLE",
            "campaign.primary_status_reasons": [],
        },
        performance={"last_7_days": {"impressions": 100, "clicks": 10}},
        impression_share={
            "metrics.search_budget_lost_impression_share": 0.4,
            "metrics.search_rank_lost_impression_share": 0.1,
        },
        ads=[],
        keywords=[],
        assets=[{"campaign_asset.field_type": "SITELINK"}],
        conversion_actions=[{"campaign_conversion_goal.biddable": True}],
    )
    codes = {f["code"] for f in findings}
    assert "MISSING_CALLOUTS" in codes
    assert "IS_LOST_BUDGET" in codes
    assert all(f["origin"] == ORIGIN_LOCAL for f in findings)


def test_pending_scheduled_campaign_is_not_critical() -> None:
    findings = collect_local_findings(
        campaign={
            "campaign.status": "ENABLED",
            "campaign.primary_status": "PENDING",
            "campaign.primary_status_reasons": ["CAMPAIGN_SCHEDULED"],
            "campaign.start_date_time": "2099-01-01 00:00:00",
        },
        performance={"last_7_days": {"impressions": 0}},
        impression_share=None,
        ads=[],
        keywords=[],
        assets=[],
    )
    primary = next(f for f in findings if f["code"] == "PRIMARY_STATUS")
    assert primary["severity"] == "informational"


def test_pending_unscheduled_campaign_stays_critical() -> None:
    findings = collect_local_findings(
        campaign={
            "campaign.status": "ENABLED",
            "campaign.primary_status": "PENDING",
            "campaign.primary_status_reasons": [],
            "campaign.start_date_time": "2020-01-01 00:00:00",
        },
        performance={"last_7_days": {"impressions": 0}},
        impression_share=None,
        ads=[],
        keywords=[],
        assets=[],
    )
    primary = next(f for f in findings if f["code"] == "PRIMARY_STATUS")
    assert primary["severity"] == "critical"


def test_build_diagnostics_origins(monkeypatch) -> None:
    def fake_search(customer_id, query, login_customer_id=None):
        if "FROM campaign WHERE campaign.id" in query and "metrics.cost_micros" not in query:
            if "search_impression_share" in query:
                return [
                    {
                        "campaign.id": 111,
                        "metrics.search_impression_share": 0.5,
                        "metrics.search_budget_lost_impression_share": 0.05,
                        "metrics.search_rank_lost_impression_share": 0.4,
                    }
                ]
            if "segments.date" in query:
                return [
                    {
                        "campaign.id": 111,
                        "metrics.cost_micros": 1_000_000,
                        "metrics.clicks": 10,
                        "metrics.impressions": 200,
                        "metrics.conversions": 1,
                        "metrics.all_conversions": 1,
                    }
                ]
            return [
                {
                    "campaign.id": 111,
                    "campaign.name": "Test",
                    "campaign.status": "ENABLED",
                    "campaign.primary_status": "ELIGIBLE",
                    "campaign.primary_status_reasons": [],
                    "campaign.advertising_channel_type": "SEARCH",
                    "campaign.bidding_strategy_type": "MAXIMIZE_CLICKS",
                    "campaign.optimization_score": 0.7,
                    "campaign.start_date_time": "2026-01-01 00:00:00",
                    "campaign.end_date_time": None,
                    "campaign_budget.amount_micros": 5_000_000,
                }
            ]
        if "FROM ad_group_ad" in query:
            return []
        if "FROM keyword_view" in query:
            return [
                {
                    "ad_group_criterion.keyword.text": "rare kw",
                    "ad_group_criterion.system_serving_status": "RARELY_SERVED",
                    "metrics.historical_quality_score": 3,
                }
            ]
        if "FROM campaign_asset" in query:
            return []
        if "FROM recommendation" in query:
            assert "recommendation.campaigns" in query
            assert "CONTAINS ANY" in query
            return [
                {
                    "recommendation.resource_name": "customers/1/recommendations/9",
                    "recommendation.type": "KEYWORD",
                    "recommendation.campaign": "customers/1/campaigns/111",
                    "recommendation.campaigns": [],
                }
            ]
        if "FROM campaign_conversion_goal" in query:
            assert "campaign_conversion_goal.campaign" in query
            assert "campaign.id" not in query
            return [{"campaign_conversion_goal.biddable": True}]
        return []

    diag = build_campaign_diagnostics("1234567890", "111", search_fn=fake_search)
    origins = {f["origin"] for f in diag["findings"]}
    assert ORIGIN_LOCAL in origins
    assert ORIGIN_GOOGLE in origins
    google = [f for f in diag["findings"] if f["origin"] == ORIGIN_GOOGLE]
    assert google[0]["code"].startswith("GOOGLE_REC_")
    local = [f for f in diag["findings"] if f["code"] == "MISSING_CALLOUTS"]
    assert local and local[0]["origin"] == ORIGIN_LOCAL
    compact = compact_diagnostic_summary(diag)
    assert "asset_counts" in compact
    assert compact["pending_recommendations"] == 1
