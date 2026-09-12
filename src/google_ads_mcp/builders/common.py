"""Shared campaign mutate builders."""

from __future__ import annotations

from datetime import date, timedelta

from google_ads_mcp.money import to_micros
from google_ads_mcp.mutate import TempIds


def set_eu_political_flag(client, campaign, contains_eu_political: bool) -> None:
    status = (
        client.enums.EuPoliticalAdvertisingStatusEnum.CONTAINS_EU_POLITICAL_ADVERTISING
        if contains_eu_political
        else client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    )
    campaign.contains_eu_political_advertising = status


def apply_bidding(
    client,
    campaign,
    *,
    bidding_strategy: str,
    target_cpa: float | None = None,
    target_roas: float | None = None,
) -> None:
    strategy = bidding_strategy.strip().upper()
    if strategy in {"MANUAL_CPC", "MANUALCPC"}:
        campaign.manual_cpc = client.get_type("ManualCpc")
        return
    if strategy in {"MAXIMIZE_CLICKS", "TARGET_SPEND", "MAXIMIZECLICKS"}:
        campaign.target_spend.target_spend_micros = 0
        return
    if strategy in {"MAXIMIZE_CONVERSIONS", "MAXIMIZECONVERSIONS"}:
        campaign.maximize_conversions = client.get_type("MaximizeConversions")
        if target_cpa is not None:
            campaign.maximize_conversions.target_cpa_micros = to_micros(target_cpa)
        return
    if strategy in {"TARGET_CPA", "TARGETCPA"}:
        campaign.target_cpa.target_cpa_micros = to_micros(target_cpa or 0)
        return
    if strategy in {"MAXIMIZE_CONVERSION_VALUE", "TARGET_ROAS", "MAXIMIZECONVERSIONVALUE"}:
        campaign.maximize_conversion_value = client.get_type("MaximizeConversionValue")
        if target_roas is not None:
            campaign.maximize_conversion_value.target_roas = target_roas
        return
    raise ValueError(
        f"Unsupported bidding_strategy {bidding_strategy!r}. "
        "Use MANUAL_CPC, MAXIMIZE_CLICKS, MAXIMIZE_CONVERSIONS, TARGET_CPA, "
        "or MAXIMIZE_CONVERSION_VALUE."
    )


def budget_operation(
    client,
    customer_id: str,
    *,
    name: str,
    daily_budget: float,
    temps: TempIds,
    explicitly_shared: bool = False,
):
    budget_service = client.get_service("CampaignBudgetService")
    op = client.get_type("MutateOperation")
    budget = op.campaign_budget_operation.create
    temp_id = temps.next()
    budget.resource_name = budget_service.campaign_budget_path(customer_id, temp_id)
    budget.name = name
    budget.amount_micros = to_micros(daily_budget)
    budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
    budget.explicitly_shared = explicitly_shared
    return op, budget.resource_name


def default_dates(start_days_from_now: int = 1, duration_days: int | None = None) -> tuple[str, str | None]:
    start = date.today() + timedelta(days=start_days_from_now)
    start_str = start.strftime("%Y%m%d 00:00:00")
    if duration_days is None:
        return start_str, None
    end = start + timedelta(days=duration_days)
    return start_str, end.strftime("%Y%m%d 23:59:59")
