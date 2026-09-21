"""Tests for rich recommendations and campaign hints."""

from __future__ import annotations

from google_ads_mcp.tools import insights as insights_mod

# Nested paths under MESSAGE fields are not documented as selectable in v25.
_FORBIDDEN_NESTED = (
    "keyword_recommendation.keyword.text",
    "recommended_campaign_callout_assets",
    "recommended_campaign_sitelink_assets",
    "impact.base_metrics",
    "structured_snippet_asset_recommendation",
)


def _assert_v25_selectable_fields(query: str) -> None:
    assert "recommendation.keyword_recommendation" in query
    assert "recommendation.impact," in query or "recommendation.impact " in query
    for bad in _FORBIDDEN_NESTED:
        assert bad not in query, query


def test_get_recommendations_normalized(monkeypatch) -> None:
    queries: list[str] = []

    def fake_search(cid, query, login_customer_id=None):
        queries.append(query)
        _assert_v25_selectable_fields(query)
        assert "recommendation.campaigns" in query
        assert " OR " not in query
        if "recommendation.campaign =" in query:
            return [
                {
                    "recommendation.resource_name": "customers/1/recommendations/1",
                    "recommendation.type": "KEYWORD",
                    "recommendation.campaign": "customers/1/campaigns/111",
                    "recommendation.campaigns": [],
                    "recommendation.keyword_recommendation": {
                        "keyword": {"text": "running shoes", "match_type": "BROAD"},
                        "recommended_cpc_bid_micros": "1500000",
                        "search_terms": [],
                    },
                    "recommendation.impact": {
                        "base_metrics": {"clicks": 10},
                        "potential_metrics": {"clicks": 20},
                    },
                }
            ]
        return []

    monkeypatch.setattr(insights_mod, "search", fake_search)
    result = insights_mod.get_recommendations("1234567890", campaign_id="111", types=["KEYWORD"])
    assert result["origin"] == "GOOGLE_API"
    assert "warning" in result
    assert len(queries) == 2
    assert any("CONTAINS ANY" in q for q in queries)
    rec = result["recommendations"][0]
    assert rec["origin"] == "GOOGLE_API"
    assert rec["details"]["keyword"]["text"] == "running shoes"
    assert rec["details"]["keyword"]["recommended_cpc_bid_micros"] == 1_500_000
    assert rec["impact"]["potential"]["clicks"] == 20
    assert rec["campaigns"] == ["customers/1/campaigns/111"]


def test_get_recommendations_budget_uses_campaigns(monkeypatch) -> None:
    queries: list[str] = []

    def fake_search(cid, query, login_customer_id=None):
        queries.append(query)
        _assert_v25_selectable_fields(query)
        assert " OR " not in query
        if "CONTAINS ANY" in query:
            return [
                {
                    "recommendation.resource_name": "customers/1/recommendations/2",
                    "recommendation.type": "CAMPAIGN_BUDGET",
                    "recommendation.campaign": None,
                    "recommendation.campaigns": [
                        "customers/1/campaigns/111",
                        "customers/1/campaigns/222",
                    ],
                    "recommendation.campaign_budget_recommendation": {
                        "recommended_budget_amount_micros": "9000000",
                        "budget_options": [],
                    },
                }
            ]
        return []

    monkeypatch.setattr(insights_mod, "search", fake_search)
    result = insights_mod.get_recommendations(
        "1234567890", campaign_id="111", types=["CAMPAIGN_BUDGET"]
    )
    assert len(queries) == 2
    rec = result["recommendations"][0]
    assert rec["type"] == "CAMPAIGN_BUDGET"
    assert rec["campaigns"] == [
        "customers/1/campaigns/111",
        "customers/1/campaigns/222",
    ]
    assert rec["details"]["budget"]["recommended_budget_amount_micros"] == 9_000_000


