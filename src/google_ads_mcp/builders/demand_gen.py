"""Demand Gen campaign mutate graphs. Do not route this through the Display builder."""

from __future__ import annotations

from typing import Any

from google_ads_mcp.builders.common import (
    apply_bidding,
    budget_operation,
    default_dates,
    set_eu_political_flag,
)
from google_ads_mcp.errors import AdsError
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.mutate import TempIds, apply_update_mask

STOCKHOLM_GEO_TARGET_ID = "21000"  # Stockholm County
SWEDISH_LANGUAGE_ID = "1015"  # Swedish (1010 is Dutch)
DISPLAY_LIST_THRESHOLD = 100
DEMAND_GEN_HEADLINE_MAX_CHARS = 40
DEMAND_GEN_DESCRIPTION_MAX_CHARS = 90
DEMAND_GEN_BUSINESS_NAME_MAX_CHARS = 25
DEMAND_GEN_MIN_HEADLINES = 3
DEMAND_GEN_MIN_DESCRIPTIONS = 1
CHANNEL_ATTRS = {
    "DISPLAY": ("display",),
    "YOUTUBE": ("youtube_in_stream", "youtube_in_feed", "youtube_shorts"),
    "DISCOVER": ("discover",),
    "GMAIL": ("gmail",),
    "MAPS": ("maps",),
}
ALL_CHANNEL_ATTRS = (
    "youtube_in_stream",
    "youtube_in_feed",
    "youtube_shorts",
    "discover",
    "gmail",
    "display",
    "maps",
)


def validate_demand_gen_copy(headlines: list[str], descriptions: list[str], business_name: str) -> None:
    if len(headlines) < DEMAND_GEN_MIN_HEADLINES:
        raise ValueError(
            f"Demand Gen multi-asset ads require at least {DEMAND_GEN_MIN_HEADLINES} headlines "
            f"(max {DEMAND_GEN_HEADLINE_MAX_CHARS} chars each)."
        )
    if len(descriptions) < DEMAND_GEN_MIN_DESCRIPTIONS:
        raise ValueError("Demand Gen multi-asset ads require at least 1 description.")
    for index, text in enumerate(headlines, 1):
        if len(text) > DEMAND_GEN_HEADLINE_MAX_CHARS:
            raise ValueError(
                f"Headline {index} exceeds {DEMAND_GEN_HEADLINE_MAX_CHARS} characters ({len(text)}): {text!r}"
            )
    for index, text in enumerate(descriptions, 1):
        if len(text) > DEMAND_GEN_DESCRIPTION_MAX_CHARS:
            raise ValueError(
                f"Description {index} exceeds {DEMAND_GEN_DESCRIPTION_MAX_CHARS} characters ({len(text)}): {text!r}"
            )
    if len(business_name) > DEMAND_GEN_BUSINESS_NAME_MAX_CHARS:
        raise ValueError(
            f"Business name exceeds {DEMAND_GEN_BUSINESS_NAME_MAX_CHARS} characters ({len(business_name)})."
        )


def user_list_resource(client, customer_id: str, value: str) -> str:
    text = str(value).strip()
    if text.startswith("customers/"):
        return text
    return client.get_service("UserListService").user_list_path(customer_id, text)


def audience_resource(client, customer_id: str, value: str) -> str:
    text = str(value).strip()
    if text.startswith("customers/"):
        return text
    return client.get_service("AudienceService").audience_path(customer_id, text)


def normalize_conversion_action_resource(customer_id: str, value: str) -> str:
    """Preserve full resource names; prefix bare IDs with the campaign customer."""
    text = str(value).strip()
    if text.startswith("customers/"):
        return text
    cid = clean_customer_id(customer_id)
    bare = text.rsplit("/", 1)[-1]
    return f"customers/{cid}/conversionActions/{bare}"


def conversion_action_resource(client, customer_id: str, value: str) -> str:
    return normalize_conversion_action_resource(customer_id, value)


def apply_selected_channels(ad_group, channels: list[str]) -> set[str]:
    selected: set[str] = set()
    for raw in channels:
        key = str(raw).strip().upper()
        if key not in CHANNEL_ATTRS:
            raise AdsError(
                f"Unsupported Demand Gen channel {raw!r}. Use one of: {', '.join(sorted(CHANNEL_ATTRS))}."
            )
        selected.update(CHANNEL_ATTRS[key])
    flags = ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels
    for attr in ALL_CHANNEL_ATTRS:
        setattr(flags, attr, attr in selected)
    return selected


