from pathlib import Path

import pytest

from google_ads_mcp.store import reset_store_for_tests
from google_ads_mcp.tools.creates import (
    add_asset_group_text,
    add_campaign_languages,
    add_campaign_locations,
    add_keywords,
    create_ad_group,
    create_search_campaign,
    update_responsive_search_ad,
)


def _isolate_store(monkeypatch, tmp_path: Path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "false")
    monkeypatch.delenv("GOOGLE_ADS_ALLOWED_CUSTOMER_IDS", raising=False)


def test_search_create_preview(monkeypatch, tmp_path: Path) -> None:
    _isolate_store(monkeypatch, tmp_path)
    result = create_search_campaign(
        customer_id="1234567890",
        name="Spring shoes",
        daily_budget=25,
        final_url="https://example.com",
        headlines=["Buy shoes", "Spring sale", "Free shipping"],
        descriptions=["Shop the new drop.", "Limited time offer."],
        keywords=["running shoes"],
        dry_run=True,
    )
    assert result["status"] == "preview"
    assert result["confirm_token"]
    assert "PAUSED" in result["description"]


def test_update_rsa_and_criteria_previews(monkeypatch, tmp_path: Path) -> None:
    _isolate_store(monkeypatch, tmp_path)
    rsa = update_responsive_search_ad(
        customer_id="1234567890",
        ad_id="11",
        headlines=["H1", "H2", "H3"],
        descriptions=["D1", "D2"],
        dry_run=True,
    )
    assert rsa["status"] == "preview"
    geo = add_campaign_locations(
        customer_id="1234567890",
        campaign_id="22",
        geo_target_constant_ids=["2840"],
        dry_run=True,
    )
    assert geo["status"] == "preview"
    lang = add_campaign_languages(
        customer_id="1234567890",
        campaign_id="22",
        language_constant_ids=["1000"],
        dry_run=True,
    )
    assert lang["status"] == "preview"
    assets = add_asset_group_text(
        customer_id="1234567890",
        asset_group_id="33",
        headlines=["Another headline"],
        dry_run=True,
    )
    assert assets["status"] == "preview"


def test_create_ad_group_and_keywords_default_paused(monkeypatch, tmp_path: Path) -> None:
    _isolate_store(monkeypatch, tmp_path)
    group = create_ad_group(
        customer_id="1234567890",
        campaign_id="22",
        name="Second group",
        dry_run=True,
    )
    assert group["status"] == "preview"
    assert group["args"]["status"] == "PAUSED"
    assert "PAUSED" in group["description"]
    keywords = add_keywords(
        customer_id="1234567890",
        ad_group_id="33",
        keywords=["trail running shoes"],
        dry_run=True,
    )
    assert keywords["status"] == "preview"
    assert keywords["args"]["status"] == "PAUSED"


def test_update_rsa_rejects_overlong_copy(monkeypatch, tmp_path: Path) -> None:
    _isolate_store(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="exceeds 30 characters"):
        update_responsive_search_ad(
            customer_id="1234567890",
            ad_id="11",
            headlines=["This headline is way too long for RSA", "H2", "H3"],
            descriptions=["D1", "D2"],
            dry_run=True,
        )
