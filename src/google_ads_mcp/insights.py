"""Builders and callers for Google Ads Insights services and search-term insight reports."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import proto
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message as PbMessage

from google_ads_mcp.client import get_client, run_ads_call
from google_ads_mcp.config import load_settings
from google_ads_mcp.errors import AdsError
from google_ads_mcp.ids import clean_customer_id

DEFAULT_INSIGHTS_GROUP = "google-ads-mcp"
DATE_PRESETS = frozenset(
    {
        "TODAY",
        "YESTERDAY",
        "LAST_7_DAYS",
        "LAST_14_DAYS",
        "LAST_30_DAYS",
        "THIS_WEEK_SUN_TODAY",
        "THIS_WEEK_MON_TODAY",
        "LAST_WEEK_SUN_SAT",
        "LAST_WEEK_MON_SUN",
        "THIS_MONTH",
        "LAST_MONTH",
        "LAST_BUSINESS_WEEK",
    }
)
DEFAULT_LIST_DIMENSIONS = (
    "AFFINITY_USER_INTEREST",
    "IN_MARKET_USER_INTEREST",
    "CATEGORY",
    "AGE_RANGE",
    "GENDER",
)
DEFAULT_COMPOSITION_DIMENSIONS = (
    "AFFINITY_USER_INTEREST",
    "IN_MARKET_USER_INTEREST",
    "AGE_RANGE",
    "GENDER",
    "PARENTAL_STATUS",
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_CHANNEL_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
EMERGING_GROWTH = 0.25
# Customer query keeps search_impression_share only. Top/lost-share fields stay on campaign
# rows to avoid the live incompatible-field combo on FROM customer.
CUSTOMER_IMPRESSION_SHARE_METRICS = ("metrics.search_impression_share",)
CAMPAIGN_IMPRESSION_SHARE_METRICS = CUSTOMER_IMPRESSION_SHARE_METRICS + (
    "metrics.search_top_impression_share",
    "metrics.search_absolute_top_impression_share",
    "metrics.search_budget_lost_impression_share",
    "metrics.search_rank_lost_impression_share",
    "metrics.search_budget_lost_top_impression_share",
    "metrics.search_rank_lost_top_impression_share",
    "metrics.search_budget_lost_absolute_top_impression_share",
    "metrics.search_rank_lost_absolute_top_impression_share",
)
_SIMPLE_ATTR_KEYS = (
    "entity",
    "category",
    "user_interest",
    "age_range",
    "gender",
    "location",
    "youtube_channel",
    "youtube_video",
    "parental_status",
    "income_range",
    "device",
    "user_list",
    "lineup",
)


def proto_to_plain(value: Any) -> Any:
    """Convert proto-plus / protobuf values to JSON-friendly dicts with enum names."""
    if value is None:
        return None
    if isinstance(value, proto.Enum):
        return value.name
    if isinstance(value, proto.Message):
        return _clean(type(value).to_dict(value, use_integers_for_enums=False))
    if isinstance(value, PbMessage):
        return _clean(MessageToDict(value, preserving_proto_field_name=True))
    if isinstance(value, dict):
        return _clean(value)
    if isinstance(value, list | tuple):
        return [proto_to_plain(item) for item in value]
    return value


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            name = "type" if key == "type_" else key
            nested = _clean(item)
            if nested in ("", None, [], {}):
                continue
            cleaned[name] = nested
        return cleaned
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def enum_value(client, enum_name: str, value: str):
    enum = getattr(client.enums, enum_name)
    key = str(value).strip().upper()
    if not hasattr(enum, key):
        valid = [
            name
            for name in dir(enum)
            if name.isupper() and not name.startswith("_") and name not in {"UNSPECIFIED", "UNKNOWN"}
        ]
        raise AdsError(f"Invalid {enum_name} {value!r}. Expected one of: {', '.join(sorted(valid))}")
    return getattr(enum, key)


def geo_target_constant(value: str | int | dict[str, Any]) -> str:
    if isinstance(value, dict):
        raw = value.get("geo_target_constant") or value.get("location") or value.get("id") or value.get("country")
    else:
        raw = value
    text = str(raw or "").strip()
    if text.startswith("geoTargetConstants/"):
        return text
    digits = re.sub(r"\D", "", text)
    if not digits:
        raise AdsError(f"Invalid geo target {value!r}. Use a geo target constant ID such as 2840 (United States).")
    return f"geoTargetConstants/{digits}"


def location_info(client, value: str | int | dict[str, Any]):
    loc = client.get_type("LocationInfo")
    loc.geo_target_constant = geo_target_constant(value)
    return loc


def parse_locations(client, values: list[str | int | dict[str, Any]] | None):
    return [location_info(client, item) for item in values or []]


def parse_dimensions(client, values: list[str] | None, default: tuple[str, ...] | None = None):
    names = values if values is not None else list(default or ())
    return [enum_value(client, "AudienceInsightsDimensionEnum", name) for name in names]


def _scalar(value: Any, *keys: str) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, ""):
                return value[key]
        return None
    return value


def _user_resource(customer_id: str | None, collection: str, value: Any) -> str:
    text = str(value).strip()
    if "/" in text:
        return text
    if not customer_id:
        raise AdsError(f"{collection} IDs need customer_id to build the resource name.")
    return f"customers/{clean_customer_id(customer_id)}/{collection}/{text}"


def parse_attribute(client, raw: str | dict[str, Any], *, customer_id: str | None = None):
    """Build an AudienceInsightsAttribute from a string KG id or a compact dict."""
    if isinstance(raw, str):
        attr = client.get_type("AudienceInsightsAttribute")
        attr.entity.knowledge_graph_machine_id = raw.strip()
        return attr
    if not isinstance(raw, dict):
        raise AdsError("Audience attribute must be a string knowledge-graph id or an object.")
    data = raw["attribute"] if isinstance(raw.get("attribute"), dict) else raw
    present = [key for key in _SIMPLE_ATTR_KEYS if data.get(key) not in (None, "", {})]
    if len(present) != 1:
        raise AdsError(
            "Audience attribute needs exactly one of: " + ", ".join(_SIMPLE_ATTR_KEYS) + f". Got {sorted(data)}"
        )
    kind = present[0]
    value = data[kind]
    attr = client.get_type("AudienceInsightsAttribute")
    if kind == "entity":
        attr.entity.knowledge_graph_machine_id = str(_scalar(value, "knowledge_graph_machine_id") or value).strip()
    elif kind == "category":
        attr.category.category_id = str(_scalar(value, "category_id") or value).strip()
    elif kind == "user_interest":
        attr.user_interest.user_interest_category = _user_resource(
            customer_id, "userInterests", _scalar(value, "user_interest_category") or value
        )
    elif kind == "age_range":
        attr.age_range.type_ = enum_value(client, "AgeRangeTypeEnum", _scalar(value, "type", "type_") or value)
    elif kind == "gender":
        attr.gender.type_ = enum_value(client, "GenderTypeEnum", _scalar(value, "type", "type_") or value)
    elif kind == "location":
        attr.location.geo_target_constant = geo_target_constant(value)
    elif kind == "youtube_channel":
        attr.youtube_channel.channel_id = str(_scalar(value, "channel_id") or value).strip()
    elif kind == "youtube_video":
        attr.youtube_video.video_id = str(_scalar(value, "video_id") or value).strip()
    elif kind == "parental_status":
        attr.parental_status.type_ = enum_value(
            client, "ParentalStatusTypeEnum", _scalar(value, "type", "type_") or value
        )
    elif kind == "income_range":
        attr.income_range.type_ = enum_value(client, "IncomeRangeTypeEnum", _scalar(value, "type", "type_") or value)
    elif kind == "device":
        attr.device.type_ = enum_value(client, "DeviceEnum", _scalar(value, "type", "type_") or value)
    elif kind == "user_list":
        attr.user_list.user_list = _user_resource(customer_id, "userLists", _scalar(value, "user_list") or value)
    else:
        attr.lineup.lineup_id = str(_scalar(value, "lineup_id") or value).strip()
    return attr


def parse_attributes(client, values: list[str | dict[str, Any]] | None, *, customer_id: str | None = None):
    return [parse_attribute(client, item, customer_id=customer_id) for item in values or []]


def insights_audience(
    client,
    *,
    country_locations: list[str | int | dict[str, Any]],
    customer_id: str | None = None,
    sub_country_locations: list[str | int | dict[str, Any]] | None = None,
    gender: str | None = None,
    age_ranges: list[str] | None = None,
    parental_status: str | None = None,
    income_ranges: list[str] | None = None,
    attributes: list[str | dict[str, Any]] | None = None,
    attribute_groups: list[list[str | dict[str, Any]]] | None = None,
    user_list: str | None = None,
):
    if not country_locations:
        raise AdsError("country_locations is required (geo target IDs, e.g. 2840 for the United States).")
    audience = client.get_type("InsightsAudience")
    audience.country_locations.extend(parse_locations(client, country_locations))
    if sub_country_locations:
        audience.sub_country_locations.extend(parse_locations(client, sub_country_locations))
    if gender:
        audience.gender.type_ = enum_value(client, "GenderTypeEnum", gender)
    for age in age_ranges or []:
        info = client.get_type("AgeRangeInfo")
        info.type_ = enum_value(client, "AgeRangeTypeEnum", age)
        audience.age_ranges.append(info)
    if parental_status:
        audience.parental_status.type_ = enum_value(client, "ParentalStatusTypeEnum", parental_status)
    for income in income_ranges or []:
        info = client.get_type("IncomeRangeInfo")
        info.type_ = enum_value(client, "IncomeRangeTypeEnum", income)
        audience.income_ranges.append(info)
    if user_list:
        audience.user_list.user_list = _user_resource(customer_id, "userLists", user_list)
    groups = list(attribute_groups or [])
    if attributes:
        groups.append(list(attributes))
    for group in groups:
        packed = client.get_type("InsightsAudienceAttributeGroup")
        packed.attributes.extend(parse_attributes(client, group, customer_id=customer_id))
        audience.topic_audience_combinations.append(packed)
    return audience


def audience_from_dict(client, data: dict[str, Any], *, customer_id: str | None = None):
    return insights_audience(
        client,
        country_locations=data.get("country_locations") or [],
        customer_id=customer_id,
        sub_country_locations=data.get("sub_country_locations"),
        gender=data.get("gender"),
        age_ranges=data.get("age_ranges"),
        parental_status=data.get("parental_status"),
        income_ranges=data.get("income_ranges"),
        attributes=data.get("attributes"),
        attribute_groups=data.get("attribute_groups"),
        user_list=data.get("user_list"),
    )


def date_condition(
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    if start_date or end_date:
        if not (start_date and end_date and _DATE_RE.fullmatch(start_date) and _DATE_RE.fullmatch(end_date)):
            raise AdsError("start_date and end_date must both be YYYY-MM-DD.")
        return f"segments.date BETWEEN '{start_date}' AND '{end_date}'"
    preset = (date_range or "LAST_7_DAYS").strip().upper()
    if preset not in DATE_PRESETS:
        raise AdsError(f"Invalid date_range {date_range!r}. Expected one of: {', '.join(sorted(DATE_PRESETS))}")
    return f"segments.date DURING {preset}"


def require_audience_insights() -> None:
    if not load_settings().audience_insights_enabled:
        raise AdsError(
            "Audience and YouTube creator insights are allowlisted. "
            "Set GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true after Google grants access."
        )


def account_today(time_zone: str | None = None) -> date:
    """Calendar date in the Ads account timezone when known; otherwise the host date."""
    if time_zone:
        try:
            return datetime.now(ZoneInfo(time_zone)).date()
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return date.today()


def resolve_window(
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    today: date | None = None,
) -> tuple[date, date]:
    """Inclusive current reporting window. LAST_* presets exclude today, matching Ads."""
    if start_date or end_date:
        date_condition(None, start_date, end_date)
        return date.fromisoformat(start_date or ""), date.fromisoformat(end_date or "")
    preset = (date_range or "LAST_7_DAYS").strip().upper()
    if preset not in DATE_PRESETS:
        raise AdsError(f"Invalid date_range {date_range!r}. Expected one of: {', '.join(sorted(DATE_PRESETS))}")
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    if preset == "TODAY":
        return today, today
    if preset == "YESTERDAY":
        return yesterday, yesterday
    if preset == "LAST_7_DAYS":
        return yesterday - timedelta(days=6), yesterday
    if preset == "LAST_14_DAYS":
        return yesterday - timedelta(days=13), yesterday
    if preset == "LAST_30_DAYS":
        return yesterday - timedelta(days=29), yesterday
    if preset == "THIS_MONTH":
        return today.replace(day=1), today
    if preset == "LAST_MONTH":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    if preset == "THIS_WEEK_SUN_TODAY":
        return today - timedelta(days=(today.weekday() + 1) % 7), today
    if preset == "THIS_WEEK_MON_TODAY":
        return today - timedelta(days=today.weekday()), today
    if preset == "LAST_WEEK_SUN_SAT":
        this_sun = today - timedelta(days=(today.weekday() + 1) % 7)
        return this_sun - timedelta(days=7), this_sun - timedelta(days=1)
    if preset == "LAST_WEEK_MON_SUN":
        this_mon = today - timedelta(days=today.weekday())
        return this_mon - timedelta(days=7), this_mon - timedelta(days=1)
    this_mon = today - timedelta(days=today.weekday())
    last_mon = this_mon - timedelta(days=7)
    return last_mon, last_mon + timedelta(days=4)


def previous_window(start: date, end: date) -> tuple[date, date]:
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=length - 1), prev_end


def clamp_completed_days(start: date, end: date, *, today: date | None = None) -> tuple[date, date]:
    """Impression-share metrics are not available for the current calendar day."""
    last_complete = (today or date.today()) - timedelta(days=1)
    if end > last_complete:
        end = last_complete
    if start > end:
        start = end
    return start, end


def between_condition(start: date, end: date) -> str:
    return f"segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"


def channel_condition(channel: str | None) -> str | None:
    if channel is None or channel.upper() == "ALL":
        return None
    key = channel.strip().upper()
    if not _CHANNEL_RE.fullmatch(key):
        raise AdsError(f"Invalid advertising_channel_type {channel!r}.")
    return f"campaign.advertising_channel_type = '{key}'"


def _require_month(data_month: str | None) -> str | None:
    if data_month is None or data_month == "":
        return None
    if not _MONTH_RE.fullmatch(data_month):
        raise AdsError("data_month must be YYYY-MM.")
    return data_month


def _client(client, login_customer_id: str | None):
    return client or get_client(login_customer_id)


def _apply_group(request, insights_group: str | None) -> None:
    request.customer_insights_group = insights_group or DEFAULT_INSIGHTS_GROUP


def _call(client, service_name: str, method_name: str, request):
    service = client.get_service(service_name)
    return run_ads_call(getattr(service, method_name), request=request)


def _one_of(options: dict[str, Any]) -> str:
    chosen = [name for name, value in options.items() if value]
    if len(chosen) != 1:
        raise AdsError("Provide exactly one of: " + ", ".join(options) + ".")
    return chosen[0]


def list_audience_insights_attributes(
    customer_id: str,
    *,
    dimensions: list[str] | None = None,
    query_text: str | None = None,
    country_location: str | None = None,
    location_country_filters: list[str] | None = None,
    entity_capabilities: list[str] | None = None,
    get_all_creator_attributes: bool = False,
    insights_group: str | None = None,
    client=None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    ads = _client(client, login_customer_id)
    cid = clean_customer_id(customer_id)
    dims = list(dimensions) if dimensions is not None else list(DEFAULT_LIST_DIMENSIONS)
    if query_text and "KNOWLEDGE_GRAPH" not in {item.upper() for item in dims}:
        dims.append("KNOWLEDGE_GRAPH")
    if "KNOWLEDGE_GRAPH" in {item.upper() for item in dims} and not query_text and not get_all_creator_attributes:
        raise AdsError("query_text is required when listing KNOWLEDGE_GRAPH attributes (unless get_all_creator_attributes).")
    if get_all_creator_attributes and query_text:
        raise AdsError("get_all_creator_attributes cannot be combined with query_text.")
    if get_all_creator_attributes and entity_capabilities:
        raise AdsError("get_all_creator_attributes cannot be combined with entity_capabilities.")
    request = ads.get_type("ListAudienceInsightsAttributesRequest")
    request.customer_id = cid
    request.dimensions.extend(parse_dimensions(ads, dims))
    if query_text:
        request.query_text = query_text
    _apply_group(request, insights_group)
    if country_location:
        request.youtube_reach_location = location_info(ads, country_location)
    request.location_country_filters.extend(parse_locations(ads, location_country_filters))
    if get_all_creator_attributes or entity_capabilities:
        options = request.knowledge_graph_entity_search_options
        options.get_all_creator_attributes = get_all_creator_attributes
        for capability in entity_capabilities or []:
            options.search_filter.entity_capability_filters.append(
                enum_value(ads, "InsightsKnowledgeGraphEntityCapabilitiesEnum", capability)
            )
    response = _call(ads, "AudienceInsightsService", "list_audience_insights_attributes", request)
    attributes = [proto_to_plain(item) for item in response.attributes]
    return {"count": len(attributes), "attributes": attributes}


def list_insights_eligible_dates(
    *,
    client=None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    ads = _client(client, login_customer_id)
    request = ads.get_type("ListInsightsEligibleDatesRequest")
    response = _call(ads, "AudienceInsightsService", "list_insights_eligible_dates", request)
    return proto_to_plain(response)


def generate_suggested_targeting_insights(
    customer_id: str,
    *,
    country_location: str | None = None,
    audience_description: str | None = None,
    audience: dict[str, Any] | None = None,
    marketing_objective: str | None = None,
    dimensions: list[str] | None = None,
    insights_group: str | None = None,
    client=None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    ads = _client(client, login_customer_id)
    cid = clean_customer_id(customer_id)
    request = ads.get_type("GenerateSuggestedTargetingInsightsRequest")
    request.customer_id = cid
    _apply_group(request, insights_group)
    mode = _one_of({"audience_description": audience_description, "audience": audience})
    if mode == "audience_description":
        if not country_location:
            raise AdsError("country_location is required with audience_description.")
        desc = request.audience_description
        desc.country_locations.append(location_info(ads, country_location))
        desc.audience_description = audience_description or ""
        if marketing_objective and dimensions:
            raise AdsError("Pass marketing_objective or dimensions, not both (they are a oneof).")
        if marketing_objective:
            desc.marketing_objective = enum_value(
                ads, "AudienceInsightsMarketingObjectiveEnum", marketing_objective
            )
        if dimensions:
            desc.audience_dimensions.dimensions.extend(parse_dimensions(ads, dimensions))
    else:
        definition = request.audience_definition
        definition.audience = audience_from_dict(ads, audience or {}, customer_id=cid)
    response = _call(ads, "AudienceInsightsService", "generate_suggested_targeting_insights", request)
    suggestions = [proto_to_plain(item) for item in response.suggestions]
    return {"count": len(suggestions), "suggestions": suggestions}


def generate_audience_definition(
    customer_id: str,
    country_location: str,
    audience_description: str,
    *,
    marketing_objective: str | None = None,
    insights_group: str | None = None,
    client=None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    ads = _client(client, login_customer_id)
    request = ads.get_type("GenerateAudienceDefinitionRequest")
    request.customer_id = clean_customer_id(customer_id)
    _apply_group(request, insights_group)
    request.audience_description.country_locations.append(location_info(ads, country_location))
    request.audience_description.audience_description = audience_description
    if marketing_objective:
        request.audience_description.marketing_objective = enum_value(
            ads, "AudienceInsightsMarketingObjectiveEnum", marketing_objective
        )
    return proto_to_plain(_call(ads, "AudienceInsightsService", "generate_audience_definition", request))


def generate_audience_composition_insights(
    customer_id: str,
    country_locations: list[str],
    *,
    dimensions: list[str] | None = None,
    gender: str | None = None,
    age_ranges: list[str] | None = None,
    parental_status: str | None = None,
    attributes: list[str | dict[str, Any]] | None = None,
    attribute_groups: list[list[str | dict[str, Any]]] | None = None,
    data_month: str | None = None,
    insights_group: str | None = None,
    client=None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    ads = _client(client, login_customer_id)
    cid = clean_customer_id(customer_id)
    request = ads.get_type("GenerateAudienceCompositionInsightsRequest")
    request.customer_id = cid
    _apply_group(request, insights_group)
    request.audience = insights_audience(
        ads,
        country_locations=country_locations,
        customer_id=cid,
        gender=gender,
        age_ranges=age_ranges,
        parental_status=parental_status,
        attributes=attributes,
        attribute_groups=attribute_groups,
    )
    request.dimensions.extend(parse_dimensions(ads, dimensions, DEFAULT_COMPOSITION_DIMENSIONS))
    month = _require_month(data_month)
    if month:
        request.data_month = month
    response = _call(ads, "AudienceInsightsService", "generate_audience_composition_insights", request)
    sections = [proto_to_plain(item) for item in response.sections]
    return {"count": len(sections), "sections": sections}


def generate_audience_overlap_insights(
    customer_id: str,
    country_location: str,
    primary_attribute: str | dict[str, Any],
    *,
    dimensions: list[str] | None = None,
    insights_group: str | None = None,
    client=None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    ads = _client(client, login_customer_id)
    cid = clean_customer_id(customer_id)
    request = ads.get_type("GenerateAudienceOverlapInsightsRequest")
    request.customer_id = cid
    _apply_group(request, insights_group)
    request.country_location = location_info(ads, country_location)
    request.primary_attribute = parse_attribute(ads, primary_attribute, customer_id=cid)
    request.dimensions.extend(
        parse_dimensions(ads, dimensions, ("AFFINITY_USER_INTEREST", "IN_MARKET_USER_INTEREST"))
    )
    return proto_to_plain(_call(ads, "AudienceInsightsService", "generate_audience_overlap_insights", request))


def generate_targeting_suggestion_metrics(
    customer_id: str,
    *,
    audiences: list[dict[str, Any]] | None = None,
    country_locations: list[str] | None = None,
    gender: str | None = None,
    age_ranges: list[str] | None = None,
    attributes: list[str | dict[str, Any]] | None = None,
    insights_group: str | None = None,
    client=None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    ads = _client(client, login_customer_id)
    cid = clean_customer_id(customer_id)
    request = ads.get_type("GenerateTargetingSuggestionMetricsRequest")
    request.customer_id = cid
    _apply_group(request, insights_group)
    payloads = list(audiences or [])
    if country_locations or gender or age_ranges or attributes:
        payloads.append(
            {
                "country_locations": country_locations or [],
                "gender": gender,
                "age_ranges": age_ranges,
                "attributes": attributes,
            }
        )
    if not payloads:
        raise AdsError("Provide audiences or country_locations plus optional gender/age_ranges/attributes.")
    for item in payloads:
        request.audiences.append(audience_from_dict(ads, item, customer_id=cid))
    response = _call(ads, "AudienceInsightsService", "generate_targeting_suggestion_metrics", request)
    suggestions = [proto_to_plain(item) for item in response.suggestions]
    return {"count": len(suggestions), "suggestions": suggestions}


def generate_insights_finder_report(
    customer_id: str,
    country_locations: list[str],
    *,
    attributes: list[str | dict[str, Any]] | None = None,
    gender: str | None = None,
    age_ranges: list[str] | None = None,
    insights_group: str | None = None,
    client=None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    ads = _client(client, login_customer_id)
    cid = clean_customer_id(customer_id)
    request = ads.get_type("GenerateInsightsFinderReportRequest")
    request.customer_id = cid
    _apply_group(request, insights_group)
    request.specific_audience = insights_audience(
        ads,
        country_locations=country_locations,
        customer_id=cid,
        gender=gender,
        age_ranges=age_ranges,
        attributes=attributes,
    )
    request.baseline_audience = insights_audience(ads, country_locations=country_locations, customer_id=cid)
    response = _call(ads, "AudienceInsightsService", "generate_insights_finder_report", request)
    return {"saved_report_url": response.saved_report_url}


def generate_creator_insights(
    customer_id: str,
    country_locations: list[str],
    *,
    audience_attributes: list[str | dict[str, Any]] | None = None,
    creator_attributes: list[str | dict[str, Any]] | None = None,
    topics: list[str] | None = None,
    youtube_channel_ids: list[str] | None = None,
    sub_country_locations: list[str] | None = None,
    supplemental_data: list[str] | None = None,
    insights_group: str | None = None,
    client=None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    ads = _client(client, login_customer_id)
    cid = clean_customer_id(customer_id)
    request = ads.get_type("GenerateCreatorInsightsRequest")
    request.customer_id = cid
    _apply_group(request, insights_group)
    request.country_locations.extend(parse_locations(ads, country_locations))
    request.sub_country_locations.extend(parse_locations(ads, sub_country_locations))
    for item in supplemental_data or []:
        request.supplemental_data.append(enum_value(ads, "ContentCreatorInsightsSupplementalDataEnum", item))
    mode = _one_of(
        {
            "audience_attributes": audience_attributes or creator_attributes,
            "topics": topics,
            "youtube_channel_ids": youtube_channel_ids,
        }
    )
    if mode == "topics":
        if len(country_locations) != 1:
            raise AdsError("search_topics allows exactly one country_location.")
        for topic in topics or []:
            entity = ads.get_type("AudienceInsightsEntity")
            entity.knowledge_graph_machine_id = topic.strip()
            request.search_topics.entities.append(entity)
    elif mode == "youtube_channel_ids":
        for channel_id in youtube_channel_ids or []:
            channel = ads.get_type("YouTubeChannelInfo")
            channel.channel_id = channel_id.strip()
            request.search_channels.youtube_channels.append(channel)
    else:
        request.search_attributes.audience_attributes.extend(
            parse_attributes(ads, audience_attributes, customer_id=cid)
        )
        request.search_attributes.creator_attributes.extend(
            parse_attributes(ads, creator_attributes, customer_id=cid)
        )
    response = _call(ads, "ContentCreatorInsightsService", "generate_creator_insights", request)
    creators = [proto_to_plain(item) for item in response.creator_insights]
    local_creators = [proto_to_plain(item) for item in response.local_creator_insights]
    return {"count": len(creators), "creators": creators, "local_creators": local_creators}


def generate_trending_insights(
    customer_id: str,
    country_location: str,
    *,
    audience_attributes: list[str | dict[str, Any]] | None = None,
    topics: list[str] | None = None,
    supplemental_data: list[str] | None = None,
    insights_group: str | None = None,
    client=None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    ads = _client(client, login_customer_id)
    cid = clean_customer_id(customer_id)
    request = ads.get_type("GenerateTrendingInsightsRequest")
    request.customer_id = cid
    _apply_group(request, insights_group)
    request.country_location = location_info(ads, country_location)
    for item in supplemental_data or []:
        request.supplemental_data.append(enum_value(ads, "ContentCreatorInsightsSupplementalDataEnum", item))
    mode = _one_of({"audience_attributes": audience_attributes, "topics": topics})
    if mode == "topics":
        for topic in topics or []:
            entity = ads.get_type("AudienceInsightsEntity")
            entity.knowledge_graph_machine_id = topic.strip()
            request.search_topics.entities.append(entity)
    else:
        request.search_audience.audience_attributes.extend(
            parse_attributes(ads, audience_attributes, customer_id=cid)
        )
    response = _call(ads, "ContentCreatorInsightsService", "generate_trending_insights", request)
    trends = [proto_to_plain(item) for item in response.trend_insights]
    return {"count": len(trends), "trends": trends}


def search_term_insights_query(
    *,
    campaign_id: str | None = None,
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    when: str | None = None,
) -> str:
    clause = when or date_condition(date_range, start_date, end_date)
    if campaign_id:
        return (
            "SELECT campaign_search_term_insight.id, campaign_search_term_insight.campaign_id, "
            "campaign_search_term_insight.category_label, metrics.search_volume, metrics.impressions, "
            "metrics.clicks, metrics.conversions, metrics.conversions_value "
            "FROM campaign_search_term_insight WHERE "
            f"{clause} AND campaign_search_term_insight.campaign_id = {int(campaign_id)} "
            f"ORDER BY metrics.search_volume DESC LIMIT {int(limit)}"
        )
    return (
        "SELECT customer_search_term_insight.id, customer_search_term_insight.category_label, "
        "metrics.search_volume, metrics.impressions, metrics.clicks, metrics.conversions, "
        "metrics.conversions_value FROM customer_search_term_insight WHERE "
        f"{clause} ORDER BY metrics.search_volume DESC LIMIT {int(limit)}"
    )


def search_term_insights_by_ids_query(
    *,
    insight_ids: list[int],
    campaign_id: str | None = None,
    when: str,
) -> str:
    if not insight_ids:
        raise AdsError("insight_ids must not be empty.")
    ids = ", ".join(str(int(item)) for item in insight_ids)
    if campaign_id:
        return (
            "SELECT campaign_search_term_insight.id, campaign_search_term_insight.campaign_id, "
            "campaign_search_term_insight.category_label, metrics.search_volume, metrics.impressions, "
            "metrics.clicks, metrics.conversions, metrics.conversions_value "
            "FROM campaign_search_term_insight WHERE "
            f"{when} AND campaign_search_term_insight.campaign_id = {int(campaign_id)} "
            f"AND campaign_search_term_insight.id IN ({ids})"
        )
    return (
        "SELECT customer_search_term_insight.id, customer_search_term_insight.category_label, "
        "metrics.search_volume, metrics.impressions, metrics.clicks, metrics.conversions, "
        "metrics.conversions_value FROM customer_search_term_insight WHERE "
        f"{when} AND customer_search_term_insight.id IN ({ids})"
    )


def _row_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def insight_ids_from_rows(rows: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for row in rows:
        raw = _row_value(row, "campaign_search_term_insight.id", "customer_search_term_insight.id")
        if raw is None:
            continue
        value = int(raw)
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    return ids


def search_term_insight_terms_query(
    *,
    insight_id: str,
    campaign_id: str | None = None,
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
    when: str | None = None,
) -> str:
    clause = when or date_condition(date_range, start_date, end_date)
    if campaign_id:
        return (
            "SELECT campaign_search_term_insight.id, campaign_search_term_insight.campaign_id, "
            "campaign_search_term_insight.category_label, segments.search_subcategory, "
            "segments.search_term, metrics.impressions, metrics.clicks, metrics.conversions, "
            "metrics.conversions_value FROM campaign_search_term_insight WHERE "
            f"{clause} AND campaign_search_term_insight.campaign_id = {int(campaign_id)} "
            f"AND campaign_search_term_insight.id = {int(insight_id)} "
            f"ORDER BY metrics.impressions DESC LIMIT {int(limit)}"
        )
    return (
        "SELECT customer_search_term_insight.id, customer_search_term_insight.category_label, "
        "segments.search_subcategory, segments.search_term, metrics.impressions, metrics.clicks, "
        "metrics.conversions, metrics.conversions_value FROM customer_search_term_insight WHERE "
        f"{clause} AND customer_search_term_insight.id = {int(insight_id)} "
        f"ORDER BY metrics.impressions DESC LIMIT {int(limit)}"
    )


def as_float(value: Any) -> float | None:
    """Coerce Ads metrics to float. SearchVolumeRange uses max when both bounds exist."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        if "value" in value:
            return as_float(value["value"])
        lo, hi = value.get("min"), value.get("max")
        if hi is not None:
            return float(hi)
        if lo is not None:
            return float(lo)
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _volume_bounds(row: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if not row:
        return None, None
    raw = row.get("metrics.search_volume")
    if isinstance(raw, dict) and ("min" in raw or "max" in raw):
        return as_float(raw.get("min")), as_float(raw.get("max"))
    parsed = _metric(row, "metrics.search_volume", "metrics.impressions")
    return parsed, parsed


def _metric(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        parsed = as_float(row.get(name))
        if parsed is not None:
            return parsed
    return None


def insight_row_key(row: dict[str, Any]) -> str:
    insight_id = _row_value(row, "campaign_search_term_insight.id", "customer_search_term_insight.id")
    campaign_id = _row_value(row, "campaign_search_term_insight.campaign_id")
    if campaign_id is None:
        campaign_id = "customer"
    label = _row_value(row, "campaign_search_term_insight.category_label", "customer_search_term_insight.category_label")
    if insight_id is not None:
        return f"{campaign_id}:{insight_id}"
    return f"{campaign_id}:{label or ''}"


def annotate_emerging(
    current_rows: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]],
    *,
    growth: float = EMERGING_GROWTH,
) -> list[dict[str, Any]]:
    previous = {insight_row_key(row): row for row in previous_rows}
    annotated: list[dict[str, Any]] = []
    for row in current_rows:
        prior = previous.get(insight_row_key(row))
        cur_lo, cur_hi = _volume_bounds(row)
        prior_lo, prior_hi = _volume_bounds(prior)
        volume = cur_hi if cur_hi is not None else cur_lo
        prior_volume = prior_hi if prior_hi is not None else prior_lo
        delta = None if volume is None or prior_volume is None else volume - prior_volume
        growth_rate = None
        if cur_lo is not None and prior_hi not in (None, 0):
            growth_rate = cur_lo / prior_hi - 1
        is_new = prior is None
        range_grew = growth_rate is not None and growth_rate >= growth
        annotated.append(
            {
                **row,
                "previous_search_volume": prior_volume,
                "volume_delta": delta,
                "volume_growth": None if growth_rate is None else round(growth_rate, 4),
                "is_new": is_new,
                "emerging": is_new or range_grew,
            }
        )
    return annotated


