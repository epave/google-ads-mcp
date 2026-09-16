"""User lists and reusable Audience resources (Demand Gen / PMax targeting)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp.builders.demand_gen import (
    build_ad_group_audience_setting_update,
    build_audience_create,
    build_audience_criterion_operation,
    meets_display_threshold,
)
from google_ads_mcp.client import get_client, run_ads_call
from google_ads_mcp.gaql import search
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.safety import SafetyGate, with_login_arg
from google_ads_mcp.store import get_store


def _gate() -> SafetyGate:
    return SafetyGate()


def list_user_lists(
    customer_id: str,
    limit: int = 100,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """List remarketing / customer-match user lists and Display eligibility.

    Returns size_for_display and eligible_for_display so you can see when a list
    reaches Google's 100-user Display serving threshold. Ads API v25 no longer
    exposes prepopulation_status; that field is always null. GA4 event audiences
    should be created in GA4 and imported — this tool only reads Ads user lists.
    """
    cid = clean_customer_id(customer_id)
    rows = search(
        cid,
        "SELECT user_list.id, user_list.name, user_list.type, user_list.membership_status, "
        "user_list.size_for_display, user_list.eligible_for_display, "
        "user_list.membership_life_span FROM user_list "
        f"ORDER BY user_list.name LIMIT {int(limit)}",
        login_customer_id=login_customer_id,
    )
    lists = []
    for row in rows:
        size = row.get("user_list.size_for_display")
        eligible = row.get("user_list.eligible_for_display")
        lists.append(
            {
                "id": row.get("user_list.id"),
                "name": row.get("user_list.name"),
                "type": row.get("user_list.type"),
                "membership_status": row.get("user_list.membership_status"),
                "size_for_display": size,
                "eligible_for_display": eligible,
                "membership_duration_days": row.get("user_list.membership_life_span"),
                "prepopulation_status": None,
                "meets_display_threshold": meets_display_threshold(size, eligible),
            }
        )
    return {"customer_id": cid, "count": len(lists), "user_lists": lists}


def list_audiences(
    customer_id: str,
    limit: int = 100,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """List reusable Audience resources (Demand Gen / Performance Max targeting)."""
    cid = clean_customer_id(customer_id)
    rows = search(
        cid,
        "SELECT audience.id, audience.name, audience.status, audience.description, "
        "audience.dimensions, audience.exclusion_dimension FROM audience "
        "WHERE audience.status != 'REMOVED' "
        f"ORDER BY audience.name LIMIT {int(limit)}",
        login_customer_id=login_customer_id,
    )
    return {"customer_id": cid, "count": len(rows), "audiences": rows}


def create_audience(
    customer_id: str,
    name: str,
    included_user_list_ids: list[str],
    excluded_user_list_ids: list[str] | None = None,
    dry_run: bool = True,
    confirm_token: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Create a reusable Audience from included/excluded user-list IDs.

    Demand Gen targets this Audience via attach_audience_to_ad_group or
    create_demand_gen_campaign(audience_id=...). GA4 event lists must already
    exist in Google Ads (imported from GA4).
    """
    cid = clean_customer_id(customer_id)
    args = with_login_arg(
        {
            "name": name,
            "included_user_list_ids": list(included_user_list_ids),
            "excluded_user_list_ids": list(excluded_user_list_ids or []),
        },
        login_customer_id,
    )
    auth = _gate().authorize_write(
        tool="create_audience",
        customer_id=cid,
        args=args,
        description=f"Create audience '{name}' from {len(included_user_list_ids)} user lists",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    client = get_client(login_customer_id)
    operation = build_audience_create(
        client,
        cid,
        name=name,
        included_user_list_ids=included_user_list_ids,
        excluded_user_list_ids=excluded_user_list_ids,
    )
    service = client.get_service("AudienceService")
    response = run_ads_call(service.mutate_audiences, customer_id=cid, operations=[operation])
    resource_name = response.results[0].resource_name
    get_store().record_audit(
        tool="create_audience",
        action="apply",
        customer_id=cid,
        payload={"name": name, "resource_name": resource_name},
    )
    return {"status": "applied", "resource_name": resource_name, "audience_id": resource_name.rsplit("/", 1)[-1]}


def attach_audience_to_ad_group(
    customer_id: str,
    ad_group_id: str,
    audience_id: str,
    dry_run: bool = True,
    confirm_token: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Attach an Audience to a Demand Gen ad group.

    Sets ad_group.audience_setting.use_audience_grouped=true and creates an
    audience AdGroupCriterion.
    """
    cid = clean_customer_id(customer_id)
    args = with_login_arg(
        {"ad_group_id": str(ad_group_id), "audience_id": str(audience_id)},
        login_customer_id,
    )
    auth = _gate().authorize_write(
        tool="attach_audience_to_ad_group",
        customer_id=cid,
        args=args,
        description=f"Attach audience {audience_id} to ad group {ad_group_id}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    client = get_client(login_customer_id)
    ad_group_service = client.get_service("AdGroupService")
    criterion_service = client.get_service("AdGroupCriterionService")
    ad_group_resource = ad_group_service.ad_group_path(cid, ad_group_id)
    setting = build_ad_group_audience_setting_update(client, ad_group_resource)
    criterion = build_audience_criterion_operation(client, cid, ad_group_resource, audience_id)
    run_ads_call(ad_group_service.mutate_ad_groups, customer_id=cid, operations=[setting])
    response = run_ads_call(criterion_service.mutate_ad_group_criteria, customer_id=cid, operations=[criterion])
    resource_name = response.results[0].resource_name
    get_store().record_audit(
        tool="attach_audience_to_ad_group",
        action="apply",
        customer_id=cid,
        payload=args,
    )
    return {"status": "applied", "resource_name": resource_name}


def register(mcp: FastMCP) -> None:
    mcp.tool(list_user_lists)
    mcp.tool(list_audiences)
    mcp.tool(create_audience)
    mcp.tool(attach_audience_to_ad_group)
