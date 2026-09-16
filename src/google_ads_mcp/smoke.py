"""Exercise the MCP server the way a host would (no live Ads API required)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError

from google_ads_mcp.server import create_server
from google_ads_mcp.store import reset_store_for_tests

EXPECTED_TOOLS = {
    "list_accessible_customers",
    "search",
    "get_resource_metadata",
    "list_campaigns",
    "get_campaign",
    "get_campaign_dashboard",
    "set_campaign_status",
    "update_campaign_budget",
    "create_search_campaign",
    "create_display_campaign",
    "create_pmax_campaign",
    "upload_image_asset",
    "update_responsive_search_ad",
    "add_campaign_locations",
    "add_campaign_languages",
    "add_asset_group_text",
    "get_local_audit",
    "get_search_term_insights",
    "get_impression_share_summary",
}


def _payload(result: Any) -> Any:
    if getattr(result, "structured_content", None) is not None:
        return result.structured_content
    texts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            return texts[0]
    return texts


async def run_session(client: Client) -> dict[str, Any]:
    report: dict[str, Any] = {"ok": True, "steps": []}

    def record(name: str, **extra: Any) -> None:
        report["steps"].append({"step": name, **extra})

    tools = {tool.name for tool in await client.list_tools()}
    missing = sorted(EXPECTED_TOOLS - tools)
    record("list_tools", count=len(tools), missing=missing, sample=sorted(tools)[:8])
    if missing:
        report["ok"] = False

    preview = _payload(
        await client.call_tool(
            "create_search_campaign",
            {
                "customer_id": "123-456-7890",
                "name": "Smoke Search",
                "daily_budget": 15,
                "final_url": "https://example.com",
                "headlines": ["Buy now", "Spring sale", "Free ship"],
                "descriptions": ["Shop the new drop.", "Paused until review."],
                "keywords": ["running shoes"],
                "dry_run": True,
            },
        )
    )
    token = preview.get("confirm_token") if isinstance(preview, dict) else None
    record(
        "create_search_campaign_preview",
        status=preview.get("status") if isinstance(preview, dict) else None,
        has_token=bool(token),
        paused="PAUSED" in str(preview),
    )
    if not (isinstance(preview, dict) and preview.get("status") == "preview" and token):
        report["ok"] = False

    status_preview = _payload(
        await client.call_tool(
            "set_campaign_status",
            {
                "customer_id": "1234567890",
                "campaign_id": "111",
                "status": "PAUSED",
                "dry_run": True,
            },
        )
    )
    record(
        "set_campaign_status_preview",
        status=status_preview.get("status") if isinstance(status_preview, dict) else None,
    )

    try:
        await client.call_tool(
            "set_campaign_status",
            {
                "customer_id": "1234567890",
                "campaign_id": "111",
                "status": "PAUSED",
                "dry_run": False,
                "confirm_token": status_preview.get("confirm_token")
                if isinstance(status_preview, dict)
                else None,
            },
        )
        report["ok"] = False
        record("apply_without_write_flag", blocked=False)
    except ToolError as exc:
        blocked = "disabled" in str(exc).lower() or "WRITE_ENABLED" in str(exc)
        if not blocked:
            report["ok"] = False
        record("apply_without_write_flag", blocked=blocked, error=str(exc)[:240])

    audit = _payload(await client.call_tool("get_local_audit", {"limit": 5}))
    events = audit.get("events") if isinstance(audit, dict) else None
    record("get_local_audit", event_count=len(events or []), tools=[e.get("tool") for e in (events or [])])
    if not events:
        report["ok"] = False

    live_error = None
    try:
        await client.call_tool("list_accessible_customers", {})
        record("list_accessible_customers", reached_api=True)
    except ToolError as exc:
        live_error = str(exc)
        record("list_accessible_customers", reached_api=False, error=live_error[:240])
    report["live_api"] = live_error is None
    return report


def _isolate_ads_env() -> None:
    for key in (
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        "GOOGLE_ADS_CONFIGURATION_FILE_PATH",
        "GOOGLE_ADS_ADC_PATH",
        "GOOGLE_ADS_ALLOWED_CUSTOMER_IDS",
        "GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED",
    ):
        os.environ.pop(key, None)


async def smoke_inprocess(db_path: Path) -> dict[str, Any]:
    reset_store_for_tests()
    _isolate_ads_env()
    os.environ["GOOGLE_ADS_DISABLE_ENV_FILE"] = "1"
    os.environ["GOOGLE_ADS_MCP_DB"] = str(db_path)
    os.environ["GOOGLE_ADS_WRITE_ENABLED"] = "false"
    async with Client(create_server()) as client:
        report = await run_session(client)
    report["transport"] = "inprocess"
    return report


async def smoke_stdio(db_path: Path) -> dict[str, Any]:
    env = {
        **os.environ,
        "GOOGLE_ADS_MCP_DB": str(db_path),
        "GOOGLE_ADS_WRITE_ENABLED": "false",
        "GOOGLE_ADS_DISABLE_ENV_FILE": "1",
    }
    for key in (
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        "GOOGLE_ADS_CONFIGURATION_FILE_PATH",
        "GOOGLE_ADS_ADC_PATH",
        "GOOGLE_ADS_ALLOWED_CUSTOMER_IDS",
        "GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED",
    ):
        env.pop(key, None)
    transport = StdioTransport(
        command="uv",
        args=["run", "--directory", str(Path.cwd()), "google-ads-mcp"],
        env=env,
        cwd=str(Path.cwd()),
    )
    async with Client(transport) as client:
        report = await run_session(client)
    report["transport"] = "stdio"
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Smoke-test the Google Ads MCP server.")
    parser.add_argument("--stdio", action="store_true", help="Also launch via stdio (uv run google-ads-mcp).")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "smoke.duckdb"
        reports = [asyncio.run(smoke_inprocess(db))]
        if args.stdio:
            reports.append(asyncio.run(smoke_stdio(Path(tmp) / "smoke-stdio.duckdb")))
    print(json.dumps(reports, indent=2))
    if any(not item["ok"] for item in reports):
        raise SystemExit(1)
    print("\nMCP smoke OK. Live Ads API was not called (no credentials in this environment).")