def share_pct(value: Any) -> float | None:
    parsed = as_float(value)
    if parsed is None:
        return None
    return round(parsed * 100, 1)


def impression_share_query(
    *,
    resource: str,
    when: str,
    campaign_id: str | None = None,
    include_paused: bool = False,
    channel: str | None = "SEARCH",
    limit: int = 100,
) -> str:
    fields = ["campaign.id", "campaign.name", "campaign.status", "campaign.advertising_channel_type"]
    metrics = CAMPAIGN_IMPRESSION_SHARE_METRICS
    if resource == "customer":
        fields = ["customer.id", "customer.descriptive_name"]
        metrics = CUSTOMER_IMPRESSION_SHARE_METRICS
    fields.extend(metrics)
    conditions = [when]
    if resource == "campaign":
        statuses = "('ENABLED', 'PAUSED')" if include_paused else "('ENABLED')"
        conditions.append(f"campaign.status IN {statuses}")
        if campaign_id:
            conditions.append(f"campaign.id = {int(campaign_id)}")
        extra = channel_condition(channel)
        if extra:
            conditions.append(extra)
    query = f"SELECT {', '.join(fields)} FROM {resource} WHERE " + " AND ".join(conditions)
    if resource == "campaign":
        query += f" ORDER BY campaign.name LIMIT {int(limit)}"
    else:
        query += " LIMIT 1"
    return query


