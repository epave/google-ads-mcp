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
    login_customer_id: str | None = None,
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
        login_customer_id=login_customer_id,
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
        login_customer_id=login_customer_id,
    )
    campaign_ids = [str(int(row["campaign.id"])) for row in catalog if row.get("campaign.id") is not None]
    if not campaign_ids:
        payload = {
            "customer_id": cid,
            "campaign_count": 0,
            "totals": {"spend_today": 0, "spend_7d": 0, "clicks_7d": 0, "conversions_7d": 0},
            "alerts": [],
            "campaigns": [],
            "markdown": (
                "| Campaign | Type | Status | Budget/day | Spend today | Spend 7d | "
                "Clicks 7d | Conv 7d | CPA 7d |\n"
                "|---|---|---|---:|---:|---:|---:|---:|---:|"
            ),
        }
        if persist_snapshot:
            store = get_store()
            store.save_dashboard_snapshot(cid, payload)
        return payload

    # Scope secondary queries by catalog IDs so they never filter on campaign.status
    # without selecting it (EXPECTED_REFERENCED_FIELD_IN_SELECT_CLAUSE).
    id_filter = "campaign.id IN (" + ", ".join(campaign_ids) + ")"
    today = _index_by_campaign(
        search(
            cid,
            "SELECT campaign.id, metrics.cost_micros, metrics.clicks, "
            "metrics.impressions, metrics.conversions, metrics.conversions_value FROM campaign "
            f"WHERE {id_filter} AND segments.date DURING TODAY",
            login_customer_id=login_customer_id,
        )
    )
    week = _index_by_campaign(
        search(
            cid,
            "SELECT campaign.id, metrics.cost_micros, metrics.clicks, "
            "metrics.impressions, metrics.conversions, metrics.conversions_value FROM campaign "
            f"WHERE {id_filter} AND segments.date DURING LAST_7_DAYS",
            login_customer_id=login_customer_id,
        )
    )
    impression_share = _index_by_campaign(
        search(
            cid,
            "SELECT campaign.id, metrics.search_budget_lost_impression_share, "
            "metrics.search_rank_lost_impression_share FROM campaign "
            f"WHERE {id_filter} AND segments.date DURING LAST_7_DAYS",
            login_customer_id=login_customer_id,
        )
    )
    asset_rows = search(
        cid,
        "SELECT campaign.id, campaign_asset.field_type FROM campaign_asset "
        f"WHERE {id_filter} "
        "AND campaign_asset.status != 'REMOVED' "
        "AND campaign_asset.field_type IN ('CALLOUT', 'STRUCTURED_SNIPPET', 'SITELINK')",
        login_customer_id=login_customer_id,
    )
    asset_counts: dict[int, dict[str, int]] = {}
    for row in asset_rows:
        cid_key = int(row["campaign.id"])
        bucket = asset_counts.setdefault(
            cid_key, {"callouts": 0, "structured_snippets": 0, "sitelinks": 0}
        )
        ft = str(row.get("campaign_asset.field_type") or "")
        if ft == "CALLOUT":
            bucket["callouts"] += 1
        elif ft == "STRUCTURED_SNIPPET":
            bucket["structured_snippets"] += 1
        elif ft == "SITELINK":
            bucket["sitelinks"] += 1

    rec_rows = search(
        cid,
        "SELECT recommendation.campaign, recommendation.campaigns, recommendation.type "
        "FROM recommendation WHERE recommendation.dismissed = FALSE",
        login_customer_id=login_customer_id,
    )
    rec_counts: dict[int, int] = {}
    for row in rec_rows:
        camp_rns: list[str] = []
        singular = row.get("recommendation.campaign")
        if singular:
            camp_rns.append(str(singular))
        repeated = row.get("recommendation.campaigns")
        if isinstance(repeated, (list, tuple)):
            camp_rns.extend(str(item) for item in repeated if item)
        elif repeated:
            camp_rns.append(str(repeated))
        seen_ids: set[int] = set()
        for camp_rn in camp_rns:
            if "/campaigns/" not in camp_rn:
                continue
            try:
                rid = int(camp_rn.rsplit("/", 1)[-1])
            except ValueError:
                continue
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            rec_counts[rid] = rec_counts.get(rid, 0) + 1

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
        spend_today_micros = today_m.get("metrics.cost_micros")
        spend_7d_micros = week_m.get("metrics.cost_micros")
        budget_micros = row.get("campaign_budget.amount_micros")
        spend_today = from_micros(spend_today_micros)
        spend_7d = from_micros(spend_7d_micros)
        clicks_7d = float(week_m.get("metrics.clicks") or 0)
        conv_7d = float(week_m.get("metrics.conversions") or 0)
        impressions_7d = float(week_m.get("metrics.impressions") or 0)
        value_7d = float(week_m.get("metrics.conversions_value") or 0)
        cpa = (spend_7d / conv_7d) if conv_7d else None
        roas = (value_7d / spend_7d) if spend_7d else None
        ctr_7d = (clicks_7d / impressions_7d) if impressions_7d else None
        cpc_7d = (spend_7d / clicks_7d) if clicks_7d else None
        budget = from_micros(budget_micros)
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

        is_row = impression_share.get(campaign_id, {})
        assets = asset_counts.get(
            campaign_id, {"callouts": 0, "structured_snippets": 0, "sitelinks": 0}
        )
        pending_recs = rec_counts.get(campaign_id, 0)

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
            "impressions_7d": impressions_7d,
            "conversions_7d": conv_7d,
            "ctr_7d": round(ctr_7d, 4) if ctr_7d is not None else None,
            "cpc_7d": round(cpc_7d, 2) if cpc_7d is not None else None,
            "cpa_7d": round(cpa, 2) if cpa is not None else None,
            "roas_7d": round(roas, 2) if roas is not None else None,
            "spend_7d_delta": _delta(spend_7d, prev.get("spend_7d") if prev else None),
            "lost_to_budget": is_row.get("metrics.search_budget_lost_impression_share"),
            "lost_to_rank": is_row.get("metrics.search_rank_lost_impression_share"),
            "asset_counts": assets,
            "pending_recommendations": pending_recs,
        }
        campaigns.append(item)
        markdown_lines.append(
            "| {name} | {channel} | {status} | {budget} | {today} | {week} | {clicks} | {conv} | {cpa} |".format(
                name=item["name"],
                channel=item["channel"],
                status=item["status"],
                budget=format_money(budget_micros),
                today=format_money(spend_today_micros),
                week=format_money(spend_7d_micros),
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
