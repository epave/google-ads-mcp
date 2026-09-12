"""Search terms, change history, recommendations, and local audit."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp.gaql import search
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.store import get_store


def get_search_terms(customer_id: str, campaign_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Top search terms for the last 7 days."""
    cid = clean_customer_id(customer_id)
    conditions = ["segments.date DURING LAST_7_DAYS"]
    if campaign_id:
        conditions.append(f"campaign.id = {int(campaign_id)}")
    rows = search(
        cid,
        "SELECT search_term_view.search_term, campaign.id, campaign.name, "
        "metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions "
        "FROM search_term_view WHERE "
        + " AND ".join(conditions)
        + f" ORDER BY metrics.clicks DESC LIMIT {int(limit)}",
    )
    return {"count": len(rows), "search_terms": rows}


def get_change_events(customer_id: str, limit: int = 50) -> dict[str, Any]:
    """Recent account change events (last 7 days)."""
    cid = clean_customer_id(customer_id)
    rows = search(
        cid,
        "SELECT change_event.change_date_time, change_event.user_email, "
        "change_event.client_type, change_event.change_resource_type, "
        "change_event.resource_change_operation, change_event.resource_name "
        "FROM change_event WHERE change_event.change_date_time DURING LAST_7_DAYS "
        f"ORDER BY change_event.change_date_time DESC LIMIT {int(limit)}",
    )
    return {"count": len(rows), "changes": rows}


def get_recommendations(customer_id: str, limit: int = 25) -> dict[str, Any]:
    """Google Ads optimization recommendations that are still pending."""
    cid = clean_customer_id(customer_id)
    rows = search(
        cid,
        "SELECT recommendation.resource_name, recommendation.type, recommendation.campaign, "
        "recommendation.impact FROM recommendation WHERE recommendation.dismissed = FALSE "
        f"LIMIT {int(limit)}",
    )
    return {"count": len(rows), "recommendations": rows}


def get_local_audit(limit: int = 20) -> dict[str, Any]:
    """Read recent mutations and previews stored in the local DuckDB 2.0 audit log."""
    return {"events": get_store().list_recent_audit(limit=limit)}


def register(mcp: FastMCP) -> None:
    mcp.tool(get_search_terms)
    mcp.tool(get_change_events)
    mcp.tool(get_recommendations)
    mcp.tool(get_local_audit)
