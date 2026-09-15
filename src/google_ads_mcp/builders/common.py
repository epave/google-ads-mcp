"""Shared campaign mutate builders."""

from __future__ import annotations

from datetime import date, timedelta

from google_ads_mcp.money import to_micros
from google_ads_mcp.mutate import TempIds

RSA_HEADLINE_MAX_CHARS = 30
RSA_DESCRIPTION_MAX_CHARS = 90
RSA_PATH_MAX_CHARS = 15
RSA_MIN_HEADLINES = 3
RSA_MAX_HEADLINES = 15
RSA_MIN_DESCRIPTIONS = 2
RSA_MAX_DESCRIPTIONS = 4
DISPLAY_HEADLINE_MAX_CHARS = 30
DISPLAY_LONG_HEADLINE_MAX_CHARS = 90
DISPLAY_DESCRIPTION_MAX_CHARS = 90
PMAX_BUSINESS_NAME_MAX_CHARS = 25


def _assert_max_len(label: str, values: list[str], max_chars: int) -> None:
    for index, text in enumerate(values, 1):
        if len(text) > max_chars:
            raise ValueError(
                f"{label} {index} exceeds {max_chars} characters ({len(text)}): {text!r}"
            )


def validate_rsa_copy(
    headlines: list[str],
    descriptions: list[str],
    *,
    path1: str | None = None,
    path2: str | None = None,
) -> None:
    if len(headlines) < RSA_MIN_HEADLINES:
        raise ValueError(
            f"Search RSA requires at least {RSA_MIN_HEADLINES} headlines "
            f"(max {RSA_HEADLINE_MAX_CHARS} chars each)."
        )
    if len(headlines) > RSA_MAX_HEADLINES:
        raise ValueError(f"Search RSA allows at most {RSA_MAX_HEADLINES} headlines.")
    if len(descriptions) < RSA_MIN_DESCRIPTIONS:
        raise ValueError(
            f"Search RSA requires at least {RSA_MIN_DESCRIPTIONS} descriptions "
            f"(max {RSA_DESCRIPTION_MAX_CHARS} chars each)."
        )
    if len(descriptions) > RSA_MAX_DESCRIPTIONS:
        raise ValueError(f"Search RSA allows at most {RSA_MAX_DESCRIPTIONS} descriptions.")
    _assert_max_len("Headline", headlines, RSA_HEADLINE_MAX_CHARS)
    _assert_max_len("Description", descriptions, RSA_DESCRIPTION_MAX_CHARS)
    if path1 and len(path1) > RSA_PATH_MAX_CHARS:
        raise ValueError(f"path1 exceeds {RSA_PATH_MAX_CHARS} characters ({len(path1)}).")
    if path2 and len(path2) > RSA_PATH_MAX_CHARS:
        raise ValueError(f"path2 exceeds {RSA_PATH_MAX_CHARS} characters ({len(path2)}).")


def validate_display_copy(
    headlines: list[str],
    descriptions: list[str],
    long_headline: str,
) -> None:
    if len(headlines) < 1:
        raise ValueError("Display ads require at least 1 headline.")
    if len(descriptions) < 1:
        raise ValueError("Display ads require at least 1 description.")
    _assert_max_len("Headline", headlines, DISPLAY_HEADLINE_MAX_CHARS)
    _assert_max_len("Description", descriptions, DISPLAY_DESCRIPTION_MAX_CHARS)
    if len(long_headline) > DISPLAY_LONG_HEADLINE_MAX_CHARS:
        raise ValueError(
            f"Long headline exceeds {DISPLAY_LONG_HEADLINE_MAX_CHARS} characters "
            f"({len(long_headline)})."
        )


def validate_pmax_copy(
    headlines: list[str],
    descriptions: list[str],
    long_headline: str,
    business_name: str,
) -> None:
    if len(headlines) < RSA_MIN_HEADLINES:
        raise ValueError("Performance Max requires at least 3 headlines.")
    if len(descriptions) < RSA_MIN_DESCRIPTIONS:
        raise ValueError("Performance Max requires at least 2 descriptions.")
    _assert_max_len("Headline", headlines, RSA_HEADLINE_MAX_CHARS)
    _assert_max_len("Description", descriptions, RSA_DESCRIPTION_MAX_CHARS)
    if len(long_headline) > DISPLAY_LONG_HEADLINE_MAX_CHARS:
        raise ValueError(
            f"Long headline exceeds {DISPLAY_LONG_HEADLINE_MAX_CHARS} characters "
            f"({len(long_headline)})."
        )
    if len(business_name) > PMAX_BUSINESS_NAME_MAX_CHARS:
        raise ValueError(
            f"Business name exceeds {PMAX_BUSINESS_NAME_MAX_CHARS} characters "
            f"({len(business_name)})."
        )


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
    # Google Ads API v21+ Campaign.start_date_time / end_date_time:
    # customer's timezone, "yyyy-MM-dd HH:mm:ss".
    start_str = start.strftime("%Y-%m-%d 00:00:00")
    if duration_days is None:
        return start_str, None
    end = start + timedelta(days=duration_days)
    return start_str, end.strftime("%Y-%m-%d 23:59:59")