def build_audience_create(
    client,
    customer_id: str,
    *,
    name: str,
    included_user_list_ids: list[str],
    excluded_user_list_ids: list[str] | None = None,
):
    if not name.strip():
        raise AdsError("Audience name is required.")
    if not included_user_list_ids:
        raise AdsError("included_user_list_ids is required.")
    cid = clean_customer_id(customer_id)
    operation = client.get_type("AudienceOperation")
    audience = operation.create
    audience.name = name.strip()
    audience.status = client.enums.AudienceStatusEnum.ENABLED
    dimension = client.get_type("AudienceDimension")
    seen: set[str] = set()
    for list_id in included_user_list_ids:
        resource = user_list_resource(client, cid, list_id)
        if resource in seen:
            raise AdsError(f"Duplicate user list {list_id!r} in included_user_list_ids.")
        seen.add(resource)
        segment = client.get_type("AudienceSegment")
        segment.user_list.user_list = resource
        dimension.audience_segments.segments.append(segment)
    audience.dimensions.append(dimension)
    for list_id in excluded_user_list_ids or []:
        resource = user_list_resource(client, cid, list_id)
        exclusion = client.get_type("ExclusionSegment")
        exclusion.user_list.user_list = resource
        audience.exclusion_dimension.exclusions.append(exclusion)
    return operation


def build_audience_criterion_operation(client, customer_id: str, ad_group_resource: str, audience_id: str):
    cid = clean_customer_id(customer_id)
    operation = client.get_type("AdGroupCriterionOperation")
    criterion = operation.create
    criterion.ad_group = ad_group_resource
    criterion.audience.audience = audience_resource(client, cid, audience_id)
    return operation


def build_ad_group_audience_setting_update(client, ad_group_resource: str):
    operation = client.get_type("AdGroupOperation")
    ad_group = operation.update
    ad_group.resource_name = ad_group_resource
    ad_group.audience_setting.use_audience_grouped = True
    apply_update_mask(client, operation, ad_group)
    return operation


def build_conversion_goal_operations(
    client,
    customer_id: str,
    *,
    campaign_id: str,
    conversion_action_ids: list[str],
    name: str,
    temps: TempIds | None = None,
    existing_goal_resource_name: str | None = None,
) -> list[Any]:
    if not conversion_action_ids:
        raise AdsError("conversion_action_ids is required.")
    cid = clean_customer_id(customer_id)
    temps = temps or TempIds()
    goal_service = client.get_service("CustomConversionGoalService")
    config_service = client.get_service("ConversionGoalCampaignConfigService")
    campaign_service = client.get_service("CampaignService")
    operations: list[Any] = []

    if existing_goal_resource_name:
        goal_resource = existing_goal_resource_name
    else:
        goal_op = client.get_type("MutateOperation")
        goal = goal_op.custom_conversion_goal_operation.create
        goal.resource_name = goal_service.custom_conversion_goal_path(cid, temps.next())
        goal.name = name
        goal.status = client.enums.CustomConversionGoalStatusEnum.ENABLED
        for action_id in conversion_action_ids:
            goal.conversion_actions.append(conversion_action_resource(client, cid, action_id))
        operations.append(goal_op)
        goal_resource = goal.resource_name

    config_op = client.get_type("MutateOperation")
    config = config_op.conversion_goal_campaign_config_operation.update
    config.resource_name = config_service.conversion_goal_campaign_config_path(cid, campaign_id)
    config.campaign = campaign_service.campaign_path(cid, campaign_id)
    config.custom_conversion_goal = goal_resource
    config.goal_config_level = client.enums.GoalConfigLevelEnum.CAMPAIGN
    apply_update_mask(client, config_op.conversion_goal_campaign_config_operation, config)
    operations.append(config_op)
    return operations


def matching_custom_conversion_goal(
    rows: list[dict[str, Any]],
    *,
    customer_id: str,
    conversion_action_ids: list[str],
) -> str | None:
    """Return resource_name of an ENABLED goal with the same conversion-action set."""
    wanted = {
        normalize_conversion_action_resource(customer_id, action_id)
        for action_id in conversion_action_ids
    }
    for row in rows:
        status = str(row.get("custom_conversion_goal.status") or "").upper()
        if status and status != "ENABLED":
            continue
        actions = row.get("custom_conversion_goal.conversion_actions") or []
        if isinstance(actions, str):
            actions = [actions]
        existing = {str(item) for item in actions if item}
        if existing == wanted:
            rn = row.get("custom_conversion_goal.resource_name")
            if rn:
                return str(rn)
    return None


