"""Demand Gen create, conversion goals, and pre-enable readiness."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp.builders.demand_gen import (
    STOCKHOLM_GEO_TARGET_ID,
    SWEDISH_LANGUAGE_ID,
    build_conversion_goal_operations,
    build_demand_gen_campaign,
    evaluate_demand_gen_readiness,
    validate_demand_gen_copy,
)
from google_ads_mcp.client import get_client
from google_ads_mcp.gaql import search
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.mutate import mutate
from google_ads_mcp.safety import SafetyGate, with_login_arg
from google_ads_mcp.store import get_store


def _gate() -> SafetyGate:
    return SafetyGate()


def create_demand_gen_campaign(
    customer_id: str,
    name: str,
    daily_budget: float,
    final_url: str,
    business_name: str,
    headlines: list[str],
    descriptions: list[str],
    marketing_image_assets: list[str],
    square_marketing_image_assets: list[str],
    logo_image_assets: list[str],
    audience_id: str,
    geo_target_constant_ids: list[str] | None = None,
    language_constant_ids: list[str] | None = None,
    channels: list[str] | None = None,
    optimized_targeting_enabled: bool = False,
    bidding_strategy: str = "MAXIMIZE_CLICKS",
    target_cpc: float | None = 3.0,
    target_cpa: float | None = None,
    target_roas: float | None = None,
    conversion_action_ids: list[str] | None = None,
    contains_eu_political: bool = False,
    dry_run: bool = True,
    confirm_token: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Create a paused Demand Gen campaign in one atomic mutate.

    Does not use the legacy Display builder. Campaign, ad group, and ad stay
    PAUSED. Defaults to Display-only channel controls, optimized targeting off,
    Stockholm geo (1005184) and Swedish (1010) at the ad group. Pass an Audience
    id from create_audience. conversion_action_ids become a campaign custom goal
    (Purchase-only bidding).
    """
    validate_demand_gen_copy(headlines, descriptions, business_name)
    cid = clean_customer_id(customer_id)
    geos = list(geo_target_constant_ids or [STOCKHOLM_GEO_TARGET_ID])
    languages = list(language_constant_ids or [SWEDISH_LANGUAGE_ID])
    selected = list(channels or ["DISPLAY"])
    actions = list(conversion_action_ids or [])
    args = with_login_arg(
        {
            "name": name,
            "daily_budget": daily_budget,
            "final_url": final_url,
            "business_name": business_name,
            "headlines": headlines,
            "descriptions": descriptions,
            "marketing_image_assets": marketing_image_assets,
            "square_marketing_image_assets": square_marketing_image_assets,
            "logo_image_assets": logo_image_assets,
            "audience_id": str(audience_id),
            "geo_target_constant_ids": geos,
            "language_constant_ids": languages,
            "channels": selected,
            "optimized_targeting_enabled": optimized_targeting_enabled,
            "bidding_strategy": bidding_strategy,
            "target_cpc": target_cpc,
            "target_cpa": target_cpa,
            "target_roas": target_roas,
            "conversion_action_ids": actions,
            "contains_eu_political": contains_eu_political,
        },
        login_customer_id,
    )
    auth = _gate().authorize_write(
        tool="create_demand_gen_campaign",
        customer_id=cid,
        args=args,
        description=f"Create PAUSED Demand Gen campaign '{name}' with daily budget {daily_budget}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    client = get_client(login_customer_id)
    operations = build_demand_gen_campaign(
        client,
        cid,
        name=name,
        daily_budget=daily_budget,
        final_url=final_url,
        business_name=business_name,
        headlines=headlines,
        descriptions=descriptions,
        marketing_image_assets=marketing_image_assets,
        square_marketing_image_assets=square_marketing_image_assets,
        logo_image_assets=logo_image_assets,
        audience_id=audience_id,
        geo_target_constant_ids=geos,
        language_constant_ids=languages,
        channels=selected,
        optimized_targeting_enabled=optimized_targeting_enabled,
        bidding_strategy=bidding_strategy,
        target_cpc=target_cpc,
        target_cpa=target_cpa,
        target_roas=target_roas,
        conversion_action_ids=actions or None,
        contains_eu_political=contains_eu_political,
    )
    result = mutate(cid, operations, client=client)
    get_store().record_audit(
        tool="create_demand_gen_campaign",
        action="apply",
        customer_id=cid,
        payload={"name": name, "result": result},
    )
    return {"status": "applied", "created_paused": True, **result}


def set_campaign_conversion_actions(
    customer_id: str,
    campaign_id: str,
    conversion_action_ids: list[str],
    name: str | None = None,
    dry_run: bool = True,
    confirm_token: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Apply a custom conversion goal so the campaign bids only on these actions.

    Use this to bid toward Purchase and ignore lead-form or analysis-start events.
    """
    cid = clean_customer_id(customer_id)
    args = with_login_arg(
        {
            "campaign_id": str(campaign_id),
            "conversion_action_ids": list(conversion_action_ids),
            "name": name,
        },
        login_customer_id,
    )
    auth = _gate().authorize_write(
        tool="set_campaign_conversion_actions",
        customer_id=cid,
        args=args,
        description=f"Set campaign {campaign_id} conversion actions ({len(conversion_action_ids)})",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    client = get_client(login_customer_id)
    operations = build_conversion_goal_operations(
        client,
        cid,
        campaign_id=str(campaign_id),
        conversion_action_ids=conversion_action_ids,
        name=name or f"Campaign {campaign_id} custom goal",
    )
    result = mutate(cid, operations, client=client)
    get_store().record_audit(
        tool="set_campaign_conversion_actions",
        action="apply",
        customer_id=cid,
        payload=args,
    )
    return {"status": "applied", **result}


def get_demand_gen_readiness(
    customer_id: str,
    campaign_id: str,
    expected_channels: list[str] | None = None,
    expected_geo_target_constant_ids: list[str] | None = None,
    purchase_action_ids: list[str] | None = None,
    expect_optimized_targeting: bool = False,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Check a Demand Gen campaign before enabling it.

    Fails when no audience is attached, lists are ineligible or under 100 Display
    users, optimized targeting is unexpectedly on, extra channels are enabled,
    Stockholm (or requested) geo is missing, Purchase is not the custom goal, or
    required assets are missing/disapproved.
    """
    cid = clean_customer_id(customer_id)
    channels = list(expected_channels or ["DISPLAY"])
    geos = [str(item).replace("geoTargetConstants/", "") for item in (expected_geo_target_constant_ids or [STOCKHOLM_GEO_TARGET_ID])]
    campaigns = search(
        cid,
        "SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type "
        f"FROM campaign WHERE campaign.id = {int(campaign_id)} LIMIT 1",
        login_customer_id=login_customer_id,
    )
    ad_groups = search(
        cid,
        "SELECT ad_group.id, ad_group.optimized_targeting_enabled, "
        "ad_group.audience_setting.use_audience_grouped, "
        "ad_group.demand_gen_ad_group_settings.channel_controls.channel_config, "
        "ad_group.demand_gen_ad_group_settings.channel_controls.channel_strategy, "
        "ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.youtube_in_feed, "
        "ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.youtube_in_stream, "
        "ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.youtube_shorts, "
        "ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.discover, "
        "ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.display, "
        "ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.gmail, "
        "ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.maps "
        f"FROM ad_group WHERE campaign.id = {int(campaign_id)} AND ad_group.status != 'REMOVED'",
        login_customer_id=login_customer_id,
    )
    criteria = search(
        cid,
        "SELECT ad_group_criterion.type, ad_group_criterion.negative, "
        "ad_group_criterion.audience.audience, "
        "ad_group_criterion.location.geo_target_constant, "
        "ad_group_criterion.language.language_constant "
        f"FROM ad_group_criterion WHERE campaign.id = {int(campaign_id)} "
        "AND ad_group_criterion.status != 'REMOVED'",
        login_customer_id=login_customer_id,
    )
    ads = search(
        cid,
        "SELECT ad_group_ad.policy_summary.approval_status, "
        "ad_group_ad.ad.demand_gen_multi_asset_ad.headlines, "
        "ad_group_ad.ad.demand_gen_multi_asset_ad.marketing_images, "
        "ad_group_ad.ad.demand_gen_multi_asset_ad.square_marketing_images, "
        "ad_group_ad.ad.demand_gen_multi_asset_ad.logo_images "
        f"FROM ad_group_ad WHERE campaign.id = {int(campaign_id)} "
        "AND ad_group_ad.status != 'REMOVED'",
        login_customer_id=login_customer_id,
    )
    goals = search(
        cid,
        "SELECT conversion_goal_campaign_config.goal_config_level, "
        "conversion_goal_campaign_config.custom_conversion_goal, "
        "custom_conversion_goal.conversion_actions, custom_conversion_goal.name "
        f"FROM conversion_goal_campaign_config WHERE campaign.id = {int(campaign_id)} LIMIT 1",
        login_customer_id=login_customer_id,
    )
    list_ids: list[str] = []
    for row in criteria:
        audience_name = row.get("ad_group_criterion.audience.audience")
        if not audience_name:
            continue
        audience_id = str(audience_name).rsplit("/", 1)[-1]
        audiences = search(
            cid,
            "SELECT audience.id, audience.dimensions, audience.exclusion_dimension "
            f"FROM audience WHERE audience.id = {int(audience_id)} LIMIT 1",
            login_customer_id=login_customer_id,
        )
        list_ids.extend(_user_list_ids_from_audience(audiences[0] if audiences else {}))
    user_lists: list[dict[str, Any]] = []
    if list_ids:
        ids = ", ".join(str(int(item)) for item in dict.fromkeys(list_ids))
        user_lists = search(
            cid,
            "SELECT user_list.id, user_list.name, user_list.size_for_display, "
            "user_list.eligible_for_display FROM user_list "
            f"WHERE user_list.id IN ({ids})",
            login_customer_id=login_customer_id,
        )
    verdict = evaluate_demand_gen_readiness(
        campaign=campaigns[0] if campaigns else None,
        ad_groups=ad_groups,
        criteria=criteria,
        ads=ads,
        user_lists=user_lists,
        goal_config=goals[0] if goals else None,
        expected_channels=channels,
        expected_geo_ids=geos,
        expect_optimized_targeting=expect_optimized_targeting,
        purchase_action_ids=purchase_action_ids,
    )
    return {
        "customer_id": cid,
        "campaign_id": str(campaign_id),
        **verdict,
    }


def _user_list_ids_from_audience(row: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    dimensions = row.get("audience.dimensions") or []
    if isinstance(dimensions, dict):
        dimensions = [dimensions]
    for dimension in dimensions:
        if not isinstance(dimension, dict):
            continue
        segments = (dimension.get("audience_segments") or {}).get("segments") or []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            resource = (segment.get("user_list") or {}).get("user_list")
            if resource:
                ids.append(str(resource).rsplit("/", 1)[-1])
    return ids


def register(mcp: FastMCP) -> None:
    mcp.tool(create_demand_gen_campaign)
    mcp.tool(set_campaign_conversion_actions)
    mcp.tool(get_demand_gen_readiness)
