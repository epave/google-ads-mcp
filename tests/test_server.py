import asyncio

from google_ads_mcp.server import create_server


def test_create_server_registers_core_tools(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.delenv("GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED", raising=False)
    server = create_server()
    tools = {tool.name for tool in asyncio.run(server.list_tools(run_middleware=False))}
    expected = {
        "list_accessible_customers",
        "search",
        "get_resource_metadata",
        "get_campaign_dashboard",
        "set_campaign_status",
        "create_search_campaign",
        "create_display_campaign",
        "create_pmax_campaign",
        "upload_image_asset",
        "update_responsive_search_ad",
        "add_campaign_locations",
        "add_campaign_languages",
        "add_asset_group_text",
        "get_search_term_insights",
        "get_search_term_insight_terms",
        "get_impression_share_summary",
    }
    missing = expected - tools
    assert not missing, f"missing tools: {missing}"
    hidden = {
        "list_audience_insights_attributes",
        "generate_suggested_targeting_insights",
        "generate_audience_composition_insights",
        "generate_creator_insights",
    }
    assert not (hidden & tools)


def test_create_server_registers_audience_tools_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED", "true")
    server = create_server()
    tools = {tool.name for tool in asyncio.run(server.list_tools(run_middleware=False))}
    assert {
        "list_audience_insights_attributes",
        "generate_audience_composition_insights",
        "generate_suggested_targeting_insights",
    } <= tools
