"""Tests for rich recommendations and campaign hints."""

from __future__ import annotations

from google_ads_mcp.tools import insights as insights_mod


def test_get_recommendations_normalized(monkeypatch) -> None:
    def fake_search(cid, query, login_customer_id=None):
        assert "recommendation.keyword_recommendation.keyword.text" in query
        assert "campaign.id" not in query or "recommendation.campaign" in query
        assert "structured_snippet_asset_recommendation" not in query
        return [
            {
                "recommendation.resource_name": "customers/1/recommendations/1",
                "recommendation.type": "KEYWORD",
                "recommendation.campaign": "customers/1/campaigns/111",
                "recommendation.keyword_recommendation.keyword.text": "running shoes",
                "recommendation.keyword_recommendation.keyword.match_type": "BROAD",
                "recommendation.impact.base_metrics.clicks": 10,
                "recommendation.impact.potential_metrics.clicks": 20,
            }
        ]

    monkeypatch.setattr(insights_mod, "search", fake_search)
    result = insights_mod.get_recommendations("1234567890", campaign_id="111", types=["KEYWORD"])
    assert result["origin"] == "GOOGLE_API"
    assert "warning" in result
    rec = result["recommendations"][0]
    assert rec["origin"] == "GOOGLE_API"
    assert rec["details"]["keyword"]["text"] == "running shoes"
    assert rec["impact"]["potential"]["clicks"] == 20


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
