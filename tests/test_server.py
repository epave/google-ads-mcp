import asyncio

from google_ads_mcp.server import create_server


def test_create_server_registers_core_tools() -> None:
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
    }
    missing = expected - tools
    assert not missing, f"missing tools: {missing}"