def _text_asset(client, text: str):
    asset = client.get_type("AdTextAsset")
    asset.text = text
    return asset


def _image_assets(client, resource_names: list[str]):
    links = []
    for name in resource_names:
        image = client.get_type("AdImageAsset")
        image.asset = name
        links.append(image)
    return links


def build_demand_gen_campaign(
    client,
    customer_id: str,
    *,
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
    target_cpc: float | None = None,
    target_cpa: float | None = None,
    target_roas: float | None = None,
    conversion_action_ids: list[str] | None = None,
    contains_eu_political: bool = False,
    existing_conversion_goal_resource_name: str | None = None,
) -> list[Any]:
    validate_demand_gen_copy(headlines, descriptions, business_name)
    if not marketing_image_assets or not square_marketing_image_assets or not logo_image_assets:
        raise ValueError("Demand Gen requires marketing, square marketing, and logo image assets.")
    cid = clean_customer_id(customer_id)
    geos = list(geo_target_constant_ids or [STOCKHOLM_GEO_TARGET_ID])
    languages = list(language_constant_ids or [SWEDISH_LANGUAGE_ID])
    selected_channels = list(channels or ["DISPLAY"])
    temps = TempIds()
    operations: list[Any] = []

    budget_op, budget_name = budget_operation(
        client, cid, name=f"{name} budget", daily_budget=daily_budget, temps=temps, explicitly_shared=False
    )
    operations.append(budget_op)

    campaign_service = client.get_service("CampaignService")
    campaign_op = client.get_type("MutateOperation")
    campaign = campaign_op.campaign_operation.create
    campaign.resource_name = campaign_service.campaign_path(cid, temps.next())
    campaign.name = name
    campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.DEMAND_GEN
    campaign.status = client.enums.CampaignStatusEnum.PAUSED
    campaign.campaign_budget = budget_name
    apply_bidding(
        client,
        campaign,
        bidding_strategy=bidding_strategy,
        target_cpa=target_cpa,
        target_roas=target_roas,
        target_cpc=target_cpc,
    )
    set_eu_political_flag(client, campaign, contains_eu_political)
    campaign.start_date_time = default_dates()[0]
    operations.append(campaign_op)

    if conversion_action_ids:
        operations.extend(
            build_conversion_goal_operations(
                client,
                cid,
                campaign_id=campaign.resource_name.rsplit("/", 1)[-1],
                conversion_action_ids=conversion_action_ids,
                name=f"{name} conversions",
                temps=temps,
                existing_goal_resource_name=existing_conversion_goal_resource_name,
            )
        )

    ad_group_service = client.get_service("AdGroupService")
    ad_group_op = client.get_type("MutateOperation")
    ad_group = ad_group_op.ad_group_operation.create
    ad_group.resource_name = ad_group_service.ad_group_path(cid, temps.next())
    ad_group.name = f"{name} ad group"
    ad_group.campaign = campaign.resource_name
    ad_group.status = client.enums.AdGroupStatusEnum.PAUSED
    ad_group.audience_setting.use_audience_grouped = True
    ad_group.optimized_targeting_enabled = optimized_targeting_enabled
    apply_selected_channels(ad_group, selected_channels)
    operations.append(ad_group_op)

    audience_op = client.get_type("MutateOperation")
    client.copy_from(
        audience_op.ad_group_criterion_operation,
        build_audience_criterion_operation(client, cid, ad_group.resource_name, audience_id),
    )
    operations.append(audience_op)

    geo_service = client.get_service("GeoTargetConstantService")
    for geo_id in geos:
        loc_op = client.get_type("MutateOperation")
        criterion = loc_op.ad_group_criterion_operation.create
        criterion.ad_group = ad_group.resource_name
        criterion.location.geo_target_constant = geo_service.geo_target_constant_path(str(geo_id).replace("geoTargetConstants/", ""))
        operations.append(loc_op)
    for language_id in languages:
        lang_op = client.get_type("MutateOperation")
        criterion = lang_op.ad_group_criterion_operation.create
        criterion.ad_group = ad_group.resource_name
        criterion.language.language_constant = f"languageConstants/{str(language_id).replace('languageConstants/', '')}"
        operations.append(lang_op)

    ad_op = client.get_type("MutateOperation")
    ad_group_ad = ad_op.ad_group_ad_operation.create
    ad_group_ad.ad_group = ad_group.resource_name
    ad_group_ad.status = client.enums.AdGroupAdStatusEnum.PAUSED
    ad_group_ad.ad.final_urls.append(final_url)
    ad_group_ad.ad.name = f"{name} multi-asset ad"
    creative = ad_group_ad.ad.demand_gen_multi_asset_ad
    creative.business_name = business_name
    creative.headlines.extend(_text_asset(client, text) for text in headlines)
    creative.descriptions.extend(_text_asset(client, text) for text in descriptions)
    creative.marketing_images.extend(_image_assets(client, marketing_image_assets))
    creative.square_marketing_images.extend(_image_assets(client, square_marketing_image_assets))
    creative.logo_images.extend(_image_assets(client, logo_image_assets))
    operations.append(ad_op)
    return operations


