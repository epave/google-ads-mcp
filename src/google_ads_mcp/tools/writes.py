"""Pause/enable and budget/bid updates."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp.client import get_client, run_ads_call
from google_ads_mcp.gaql import search
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.money import from_micros, to_micros
from google_ads_mcp.mutate import apply_update_mask, status_enum
from google_ads_mcp.safety import SafetyGate, require_force_for_removed, with_login_arg
from google_ads_mcp.store import get_store


def _gate() -> SafetyGate:
    return SafetyGate()


def _maybe_preview(result: dict[str, Any]) -> dict[str, Any] | None:
    if result.get("status") == "preview":
        return result
    return None


def _status_args(
    extra: dict[str, Any],
    status: str,
    force: bool,
    login_customer_id: str | None,
) -> tuple[str, dict[str, Any]]:
    normalized = require_force_for_removed(status, force)
    return normalized, with_login_arg(
        {**extra, "status": normalized, "force": force}, login_customer_id
    )


def set_campaign_status(
    customer_id: str,
    campaign_id: str,
    status: str,
    dry_run: bool = True,
    confirm_token: str | None = None,
    force: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Set a campaign to ENABLED, PAUSED, or REMOVED.

    Defaults to dry_run. Re-call with the returned confirm_token to apply.
    Writes require GOOGLE_ADS_WRITE_ENABLED=true.
    REMOVED permanently deletes the campaign via CampaignOperation.remove and
    requires force=true. ENABLED/PAUSED update campaign.status.
    """
    cid = clean_customer_id(customer_id)
    status, args = _status_args({"campaign_id": str(campaign_id)}, status, force, login_customer_id)
    description = f"Set campaign {campaign_id} to {status}"
    auth = _gate().authorize_write(
        tool="set_campaign_status",
        customer_id=cid,
        args=args,
        description=description,
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if preview := _maybe_preview(auth):
        return preview
    client = get_client(login_customer_id)
    service = client.get_service("CampaignService")
    operation = client.get_type("CampaignOperation")
    resource_name = service.campaign_path(cid, campaign_id)
    if status == "REMOVED":
        operation.remove = resource_name
    else:
        campaign = operation.update
        campaign.resource_name = resource_name
        campaign.status = status_enum(client, "CampaignStatusEnum", status)
        apply_update_mask(client, operation, campaign)
    response = run_ads_call(service.mutate_campaigns, customer_id=cid, operations=[operation])
    resource_name = response.results[0].resource_name
    get_store().record_audit(
        tool="set_campaign_status",
        action="apply",
        customer_id=cid,
        payload={"campaign_id": campaign_id, "status": status, "resource_name": resource_name},
    )
    return {"status": "applied", "resource_name": resource_name, "campaign_status": status}


def set_ad_group_status(
    customer_id: str,
    ad_group_id: str,
    status: str,
    dry_run: bool = True,
    confirm_token: str | None = None,
    force: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Set an ad group to ENABLED, PAUSED, or REMOVED.

    REMOVED permanently deletes the ad group and requires force=true.
    """
    cid = clean_customer_id(customer_id)
    status, args = _status_args({"ad_group_id": str(ad_group_id)}, status, force, login_customer_id)
    description = f"Set ad group {ad_group_id} to {status}"
    auth = _gate().authorize_write(
        tool="set_ad_group_status",
        customer_id=cid,
        args=args,
        description=description,
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if preview := _maybe_preview(auth):
        return preview
    client = get_client(login_customer_id)
    service = client.get_service("AdGroupService")
    operation = client.get_type("AdGroupOperation")
    ad_group = operation.update
    ad_group.resource_name = service.ad_group_path(cid, ad_group_id)
    ad_group.status = status_enum(client, "AdGroupStatusEnum", status)
    apply_update_mask(client, operation, ad_group)
    response = run_ads_call(service.mutate_ad_groups, customer_id=cid, operations=[operation])
    resource_name = response.results[0].resource_name
    get_store().record_audit(
        tool="set_ad_group_status",
        action="apply",
        customer_id=cid,
        payload={"ad_group_id": ad_group_id, "status": status},
    )
    return {"status": "applied", "resource_name": resource_name}


def set_ad_status(
    customer_id: str,
    ad_group_id: str,
    ad_id: str,
    status: str,
    dry_run: bool = True,
    confirm_token: str | None = None,
    force: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Set an ad to ENABLED, PAUSED, or REMOVED.

    REMOVED permanently deletes the ad and requires force=true.
    """
    cid = clean_customer_id(customer_id)
    status, args = _status_args(
        {"ad_group_id": str(ad_group_id), "ad_id": str(ad_id)},
        status,
        force,
        login_customer_id,
    )
    auth = _gate().authorize_write(
        tool="set_ad_status",
        customer_id=cid,
        args=args,
        description=f"Set ad {ad_id} to {status}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if preview := _maybe_preview(auth):
        return preview
    client = get_client(login_customer_id)
    service = client.get_service("AdGroupAdService")
    operation = client.get_type("AdGroupAdOperation")
    ad = operation.update
    ad.resource_name = service.ad_group_ad_path(cid, ad_group_id, ad_id)
    ad.status = status_enum(client, "AdGroupAdStatusEnum", status)
    apply_update_mask(client, operation, ad)
    response = run_ads_call(service.mutate_ad_group_ads, customer_id=cid, operations=[operation])
    get_store().record_audit(
        tool="set_ad_status",
        action="apply",
        customer_id=cid,
        payload={"ad_id": ad_id, "status": status},
    )
    return {"status": "applied", "resource_name": response.results[0].resource_name}


def set_keyword_status(
    customer_id: str,
    ad_group_id: str,
    criterion_id: str,
    status: str,
    dry_run: bool = True,
    confirm_token: str | None = None,
    force: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Set a keyword criterion to ENABLED, PAUSED, or REMOVED.

    REMOVED permanently deletes the keyword and requires force=true.
    """
    cid = clean_customer_id(customer_id)
    status, args = _status_args(
        {"ad_group_id": str(ad_group_id), "criterion_id": str(criterion_id)},
        status,
        force,
        login_customer_id,
    )
    auth = _gate().authorize_write(
        tool="set_keyword_status",
        customer_id=cid,
        args=args,
        description=f"Set keyword {criterion_id} to {status}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if preview := _maybe_preview(auth):
        return preview
    client = get_client(login_customer_id)
    service = client.get_service("AdGroupCriterionService")
    operation = client.get_type("AdGroupCriterionOperation")
    criterion = operation.update
    criterion.resource_name = service.ad_group_criterion_path(cid, ad_group_id, criterion_id)
    criterion.status = status_enum(client, "AdGroupCriterionStatusEnum", status)
    apply_update_mask(client, operation, criterion)
    response = run_ads_call(service.mutate_ad_group_criteria, customer_id=cid, operations=[operation])
    get_store().record_audit(
        tool="set_keyword_status",
        action="apply",
        customer_id=cid,
        payload={"criterion_id": criterion_id, "status": status},
    )
    return {"status": "applied", "resource_name": response.results[0].resource_name}


def update_campaign_budget(
    customer_id: str,
    campaign_id: str,
    daily_budget: float,
    dry_run: bool = True,
    confirm_token: str | None = None,
    force: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Change a campaign's daily budget. Amount is in account currency, not micros.

    Increases above GOOGLE_ADS_BUDGET_INCREASE_CAP (default 20%) require force=true.
    """
    cid = clean_customer_id(customer_id)
    current_rows = search(
        cid,
        "SELECT campaign_budget.resource_name, campaign_budget.amount_micros "
        f"FROM campaign WHERE campaign.id = {int(campaign_id)} LIMIT 1",
        login_customer_id=login_customer_id,
    )
    if not current_rows:
        raise ValueError(f"Campaign {campaign_id} not found")
    current_amount = from_micros(current_rows[0].get("campaign_budget.amount_micros"))
    budget_name = current_rows[0]["campaign_budget.resource_name"]
    _gate().assert_budget_increase_ok(current_amount, daily_budget, force)
    auth = _gate().authorize_write(
        tool="update_campaign_budget",
        customer_id=cid,
        args=with_login_arg(
            {"campaign_id": str(campaign_id), "daily_budget": daily_budget, "force": force},
            login_customer_id,
        ),
        description=f"Change campaign {campaign_id} daily budget {current_amount} -> {daily_budget}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if preview := _maybe_preview(auth):
        preview["current_daily_budget"] = current_amount
        preview["new_daily_budget"] = daily_budget
        return preview
    client = get_client(login_customer_id)
    service = client.get_service("CampaignBudgetService")
    operation = client.get_type("CampaignBudgetOperation")
    budget = operation.update
    budget.resource_name = budget_name
    budget.amount_micros = to_micros(daily_budget)
    apply_update_mask(client, operation, budget)
    response = run_ads_call(service.mutate_campaign_budgets, customer_id=cid, operations=[operation])
    get_store().record_audit(
        tool="update_campaign_budget",
        action="apply",
        customer_id=cid,
        payload={"campaign_id": campaign_id, "from": current_amount, "to": daily_budget},
    )
    return {
        "status": "applied",
        "resource_name": response.results[0].resource_name,
        "daily_budget": daily_budget,
    }


def update_campaign_bidding(
    customer_id: str,
    campaign_id: str,
    bidding_strategy: str,
    target_cpa: float | None = None,
    target_roas: float | None = None,
    dry_run: bool = True,
    confirm_token: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Update a campaign bidding strategy.

    bidding_strategy: MANUAL_CPC, MAXIMIZE_CLICKS, MAXIMIZE_CONVERSIONS,
    TARGET_CPA, or MAXIMIZE_CONVERSION_VALUE.
    """
    from google_ads_mcp.builders.common import apply_bidding

    cid = clean_customer_id(customer_id)
    auth = _gate().authorize_write(
        tool="update_campaign_bidding",
        customer_id=cid,
        args=with_login_arg(
            {
                "campaign_id": str(campaign_id),
                "bidding_strategy": bidding_strategy,
                "target_cpa": target_cpa,
                "target_roas": target_roas,
            },
            login_customer_id,
        ),
        description=f"Set campaign {campaign_id} bidding to {bidding_strategy}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if preview := _maybe_preview(auth):
        return preview
    client = get_client(login_customer_id)
    service = client.get_service("CampaignService")
    operation = client.get_type("CampaignOperation")
    campaign = operation.update
    campaign.resource_name = service.campaign_path(cid, campaign_id)
    apply_bidding(
        client,
        campaign,
        bidding_strategy=bidding_strategy,
        target_cpa=target_cpa,
        target_roas=target_roas,
    )
    apply_update_mask(client, operation, campaign)
    response = run_ads_call(service.mutate_campaigns, customer_id=cid, operations=[operation])
    get_store().record_audit(
        tool="update_campaign_bidding",
        action="apply",
        customer_id=cid,
        payload={"campaign_id": campaign_id, "bidding_strategy": bidding_strategy},
    )
    return {"status": "applied", "resource_name": response.results[0].resource_name}


def register(mcp: FastMCP) -> None:
    mcp.tool(set_campaign_status)
    mcp.tool(set_ad_group_status)
    mcp.tool(set_ad_status)
    mcp.tool(set_keyword_status)
    mcp.tool(update_campaign_budget)
    mcp.tool(update_campaign_bidding)
