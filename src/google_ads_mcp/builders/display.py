"""Display campaign mutate graphs."""

from __future__ import annotations

from typing import Any

from google_ads_mcp.builders.common import (
    apply_bidding,
    budget_operation,
    default_dates,
    set_eu_political_flag,
)
from google_ads_mcp.mutate import TempIds


def _text_asset(client, text: str):
    asset = client.get_type("AdTextAsset")
    asset.text = text
    return asset


def build_display_campaign(
    client,
    customer_id: str,
    *,
    name: str,
    daily_budget: float,
    bidding_strategy: str = "MAXIMIZE_CONVERSIONS",
    target_cpa: float | None = None,
    final_url: str,
    business_name: str,
    headlines: list[str],
    long_headline: str,
    descriptions: list[str],
    marketing_image_asset: str,
    square_marketing_image_asset: str,
    logo_image_asset: str | None = None,
    contains_eu_political: bool = False,
) -> list[Any]:
    if len(headlines) < 1:
        raise ValueError("Display ads require at least 1 headline.")
    if len(descriptions) < 1:
        raise ValueError("Display ads require at least 1 description.")

    temps = TempIds()
    operations: list[Any] = []
    budget_op, budget_name = budget_operation(
        client, customer_id, name=f"{name} budget", daily_budget=daily_budget, temps=temps
    )
    operations.append(budget_op)

    campaign_service = client.get_service("CampaignService")
    campaign_op = client.get_type("MutateOperation")
    campaign = campaign_op.campaign_operation.create
    campaign.resource_name = campaign_service.campaign_path(customer_id, temps.next())
    campaign.name = name
    campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.DISPLAY
    campaign.status = client.enums.CampaignStatusEnum.PAUSED
    campaign.campaign_budget = budget_name
    apply_bidding(client, campaign, bidding_strategy=bidding_strategy, target_cpa=target_cpa)
    set_eu_political_flag(client, campaign, contains_eu_political)
    campaign.start_date_time = default_dates()[0]
    operations.append(campaign_op)

    ad_group_service = client.get_service("AdGroupService")
    ad_group_op = client.get_type("MutateOperation")
    ad_group = ad_group_op.ad_group_operation.create
    ad_group.resource_name = ad_group_service.ad_group_path(customer_id, temps.next())
    ad_group.name = f"{name} ad group"
    ad_group.campaign = campaign.resource_name
    ad_group.status = client.enums.AdGroupStatusEnum.ENABLED
    operations.append(ad_group_op)

    ad_op = client.get_type("MutateOperation")
    ad_group_ad = ad_op.ad_group_ad_operation.create
    ad_group_ad.ad_group = ad_group.resource_name
    ad_group_ad.status = client.enums.AdGroupAdStatusEnum.ENABLED
    ad_group_ad.ad.final_urls.append(final_url)
    rda = ad_group_ad.ad.responsive_display_ad
    rda.business_name = business_name
    rda.long_headline = _text_asset(client, long_headline)
    rda.headlines.extend(_text_asset(client, text) for text in headlines)
    rda.descriptions.extend(_text_asset(client, text) for text in descriptions)
    marketing = client.get_type("AdImageAsset")
    marketing.asset = marketing_image_asset
    rda.marketing_images.append(marketing)
    square = client.get_type("AdImageAsset")
    square.asset = square_marketing_image_asset
    rda.square_marketing_images.append(square)
    if logo_image_asset:
        logo = client.get_type("AdImageAsset")
        logo.asset = logo_image_asset
        rda.logo_images.append(logo)
    operations.append(ad_op)
    return operations