def _share_block(row: dict[str, Any] | None) -> dict[str, float | None]:
    row = row or {}
    return {
        "impression_share": share_pct(row.get("metrics.search_impression_share")),
        "top_impression_share": share_pct(row.get("metrics.search_top_impression_share")),
        "absolute_top_impression_share": share_pct(row.get("metrics.search_absolute_top_impression_share")),
        "lost_to_budget": share_pct(row.get("metrics.search_budget_lost_impression_share")),
        "lost_to_rank": share_pct(row.get("metrics.search_rank_lost_impression_share")),
        "top_lost_to_budget": share_pct(row.get("metrics.search_budget_lost_top_impression_share")),
        "top_lost_to_rank": share_pct(row.get("metrics.search_rank_lost_top_impression_share")),
        "absolute_top_lost_to_budget": share_pct(row.get("metrics.search_budget_lost_absolute_top_impression_share")),
        "absolute_top_lost_to_rank": share_pct(row.get("metrics.search_rank_lost_absolute_top_impression_share")),
    }


def _share_deltas(current: dict[str, float | None], previous: dict[str, float | None]) -> dict[str, float | None]:
    return {
        key: None if current[key] is None or previous[key] is None else round(current[key] - previous[key], 1)
        for key in current
    }


def summarize_impression_share(
    *,
    current_account: dict[str, Any] | None,
    previous_account: dict[str, Any] | None,
    current_campaigns: list[dict[str, Any]],
    previous_campaigns: list[dict[str, Any]],
) -> dict[str, Any]:
    account = _share_block(current_account)
    previous = _share_block(previous_account)
    prev_by_id = {
        int(row["campaign.id"]): row for row in previous_campaigns if row.get("campaign.id") is not None
    }
    campaigns: list[dict[str, Any]] = []
    alerts: list[str] = []
    for row in current_campaigns:
        current = _share_block(row)
        prior_row = prev_by_id.get(int(row["campaign.id"])) if row.get("campaign.id") is not None else None
        item = {
            "campaign_id": row.get("campaign.id"),
            "name": row.get("campaign.name"),
            "status": row.get("campaign.status"),
            "channel": row.get("campaign.advertising_channel_type"),
            **current,
            "deltas": _share_deltas(current, _share_block(prior_row)),
        }
        campaigns.append(item)
        name = item["name"] or item["campaign_id"]
        if (item["lost_to_budget"] or 0) >= 20:
            alerts.append(f"{name}: lost {item['lost_to_budget']}% impression share to budget")
        if (item["lost_to_rank"] or 0) >= 30:
            alerts.append(f"{name}: lost {item['lost_to_rank']}% impression share to rank")
    if (account["lost_to_budget"] or 0) >= 20:
        alerts.insert(0, f"Account lost {account['lost_to_budget']}% impression share to budget")
    if (account["lost_to_rank"] or 0) >= 30:
        alerts.insert(0, f"Account lost {account['lost_to_rank']}% impression share to rank")
    return {
        "account": {**account, "deltas": _share_deltas(account, previous)},
        "campaigns": campaigns,
        "alerts": alerts,
    }
