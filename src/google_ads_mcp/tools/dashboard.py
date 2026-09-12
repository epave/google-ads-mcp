"""MCP-native dashboard snapshot of running campaigns."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp.gaql import search
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.money import format_money, from_micros
from google_ads_mcp.store import get_store


def _index_by_campaign(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    for row in rows:
        campaign_id = row.get("campaign.id")
        if campaign_id is None:
            continue
        indexed[int(campaign_id)] = row
    return indexed


def _delta(current: float, previous: float | None) -> float | None:
    if previous is None:
        return None
    return round(current - previous, 2)


def get_campaign_dashboard(
    customer_id: str,
    include_paused: bool = False,
    persist_snapshot: bool = True,
) -> dict[str, Any]:
    """Compact live dashboard of campaigns for an agent to read and act on.

    Returns status, daily budget, today and last-7-day spend/clicks/conversions,
    CPA, ROAS, serving alerts, and deltas versus the previous local snapshot.
    This is an MCP tool, not a web UI.
    """
    cid = clean_customer_id(customer_id)
    account = search(
        cid,
        "SELECT customer.id, customer.descriptive_name, customer.manager FROM customer LIMIT 1",
    )
    if account and account[0].get("customer.manager"):
        name = account[0].get("customer.descriptive_name") or cid
        return {
            "customer_id": cid,
            "manager": True,
            "name": name,
            "campaign_count": 0,
            "totals": {"spend_today": 0, "spend_7d": 0, "clicks_7d": 0, "conversions_7d": 0},
            "alerts": [
                f"{name} is a manager (MCC) account. Call get_campaign_dashboard on a client customer_id."
            ],
            "campaigns": [],
            "markdown": (
                f"{name} is a manager account — Google Ads will not return campaign metrics here. "
                "Use list_accessible_customers and dashboard a non-manager customer."
            ),
        }
    status_filter = "campaign.status IN ('ENABLED', 'PAUSED')" if include_paused else "campaign.status = 'ENABLED'"
    catalog = search(
        cid,
        "SELECT campaign.id, campaign.name, campaign.status, campaign.primary_status, "
        "campaign.primary_status_reasons, campaign.advertising_channel_type, "
        "campaign_budget.amount_micros FROM campaign WHERE "
        f"{status_filter} ORDER BY campaign.name",
    )
    today = _index_by_campaign(
        search(
            cid,
            "SELECT campaign.id, metrics.cost_micros, metrics.clicks, metrics.impressions, "
            "metrics.conversions, metrics.conversions_value FROM campaign "
            f"WHERE {status_filter} AND segments.date DURING TODAY",
        )
    )
    week = _index_by_campaign(
        search(
            cid,
            "SELECT campaign.id, metrics.cost_micros, metrics.clicks, metrics.impressions, "
            "metrics.conversions, metrics.conversions_value FROM campaign "
            f"WHERE {status_filter} AND segments.date DURING LAST_7_DAYS",
        )
    )

    store = get_store()
    previous = store.previous_dashboard_snapshot(cid)
    prev_by_id = {}
    if previous:
        for item in previous.get("campaigns", []):
            prev_by_id[int(item["campaign_id"])] = item

    campaigns: list[dict[str, Any]] = []
    alerts: list[str] = []
    markdown_lines = [
        "| Campaign | Type | Status | Budget/day | Spend today | Spend 7d | Clicks 7d | Conv 7d | CPA 7d |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    for row in catalog:
        campaign_id = int(row["campaign.id"])
        today_m = today.get(campaign_id, {})
        week_m = week.get(campaign_id, {})
        spend_today = from_micros(today_m.get("metrics.cost_micros"))
        spend_7d = from_micros(week_m.get("metrics.cost_micros"))
        clicks_7d = float(week_m.get("metrics.clicks") or 0)
        conv_7d = float(week_m.get("metrics.conversions") or 0)
        value_7d = float(week_m.get("metrics.conversions_value") or 0)
        cpa = (spend_7d / conv_7d) if conv_7d else None
        roas = (value_7d / spend_7d) if spend_7d else None
        budget = from_micros(row.get("campaign_budget.amount_micros"))
        reasons = row.get("campaign.primary_status_reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        primary = row.get("campaign.primary_status")
        if primary and primary not in {"ELIGIBLE", "ELIGIBLE_LIMITED", None} and str(primary) != "ELIGIBLE":
            if str(primary) not in {"UNSPECIFIED", "UNKNOWN"}:
                alerts.append(f"{row['campaign.name']}: {primary}")
        if reasons:
            alerts.append(f"{row['campaign.name']}: {', '.join(str(r) for r in reasons)}")
        if budget and spend_today >= budget:
            alerts.append(f"{row['campaign.name']}: spent full daily budget today")

        prev = prev_by_id.get(campaign_id)
        item = {
            "campaign_id": campaign_id,
            "name": row.get("campaign.name"),
            "status": row.get("campaign.status"),
            "primary_status": primary,
            "channel": row.get("campaign.advertising_channel_type"),
            "daily_budget": budget,
            "spend_today": spend_today,
            "spend_7d": spend_7d,
            "clicks_7d": clicks_7d,
            "impressions_7d": float(week_m.get("metrics.impressions") or 0),
            "conversions_7d": conv_7d,
            "cpa_7d": round(cpa, 2) if cpa is not None else None,
            "roas_7d": round(roas, 2) if roas is not None else None,
            "spend_7d_delta": _delta(spend_7d, prev.get("spend_7d") if prev else None),
        }
        campaigns.append(item)
        markdown_lines.append(
            "| {name} | {channel} | {status} | {budget} | {today} | {week} | {clicks} | {conv} | {cpa} |".format(
                name=item["name"],
                channel=item["channel"],
                status=item["status"],
                budget=format_money(int(budget * 1_000_000)),
                today=format_money(int(spend_today * 1_000_000)),
                week=format_money(int(spend_7d * 1_000_000)),
                clicks=int(clicks_7d),
                conv=round(conv_7d, 2),
                cpa="—" if item["cpa_7d"] is None else f"{item['cpa_7d']:.2f}",
            )
        )

    payload = {
        "customer_id": cid,
        "campaign_count": len(campaigns),
        "totals": {
            "spend_today": round(sum(c["spend_today"] for c in campaigns), 2),
            "spend_7d": round(sum(c["spend_7d"] for c in campaigns), 2),
            "clicks_7d": int(sum(c["clicks_7d"] for c in campaigns)),
            "conversions_7d": round(sum(c["conversions_7d"] for c in campaigns), 2),
        },
        "alerts": alerts,
        "campaigns": campaigns,
        "markdown": "\n".join(markdown_lines),
    }
    if persist_snapshot:
        store.save_dashboard_snapshot(cid, payload)
    return payload


def register(mcp: FastMCP) -> None:
    mcp.tool(get_campaign_dashboard)
