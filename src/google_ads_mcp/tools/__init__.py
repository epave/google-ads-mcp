"""Register all MCP tools."""

from __future__ import annotations

from fastmcp import FastMCP

from google_ads_mcp.tools import (
    accounts,
    assets,
    audiences,
    campaigns,
    creates,
    dashboard,
    demand_gen,
    diagnostics,
    insights,
    query,
    server_info,
    writes,
)


def register_all(mcp: FastMCP) -> None:
    accounts.register(mcp)
    query.register(mcp)
    campaigns.register(mcp)
    dashboard.register(mcp)
    diagnostics.register(mcp)
    insights.register(mcp)
    audiences.register(mcp)
    demand_gen.register(mcp)
    writes.register(mcp)
    creates.register(mcp)
    assets.register(mcp)
    # Register last so get_server_info can list every tool name.
    server_info.register(mcp)
