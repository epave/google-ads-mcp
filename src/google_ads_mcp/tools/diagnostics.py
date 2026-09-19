"""MCP tools for consolidated campaign diagnostics."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp.diagnostics import build_campaign_diagnostics
from google_ads_mcp.ids import clean_customer_id


def get_campaign_diagnostics(
    customer_id: str,
    campaign_id: str,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """One-call campaign health: status, performance, IS, ads, keywords, assets, findings.

    Findings use severity critical/warning/opportunity/informational and origin
    GOOGLE_API (pending Google recommendations) or LOCAL_DIAGNOSTIC (observed issues).
    """
    cid = clean_customer_id(customer_id)
    return build_campaign_diagnostics(
        cid, campaign_id, login_customer_id=login_customer_id
    )


def register(mcp: FastMCP) -> None:
    mcp.tool(get_campaign_diagnostics)
