"""Performance Max campaign mutate graphs."""

from __future__ import annotations

from typing import Any

from google_ads_mcp.builders.common import (
    apply_bidding,
    budget_operation,
    default_dates,
    set_eu_political_flag,
    validate_pmax_copy,
)
from google_ads_mcp.mutate import TempIds


def _link_asset_group_asset(client, asset_group_name: str, asset_name: str, field_type):
    op = client.get_type("MutateOperation")
    link = op.asset_group_asset_operation.create
    link.asset_group = asset_group_name
    link.asset = asset_name
    link.field_type = field_type
    return op


def _link_campaign_asset(client, campaign_name: str, asset_name: str, field_type):
    op = client.get_type("MutateOperation")
    link = op.campaign_asset_operation.create
    link.campaign = campaign_name
    link.asset = asset_name
    link.field_type = field_type
    return op


def _text_asset_op(client, customer_id: str, text: str, temps: TempIds):
    asset_service = client.get_service("AssetService")
    op = client.get_type("MutateOperation")
    asset = op.asset_operation.create
    asset.resource_name = asset_service.asset_path(customer_id, temps.next())
    asset.text_asset.text = text
    return op, asset.resource_name


def build_pmax_campaign(
    client,
    customer_id: str,
    *,
    name: str,
    daily_budget: float,
    final_url: str,
    business_name: str,
    headlines: list[str],
    long_headline: str,
    descriptions: list[str],
    logo_asset: str,
    marketing_image_asset: str,
    square_marketing_image_asset: str,
    bidding_strategy: str = "MAXIMIZE_CONVERSIONS",
    target_cpa: float | None = None,
    target_roas: float | None = None,
    brand_guidelines_enabled: bool = True,
    contains_eu_political: bool = False,
) -> list[Any]:
    validate_pmax_copy(headlines, descriptions, long_headline, business_name)

    temps = TempIds()
    operations: list[Any] = []
    budget_op, budget_name = budget_operation(
        client,
        customer_id,
        name=f"{name} budget",
        daily_budget=daily_budget,
        temps=temps,
        explicitly_shared=False,
    )
    operations.append(budget_op)

    campaign_service = client.get_service("CampaignService")
    campaign_op = client.get_type("MutateOperation")
    campaign = campaign_op.campaign_operation.create
    campaign.resource_name = campaign_service.campaign_path(customer_id, temps.next())
    campaign.name = name
    campaign.status = client.enums.CampaignStatusEnum.PAUSED
    campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
    campaign.campaign_budget = budget_name
    apply_bidding(
        client,
        campaign,
        bidding_strategy=bidding_strategy,
        target_cpa=target_cpa,
        target_roas=target_roas,
    )
    if hasattr(campaign, "brand_guidelines_enabled"):
        campaign.brand_guidelines_enabled = brand_guidelines_enabled
    set_eu_political_flag(client, campaign, contains_eu_political)
    campaign.start_date_time = default_dates()[0]
    operations.append(campaign_op)

    asset_group_service = client.get_service("AssetGroupService")
    asset_group_op = client.get_type("MutateOperation")
    asset_group = asset_group_op.asset_group_operation.create
    asset_group.resource_name = asset_group_service.asset_group_path(customer_id, temps.next())
    asset_group.name = f"{name} asset group"
    asset_group.campaign = campaign.resource_name
    asset_group.final_urls.append(final_url)
    asset_group.status = client.enums.AssetGroupStatusEnum.ENABLED
    operations.append(asset_group_op)

    business_op, business_name_asset = _text_asset_op(client, customer_id, business_name, temps)
    operations.append(business_op)
    long_op, long_asset = _text_asset_op(client, customer_id, long_headline, temps)
    operations.append(long_op)

    field = client.enums.AssetFieldTypeEnum
    if brand_guidelines_enabled:
        operations.append(
            _link_campaign_asset(client, campaign.resource_name, business_name_asset, field.BUSINESS_NAME)
        )
        operations.append(_link_campaign_asset(client, campaign.resource_name, logo_asset, field.LOGO))
    else:
        operations.append(
            _link_asset_group_asset(
                client, asset_group.resource_name, business_name_asset, field.BUSINESS_NAME
            )
        )
        operations.append(
            _link_asset_group_asset(client, asset_group.resource_name, logo_asset, field.LOGO)
        )

    operations.append(
        _link_asset_group_asset(
            client, asset_group.resource_name, marketing_image_asset, field.MARKETING_IMAGE
        )
    )
    operations.append(
        _link_asset_group_asset(
            client, asset_group.resource_name, square_marketing_image_asset, field.SQUARE_MARKETING_IMAGE
        )
    )
    operations.append(
        _link_asset_group_asset(client, asset_group.resource_name, long_asset, field.LONG_HEADLINE)
    )
    for headline in headlines:
        hop, href = _text_asset_op(client, customer_id, headline, temps)
        operations.append(hop)
        operations.append(
            _link_asset_group_asset(client, asset_group.resource_name, href, field.HEADLINE)
        )
    for description in descriptions:
        dop, dref = _text_asset_op(client, customer_id, description, temps)
        operations.append(dop)
        operations.append(
            _link_asset_group_asset(client, asset_group.resource_name, dref, field.DESCRIPTION)
        )
    return operations


def build_asset_group_text_ops(
    client,
    customer_id: str,
    *,
    asset_group_id: str,
    headlines: list[str] | None = None,
    descriptions: list[str] | None = None,
) -> list[Any]:
    """Add headline/description text assets to an existing asset group."""
    headlines = headlines or []
    descriptions = descriptions or []
    if not headlines and not descriptions:
        raise ValueError("Provide at least one headline or description.")
    temps = TempIds()
    service = client.get_service("AssetGroupService")
    asset_group_name = service.asset_group_path(customer_id, asset_group_id)
    field = client.enums.AssetFieldTypeEnum
    operations: list[Any] = []
    for headline in headlines:
        hop, href = _text_asset_op(client, customer_id, headline, temps)
        operations.append(hop)
        operations.append(_link_asset_group_asset(client, asset_group_name, href, field.HEADLINE))
    for description in descriptions:
        dop, dref = _text_asset_op(client, customer_id, description, temps)
        operations.append(dop)
        operations.append(_link_asset_group_asset(client, asset_group_name, dref, field.DESCRIPTION))
    return operations
