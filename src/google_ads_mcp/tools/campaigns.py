"""Read tools for campaigns, ad groups, ads, and keywords."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp.gaql import search
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.money import from_micros


def list_campaigns(
    customer_id: str,
    status: str | None = "ENABLED",
    limit: int = 100,
) -> dict[str, Any]:
    """List campaigns with status, channel, budget, and bidding strategy.

    status can be ENABLED, PAUSED, REMOVED, or ALL.
    """
    cid = clean_customer_id(customer_id)
    conditions = []
    if status and status.upper() != "ALL":
        conditions.append(f"campaign.status = '{status.upper()}'")
    query_conditions = " AND ".join(conditions) if conditions else "campaign.id > 0"
    rows = search(
        cid,
        "SELECT campaign.id, campaign.name, campaign.status, campaign.primary_status, "
        "campaign.advertising_channel_type, campaign.bidding_strategy_type, "
        "campaign_budget.id, campaign_budget.amount_micros, campaign.start_date_time, "
        "campaign.end_date_time FROM campaign "
        f"WHERE {query_conditions} ORDER BY campaign.name LIMIT {int(limit)}",
    )
    campaigns = []
    for row in rows:
        campaigns.append(
            {
                **row,
                "daily_budget": from_micros(row.get("campaign_budget.amount_micros")),
            }
        )
    return {"customer_id": cid, "count": len(campaigns), "campaigns": campaigns}


def get_campaign(customer_id: str, campaign_id: str) -> dict[str, Any]:
    """Get one campaign plus its budget and recent 7-day performance."""
    cid = clean_customer_id(customer_id)
    details = search(
        cid,
        "SELECT campaign.id, campaign.name, campaign.status, campaign.primary_status, "
        "campaign.primary_status_reasons, campaign.advertising_channel_type, "
        "campaign.bidding_strategy_type, campaign_budget.amount_micros, "
        "campaign.network_settings.target_google_search, campaign.start_date_time "
        f"FROM campaign WHERE campaign.id = {int(campaign_id)} LIMIT 1",
    )
    metrics = search(
        cid,
        "SELECT metrics.impressions, metrics.clicks, metrics.cost_micros, "
        "metrics.conversions, metrics.conversions_value, metrics.average_cpc "
        f"FROM campaign WHERE campaign.id = {int(campaign_id)} "
        "AND segments.date DURING LAST_7_DAYS",
    )
    return {
        "campaign": details[0] if details else None,
        "last_7_days": metrics[0] if metrics else None,
        "daily_budget": from_micros(details[0].get("campaign_budget.amount_micros")) if details else None,
    }


def list_ad_groups(customer_id: str, campaign_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    """List ad groups, optionally filtered to one campaign."""
    cid = clean_customer_id(customer_id)
    conditions = ["ad_group.status != 'REMOVED'"]
    if campaign_id:
        conditions.append(f"campaign.id = {int(campaign_id)}")
    rows = search(
        cid,
        "SELECT ad_group.id, ad_group.name, ad_group.status, ad_group.type, "
        "campaign.id, campaign.name FROM ad_group WHERE "
        + " AND ".join(conditions)
        + f" ORDER BY ad_group.name LIMIT {int(limit)}",
    )
    return {"count": len(rows), "ad_groups": rows}


def list_ads(customer_id: str, ad_group_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """List ads with type, status, and policy summary."""
    cid = clean_customer_id(customer_id)
    conditions = ["ad_group_ad.status != 'REMOVED'"]
    if ad_group_id:
        conditions.append(f"ad_group.id = {int(ad_group_id)}")
    rows = search(
        cid,
        "SELECT ad_group.id, ad_group_ad.ad.id, ad_group_ad.status, ad_group_ad.ad.type, "
        "ad_group_ad.ad.final_urls, ad_group_ad.policy_summary.approval_status "
        "FROM ad_group_ad WHERE "
        + " AND ".join(conditions)
        + f" LIMIT {int(limit)}",
    )
    return {"count": len(rows), "ads": rows}


def list_keywords(customer_id: str, ad_group_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    """List keywords with match type, status, and bid."""
    cid = clean_customer_id(customer_id)
    conditions = ["ad_group_criterion.type = 'KEYWORD'", "ad_group_criterion.status != 'REMOVED'"]
    if ad_group_id:
        conditions.append(f"ad_group.id = {int(ad_group_id)}")
    rows = search(
        cid,
        "SELECT ad_group.id, ad_group_criterion.criterion_id, ad_group_criterion.keyword.text, "
        "ad_group_criterion.keyword.match_type, ad_group_criterion.status, "
        "ad_group_criterion.cpc_bid_micros FROM ad_group_criterion WHERE "
        + " AND ".join(conditions)
        + f" LIMIT {int(limit)}",
    )
    return {"count": len(rows), "keywords": rows}


def register(mcp: FastMCP) -> None:
    mcp.tool(list_campaigns)
    mcp.tool(get_campaign)
    mcp.tool(list_ad_groups)
    mcp.tool(list_ads)
    mcp.tool(list_keywords)
