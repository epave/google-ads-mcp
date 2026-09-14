"""Search campaign mutate graphs."""

from __future__ import annotations

from typing import Any

from google_ads_mcp.builders.common import (
    apply_bidding,
    budget_operation,
    default_dates,
    set_eu_political_flag,
    validate_rsa_copy,
)
from google_ads_mcp.mutate import TempIds


def _text_asset(client, text: str):
    asset = client.get_type("AdTextAsset")
    asset.text = text
    return asset


def build_search_campaign(
    client,
    customer_id: str,
    *,
    name: str,
    daily_budget: float,
    bidding_strategy: str = "MAXIMIZE_CLICKS",
    target_cpa: float | None = None,
    target_roas: float | None = None,
    final_url: str,
    headlines: list[str],
    descriptions: list[str],
    keywords: list[str] | None = None,
    ad_group_name: str | None = None,
    path1: str | None = None,
    path2: str | None = None,
    contains_eu_political: bool = False,
) -> list[Any]:
    validate_rsa_copy(headlines, descriptions, path1=path1, path2=path2)

    temps = TempIds()
    operations: list[Any] = []
    budget_op, budget_name = budget_operation(
        client, customer_id, name=f"{name} budget", daily_budget=daily_budget, temps=temps
    )
    operations.append(budget_op)

    campaign_service = client.get_service("CampaignService")
    campaign_op = client.get_type("MutateOperation")
    campaign = campaign_op.campaign_operation.create
    campaign_temp = temps.next()
    campaign.resource_name = campaign_service.campaign_path(customer_id, campaign_temp)
    campaign.name = name
    campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
    campaign.status = client.enums.CampaignStatusEnum.PAUSED
    campaign.campaign_budget = budget_name
    apply_bidding(
        client,
        campaign,
        bidding_strategy=bidding_strategy,
        target_cpa=target_cpa,
        target_roas=target_roas,
    )
    campaign.network_settings.target_google_search = True
    campaign.network_settings.target_search_network = True
    campaign.network_settings.target_partner_search_network = False
    campaign.network_settings.target_content_network = False
    set_eu_political_flag(client, campaign, contains_eu_political)
    start, _end = default_dates()
    campaign.start_date_time = start
    operations.append(campaign_op)

    ad_group_service = client.get_service("AdGroupService")
    ad_group_op = client.get_type("MutateOperation")
    ad_group = ad_group_op.ad_group_operation.create
    ad_group_temp = temps.next()
    ad_group.resource_name = ad_group_service.ad_group_path(customer_id, ad_group_temp)
    ad_group.name = ad_group_name or f"{name} ad group"
    ad_group.campaign = campaign.resource_name
    ad_group.status = client.enums.AdGroupStatusEnum.ENABLED
    ad_group.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD
    operations.append(ad_group_op)

    ad_op = client.get_type("MutateOperation")
    ad_group_ad = ad_op.ad_group_ad_operation.create
    ad_group_ad.ad_group = ad_group.resource_name
    ad_group_ad.status = client.enums.AdGroupAdStatusEnum.ENABLED
    ad_group_ad.ad.final_urls.append(final_url)
    ad_group_ad.ad.responsive_search_ad.headlines.extend(
        _text_asset(client, text) for text in headlines
    )
    ad_group_ad.ad.responsive_search_ad.descriptions.extend(
        _text_asset(client, text) for text in descriptions
    )
    if path1:
        ad_group_ad.ad.responsive_search_ad.path1 = path1
    if path2:
        ad_group_ad.ad.responsive_search_ad.path2 = path2
    operations.append(ad_op)

    for keyword in keywords or []:
        criterion_op = client.get_type("MutateOperation")
        criterion = criterion_op.ad_group_criterion_operation.create
        criterion.ad_group = ad_group.resource_name
        criterion.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
        criterion.keyword.text = keyword
        criterion.keyword.match_type = client.enums.KeywordMatchTypeEnum.BROAD
        operations.append(criterion_op)

    return operations
