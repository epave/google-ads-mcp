"""Create and expand Search, Display, and Performance Max campaigns."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp.builders.display import build_display_campaign
from google_ads_mcp.builders.pmax import build_pmax_campaign
from google_ads_mcp.builders.search import build_search_campaign
from google_ads_mcp.client import get_client, run_ads_call
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.mutate import mutate
from google_ads_mcp.safety import SafetyGate
from google_ads_mcp.store import get_store


def _gate() -> SafetyGate:
    return SafetyGate()


def create_search_campaign(
    customer_id: str,
    name: str,
    daily_budget: float,
    final_url: str,
    headlines: list[str],
    descriptions: list[str],
    keywords: list[str] | None = None,
    bidding_strategy: str = "MAXIMIZE_CLICKS",
    target_cpa: float | None = None,
    target_roas: float | None = None,
    ad_group_name: str | None = None,
    path1: str | None = None,
    path2: str | None = None,
    contains_eu_political: bool = False,
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    """Create a paused Search campaign with budget, ad group, RSA, and keywords.

    Requires at least 3 headlines (≤30 chars) and 2 descriptions (≤90 chars).
    The campaign is always created PAUSED. Enable it separately after review.
    """
    cid = clean_customer_id(customer_id)
    description = (
        f"Create PAUSED Search campaign '{name}' with daily budget {daily_budget}, "
        f"{len(headlines)} headlines, {len(keywords or [])} keywords, URL {final_url}"
    )
    auth = _gate().authorize_write(
        tool="create_search_campaign",
        customer_id=cid,
        args={
            "name": name,
            "daily_budget": daily_budget,
            "final_url": final_url,
            "headlines": headlines,
            "descriptions": descriptions,
            "keywords": keywords or [],
            "bidding_strategy": bidding_strategy,
            "target_cpa": target_cpa,
            "target_roas": target_roas,
            "ad_group_name": ad_group_name,
            "path1": path1,
            "path2": path2,
            "contains_eu_political": contains_eu_political,
        },
        description=description,
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    client = get_client()
    operations = build_search_campaign(
        client,
        cid,
        name=name,
        daily_budget=daily_budget,
        bidding_strategy=bidding_strategy,
        target_cpa=target_cpa,
        target_roas=target_roas,
        final_url=final_url,
        headlines=headlines,
        descriptions=descriptions,
        keywords=keywords,
        ad_group_name=ad_group_name,
        path1=path1,
        path2=path2,
        contains_eu_political=contains_eu_political,
    )
    result = mutate(cid, operations, client=client)
    get_store().record_audit(
        tool="create_search_campaign",
        action="apply",
        customer_id=cid,
        payload={"name": name, "result": result},
    )
    return {"status": "applied", "created_paused": True, **result}


def create_display_campaign(
    customer_id: str,
    name: str,
    daily_budget: float,
    final_url: str,
    business_name: str,
    headlines: list[str],
    long_headline: str,
    descriptions: list[str],
    marketing_image_asset: str,
    square_marketing_image_asset: str,
    logo_image_asset: str | None = None,
    bidding_strategy: str = "MAXIMIZE_CONVERSIONS",
    target_cpa: float | None = None,
    contains_eu_political: bool = False,
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    """Create a paused Display campaign with a Responsive Display Ad.

    Upload images first with upload_image_asset. Marketing image must be 1.91:1
    (min 600x314). Square marketing image must be 1:1 (min 300x300).
    """
    cid = clean_customer_id(customer_id)
    description = f"Create PAUSED Display campaign '{name}' with daily budget {daily_budget}"
    auth = _gate().authorize_write(
        tool="create_display_campaign",
        customer_id=cid,
        args={
            "name": name,
            "daily_budget": daily_budget,
            "final_url": final_url,
            "business_name": business_name,
            "headlines": headlines,
            "long_headline": long_headline,
            "descriptions": descriptions,
            "marketing_image_asset": marketing_image_asset,
            "square_marketing_image_asset": square_marketing_image_asset,
            "logo_image_asset": logo_image_asset,
            "bidding_strategy": bidding_strategy,
            "target_cpa": target_cpa,
            "contains_eu_political": contains_eu_political,
        },
        description=description,
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    client = get_client()
    operations = build_display_campaign(
        client,
        cid,
        name=name,
        daily_budget=daily_budget,
        bidding_strategy=bidding_strategy,
        target_cpa=target_cpa,
        final_url=final_url,
        business_name=business_name,
        headlines=headlines,
        long_headline=long_headline,
        descriptions=descriptions,
        marketing_image_asset=marketing_image_asset,
        square_marketing_image_asset=square_marketing_image_asset,
        logo_image_asset=logo_image_asset,
        contains_eu_political=contains_eu_political,
    )
    result = mutate(cid, operations, client=client)
    get_store().record_audit(
        tool="create_display_campaign", action="apply", customer_id=cid, payload={"name": name}
    )
    return {"status": "applied", "created_paused": True, **result}


def create_pmax_campaign(
    customer_id: str,
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
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    """Create a paused standard Performance Max campaign (not retail/Merchant Center).

    Requires a logo asset plus landscape and square marketing images. Upload those
    with upload_image_asset first. Brand guidelines are on by default.
    """
    cid = clean_customer_id(customer_id)
    description = f"Create PAUSED Performance Max campaign '{name}' with daily budget {daily_budget}"
    auth = _gate().authorize_write(
        tool="create_pmax_campaign",
        customer_id=cid,
        args={
            "name": name,
            "daily_budget": daily_budget,
            "final_url": final_url,
            "business_name": business_name,
            "headlines": headlines,
            "long_headline": long_headline,
            "descriptions": descriptions,
            "logo_asset": logo_asset,
            "marketing_image_asset": marketing_image_asset,
            "square_marketing_image_asset": square_marketing_image_asset,
            "bidding_strategy": bidding_strategy,
            "target_cpa": target_cpa,
            "target_roas": target_roas,
            "brand_guidelines_enabled": brand_guidelines_enabled,
            "contains_eu_political": contains_eu_political,
        },
        description=description,
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    client = get_client()
    operations = build_pmax_campaign(
        client,
        cid,
        name=name,
        daily_budget=daily_budget,
        final_url=final_url,
        business_name=business_name,
        headlines=headlines,
        long_headline=long_headline,
        descriptions=descriptions,
        logo_asset=logo_asset,
        marketing_image_asset=marketing_image_asset,
        square_marketing_image_asset=square_marketing_image_asset,
        bidding_strategy=bidding_strategy,
        target_cpa=target_cpa,
        target_roas=target_roas,
        brand_guidelines_enabled=brand_guidelines_enabled,
        contains_eu_political=contains_eu_political,
    )
    result = mutate(cid, operations, client=client)
    get_store().record_audit(
        tool="create_pmax_campaign", action="apply", customer_id=cid, payload={"name": name}
    )
    return {"status": "applied", "created_paused": True, **result}


def add_keywords(
    customer_id: str,
    ad_group_id: str,
    keywords: list[str],
    match_type: str = "BROAD",
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    """Add keywords to an existing ad group. match_type: BROAD, PHRASE, or EXACT."""
    cid = clean_customer_id(customer_id)
    auth = _gate().authorize_write(
        tool="add_keywords",
        customer_id=cid,
        args={"ad_group_id": str(ad_group_id), "keywords": keywords, "match_type": match_type},
        description=f"Add {len(keywords)} {match_type} keywords to ad group {ad_group_id}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    client = get_client()
    service = client.get_service("AdGroupCriterionService")
    ad_group_service = client.get_service("AdGroupService")
    match = getattr(client.enums.KeywordMatchTypeEnum, match_type.upper())
    operations = []
    for text in keywords:
        operation = client.get_type("AdGroupCriterionOperation")
        criterion = operation.create
        criterion.ad_group = ad_group_service.ad_group_path(cid, ad_group_id)
        criterion.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
        criterion.keyword.text = text
        criterion.keyword.match_type = match
        operations.append(operation)
    response = run_ads_call(service.mutate_ad_group_criteria, customer_id=cid, operations=operations)
    names = [item.resource_name for item in response.results]
    get_store().record_audit(
        tool="add_keywords", action="apply", customer_id=cid, payload={"keywords": keywords}
    )
    return {"status": "applied", "resource_names": names}


def create_ad_group(
    customer_id: str,
    campaign_id: str,
    name: str,
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    """Create an ENABLED ad group under an existing campaign."""
    cid = clean_customer_id(customer_id)
    auth = _gate().authorize_write(
        tool="create_ad_group",
        customer_id=cid,
        args={"campaign_id": str(campaign_id), "name": name},
        description=f"Create ad group '{name}' in campaign {campaign_id}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    client = get_client()
    service = client.get_service("AdGroupService")
    campaign_service = client.get_service("CampaignService")
    operation = client.get_type("AdGroupOperation")
    ad_group = operation.create
    ad_group.name = name
    ad_group.campaign = campaign_service.campaign_path(cid, campaign_id)
    ad_group.status = client.enums.AdGroupStatusEnum.ENABLED
    response = run_ads_call(service.mutate_ad_groups, customer_id=cid, operations=[operation])
    resource_name = response.results[0].resource_name
    get_store().record_audit(
        tool="create_ad_group", action="apply", customer_id=cid, payload={"name": name}
    )
    return {"status": "applied", "resource_name": resource_name}


def register(mcp: FastMCP) -> None:
    mcp.tool(create_search_campaign)
    mcp.tool(create_display_campaign)
    mcp.tool(create_pmax_campaign)
    mcp.tool(add_keywords)
    mcp.tool(create_ad_group)