def test_get_recommendations_ignores_unset_budget_on_keyword(monkeypatch) -> None:
    """Budget MESSAGE on a KEYWORD row must not invent budget details."""

    def fake_search(cid, query, login_customer_id=None):
        if "recommendation.campaign =" in query:
            return [
                {
                    "recommendation.resource_name": "customers/1/recommendations/1",
                    "recommendation.type": "KEYWORD",
                    "recommendation.campaign": "customers/1/campaigns/111",
                    "recommendation.campaigns": [],
                    "recommendation.keyword_recommendation": {
                        "keyword": {"text": "shoes", "match_type": "BROAD"},
                        "search_terms": [],
                    },
                    "recommendation.campaign_budget_recommendation": {
                        "recommended_budget_amount_micros": "0",
                        "budget_options": [],
                    },
                    "recommendation.callout_asset_recommendation": {
                        "recommended_campaign_callout_assets": [],
                        "recommended_customer_callout_assets": [],
                    },
                }
            ]
        return []

    monkeypatch.setattr(insights_mod, "search", fake_search)
    result = insights_mod.get_recommendations("1234567890", campaign_id="111")
    details = result["recommendations"][0]["details"]
    assert "budget" not in details
    assert "callout_assets" not in details
    assert details["keyword"]["text"] == "shoes"


def test_get_recommendations_budget_zero_is_kept_for_budget_type(monkeypatch) -> None:
    def fake_search(cid, query, login_customer_id=None):
        return [
            {
                "recommendation.resource_name": "customers/1/recommendations/3",
                "recommendation.type": "CAMPAIGN_BUDGET",
                "recommendation.campaign": "customers/1/campaigns/111",
                "recommendation.campaign_budget_recommendation": {
                    "recommended_budget_amount_micros": "0",
                    "budget_options": [],
                },
            }
        ]

    monkeypatch.setattr(insights_mod, "search", fake_search)
    result = insights_mod.get_recommendations("1234567890")
    assert result["recommendations"][0]["details"]["budget"][
        "recommended_budget_amount_micros"
    ] == 0


def test_get_recommendations_dedupes_across_queries(monkeypatch) -> None:
    shared = {
        "recommendation.resource_name": "customers/1/recommendations/9",
        "recommendation.type": "KEYWORD",
        "recommendation.campaign": "customers/1/campaigns/111",
        "recommendation.campaigns": ["customers/1/campaigns/111"],
    }

    def fake_search(cid, query, login_customer_id=None):
        return [shared]

    monkeypatch.setattr(insights_mod, "search", fake_search)
    result = insights_mod.get_recommendations("1234567890", campaign_id="111")
    assert result["count"] == 1


def test_get_campaign_hints_propagates_error(monkeypatch) -> None:
    def fake_build(customer_id, campaign_id, login_customer_id=None, search_fn=None):
        return {
            "customer_id": "1234567890",
            "campaign_id": "999",
            "error": "Campaign 999 not found",
            "findings": [],
            "finding_counts": {},
        }

    import google_ads_mcp.diagnostics as diag_mod

    monkeypatch.setattr(diag_mod, "build_campaign_diagnostics", fake_build)
    result = insights_mod.get_campaign_hints("1234567890", "999")
    assert result["error"] == "Campaign 999 not found"
    assert result["findings"] == []


def test_get_campaign_hints_separates_origins(monkeypatch) -> None:
    def fake_build(customer_id, campaign_id, login_customer_id=None, search_fn=None):
        return {
            "customer_id": "1234567890",
            "campaign_id": "111",
            "findings": [
                {
                    "severity": "opportunity",
                    "code": "MISSING_CALLOUTS",
                    "origin": "LOCAL_DIAGNOSTIC",
                    "message": "no callouts",
                    "evidence": {},
                },
                {
                    "severity": "opportunity",
                    "code": "GOOGLE_REC_KEYWORD",
                    "origin": "GOOGLE_API",
                    "message": "add keyword",
                    "evidence": {},
                },
            ],
            "finding_counts": {"opportunity": 2},
        }

    import google_ads_mcp.diagnostics as diag_mod

    monkeypatch.setattr(diag_mod, "build_campaign_diagnostics", fake_build)
    result = insights_mod.get_campaign_hints("1234567890", "111")
    assert result["local_diagnostics"][0]["origin"] == "LOCAL_DIAGNOSTIC"
    assert result["google_recommendations"][0]["origin"] == "GOOGLE_API"
    assert result["local_diagnostics"][0]["code"] != "GOOGLE_API"
    assert "error" not in result