def meets_display_threshold(size_for_display: Any, eligible_for_display: Any) -> bool | None:
    if eligible_for_display is False:
        return False
    try:
        size = int(size_for_display)
    except (TypeError, ValueError):
        return None
    if size < 0:
        return None
    return size >= DISPLAY_LIST_THRESHOLD and bool(eligible_for_display)


def requested_channel_attrs(channels: list[str]) -> set[str]:
    selected: set[str] = set()
    for raw in channels:
        key = str(raw).strip().upper()
        if key not in CHANNEL_ATTRS:
            raise AdsError(
                f"Unsupported Demand Gen channel {raw!r}. Use one of: {', '.join(sorted(CHANNEL_ATTRS))}."
            )
        selected.update(CHANNEL_ATTRS[key])
    return selected


def enabled_channel_attrs(row: dict[str, Any]) -> set[str] | None:
    config = str(row.get("ad_group.demand_gen_ad_group_settings.channel_controls.channel_config") or "")
    strategy = str(row.get("ad_group.demand_gen_ad_group_settings.channel_controls.channel_strategy") or "")
    if config == "CHANNEL_STRATEGY" or strategy in {"ALL_CHANNELS", "ALL_OWNED_AND_OPERATED_CHANNELS"}:
        return None
    enabled = {
        attr
        for attr in ALL_CHANNEL_ATTRS
        if row.get(f"ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.{attr}") is True
    }
    return enabled


