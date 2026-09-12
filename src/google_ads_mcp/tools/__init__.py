"""Register all MCP tools."""

from __future__ import annotations

from fastmcp import FastMCP

from google_ads_mcp.tools import (
    accounts,
    assets,
    campaigns,
    creates,
    dashboard,
    insights,
    query,
    writes,
)


def register_all(mcp: FastMCP) -> None:
    accounts.register(mcp)
    query.register(mcp)
    campaigns.register(mcp)
    dashboard.register(mcp)
    insights.register(mcp)
    writes.register(mcp)
    creates.register(mcp)
    assets.register(mcp)