def evaluate_demand_gen_readiness(
    *,
    campaign: dict[str, Any] | None,
    ad_groups: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    ads: list[dict[str, Any]],
    user_lists: list[dict[str, Any]],
    goal_config: dict[str, Any] | None,
    expected_channels: list[str],
    expected_geo_ids: list[str],
    expect_optimized_targeting: bool = False,
    purchase_action_ids: list[str] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    if not campaign:
        return {"ready": False, "failures": ["Campaign not found."], "warnings": []}
    if campaign.get("campaign.advertising_channel_type") not in {"DEMAND_GEN", None}:
        channel = campaign.get("campaign.advertising_channel_type")
        if channel and channel != "DEMAND_GEN":
            failures.append(f"Campaign channel is {channel}, not DEMAND_GEN.")

    audience_names = [
        row.get("ad_group_criterion.audience.audience")
        for row in criteria
        if row.get("ad_group_criterion.audience.audience") and not row.get("ad_group_criterion.negative")
    ]
    if not audience_names:
        failures.append("No audience is attached to a Demand Gen ad group.")

    for row in user_lists:
        meets = meets_display_threshold(row.get("user_list.size_for_display"), row.get("user_list.eligible_for_display"))
        name = row.get("user_list.name") or row.get("user_list.id") or "user list"
        if meets is False:
            failures.append(f"{name} is ineligible or below {DISPLAY_LIST_THRESHOLD} Display users.")
        elif meets is None:
            warnings.append(f"{name} Display size is unknown; confirm it has reached {DISPLAY_LIST_THRESHOLD} users.")

    wanted = requested_channel_attrs(expected_channels)
    for group in ad_groups:
        optimized = group.get("ad_group.optimized_targeting_enabled")
        if bool(optimized) != expect_optimized_targeting:
            failures.append(
                "Optimized targeting is enabled unexpectedly."
                if optimized
                else "Optimized targeting is off but was expected on."
            )
        enabled = enabled_channel_attrs(group)
        if enabled is None:
            failures.append("More than the requested channels are enabled (all-channels strategy).")
        elif enabled - wanted:
            failures.append(f"Unexpected Demand Gen channels enabled: {', '.join(sorted(enabled - wanted))}.")
        elif wanted - enabled:
            warnings.append(f"Requested channels are not enabled: {', '.join(sorted(wanted - enabled))}.")

    expected_geos = {str(item).replace("geoTargetConstants/", "") for item in expected_geo_ids}
    positive_geos = {
        str(row.get("ad_group_criterion.location.geo_target_constant") or "").rsplit("/", 1)[-1]
        for row in criteria
        if row.get("ad_group_criterion.location.geo_target_constant") and not row.get("ad_group_criterion.negative")
    }
    if expected_geos and not (positive_geos & expected_geos):
        failures.append("No positive Stockholm (or requested) location targeting exists at the ad group.")

    custom_actions = {
        str(item).rsplit("/", 1)[-1]
        for item in (goal_config or {}).get("custom_conversion_goal.conversion_actions") or []
    }
    wanted_actions = {str(item).rsplit("/", 1)[-1] for item in purchase_action_ids or []}
    level = (goal_config or {}).get("conversion_goal_campaign_config.goal_config_level")
    if wanted_actions:
        if level != "CAMPAIGN" or not (wanted_actions <= custom_actions):
            failures.append("Purchase is not the campaign custom conversion goal.")
    elif level != "CAMPAIGN" or not custom_actions:
        warnings.append("Campaign is not using a custom conversion goal.")

    if not ads:
        failures.append("Required Demand Gen assets are missing.")
    for ad in ads:
        approval = ad.get("ad_group_ad.policy_summary.approval_status")
        if approval == "DISAPPROVED":
            failures.append("A Demand Gen ad is disapproved.")
        ad_type = str(ad.get("ad_group_ad.ad.type") or "").upper()
        if ad_type == "DEMAND_GEN_VIDEO_RESPONSIVE_AD" or (
            not ad_type and _looks_like_video_responsive(ad)
        ):
            if _video_responsive_assets_missing(ad):
                failures.append("Required Demand Gen video assets are missing.")
            continue
        if ad_type in {"DEMAND_GEN_CAROUSEL_AD", "DEMAND_GEN_PRODUCT_AD"}:
            continue
        if _multi_asset_assets_missing(ad):
            failures.append("Required Demand Gen assets are missing.")

    return {"ready": not failures, "failures": failures, "warnings": warnings}


def _looks_like_video_responsive(ad: dict[str, Any]) -> bool:
    return bool(
        ad.get("ad_group_ad.ad.demand_gen_video_responsive_ad.videos")
        or ad.get("ad_group_ad.ad.demand_gen_video_responsive_ad.headlines")
        or ad.get("ad_group_ad.ad.demand_gen_video_responsive_ad.long_headlines")
        or ad.get("ad_group_ad.ad.demand_gen_video_responsive_ad.logo_images")
    )


def _multi_asset_assets_missing(ad: dict[str, Any]) -> bool:
    headlines = ad.get("ad_group_ad.ad.demand_gen_multi_asset_ad.headlines") or []
    marketing = ad.get("ad_group_ad.ad.demand_gen_multi_asset_ad.marketing_images") or []
    square = ad.get("ad_group_ad.ad.demand_gen_multi_asset_ad.square_marketing_images") or []
    logos = ad.get("ad_group_ad.ad.demand_gen_multi_asset_ad.logo_images") or []
    return not headlines or not marketing or not square or not logos


def _video_responsive_assets_missing(ad: dict[str, Any]) -> bool:
    headlines = ad.get("ad_group_ad.ad.demand_gen_video_responsive_ad.headlines") or []
    long_headlines = ad.get("ad_group_ad.ad.demand_gen_video_responsive_ad.long_headlines") or []
    videos = ad.get("ad_group_ad.ad.demand_gen_video_responsive_ad.videos") or []
    logos = ad.get("ad_group_ad.ad.demand_gen_video_responsive_ad.logo_images") or []
    return (not headlines and not long_headlines) or not videos or not logos
