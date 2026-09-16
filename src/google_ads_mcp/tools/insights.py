"""Search terms, Ads Insights services, change history, recommendations, and local audit."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp import insights as ads_insights
from google_ads_mcp.config import load_settings
from google_ads_mcp.gaql import search
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.store import get_store


def get_search_terms(
    customer_id: str,
    campaign_id: str | None = None,
    limit: int = 50,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Top raw search terms for the last 7 days from search_term_view.

    For category-level Search term insights (PMax included), use
    get_search_term_insights instead.
    """
    cid = clean_customer_id(customer_id)
    conditions = ["segments.date DURING LAST_7_DAYS"]
    if campaign_id:
        conditions.append(f"campaign.id = {int(campaign_id)}")
    rows = search(
        cid,
        "SELECT search_term_view.search_term, campaign.id, campaign.name, "
        "metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions "
        "FROM search_term_view WHERE "
        + " AND ".join(conditions)
        + f" ORDER BY metrics.clicks DESC LIMIT {int(limit)}",
        login_customer_id=login_customer_id,
    )
    return {"count": len(rows), "search_terms": rows}


def get_search_term_insights(
    customer_id: str,
    campaign_id: str | None = None,
    date_range: str = "LAST_7_DAYS",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Search term insight categories with volume, clicks, conversions, and emerging demand.

    Pass campaign_id for campaign_search_term_insight (needed for Performance Max).
    Omit it for account-level customer_search_term_insight. Then call
    get_search_term_insight_terms with a returned insight id to list terms
    inside one category. Emerging categories are new versus the previous equal
    window, or grew search volume by 25%+.
    """
    cid = clean_customer_id(customer_id)
    current_start, current_end = ads_insights.resolve_window(date_range, start_date, end_date)
    current_when = ads_insights.between_condition(current_start, current_end)
    query = ads_insights.search_term_insights_query(
        campaign_id=campaign_id,
        limit=limit,
        when=current_when,
    )
    rows = search(cid, query, login_customer_id=login_customer_id)
    prev_start, prev_end = ads_insights.previous_window(current_start, current_end)
    previous_query = ads_insights.search_term_insights_query(
        campaign_id=campaign_id,
        limit=max(int(limit), 200),
        when=ads_insights.between_condition(prev_start, prev_end),
    )
    previous_rows = search(cid, previous_query, login_customer_id=login_customer_id)
    insights = ads_insights.annotate_emerging(rows, previous_rows)
    emerging = [row for row in insights if row.get("emerging")]
    return {
        "count": len(insights),
        "current_period": {"start": current_start.isoformat(), "end": current_end.isoformat()},
        "previous_period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        "emerging_count": len(emerging),
        "emerging": emerging,
        "insights": insights,
        "query": query,
    }


def get_search_term_insight_terms(
    customer_id: str,
    insight_id: str,
    campaign_id: str | None = None,
    date_range: str = "LAST_7_DAYS",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Search terms inside one Search term insights category.

    campaign_id plus insight_id is required for campaign-level / PMax terms.
    Account-level categories only need insight_id.
    """
    cid = clean_customer_id(customer_id)
    query = ads_insights.search_term_insight_terms_query(
        insight_id=insight_id,
        campaign_id=campaign_id,
        date_range=date_range,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    rows = search(cid, query, login_customer_id=login_customer_id)
    return {"count": len(rows), "search_terms": rows, "query": query}


def get_impression_share_summary(
    customer_id: str,
    campaign_id: str | None = None,
    date_range: str = "LAST_7_DAYS",
    start_date: str | None = None,
    end_date: str | None = None,
    include_paused: bool = False,
    limit: int = 100,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Search impression share, top/absolute-top share, and lost share from budget vs rank.

    Returns account and campaign rows for the current window plus deltas versus the
    previous equal-length period. Shares are percents (0-100). Search campaigns only
    populate these metrics; others may return null.
    """
    cid = clean_customer_id(customer_id)
    current_start, current_end = ads_insights.resolve_window(date_range, start_date, end_date)
    prev_start, prev_end = ads_insights.previous_window(current_start, current_end)
    current_when = ads_insights.between_condition(current_start, current_end)
    previous_when = ads_insights.between_condition(prev_start, prev_end)
    account_now = search(
        cid,
        ads_insights.impression_share_query(resource="customer", when=current_when),
        login_customer_id=login_customer_id,
    )
    account_prev = search(
        cid,
        ads_insights.impression_share_query(resource="customer", when=previous_when),
        login_customer_id=login_customer_id,
    )
    campaigns_now = search(
        cid,
        ads_insights.impression_share_query(
            resource="campaign",
            when=current_when,
            campaign_id=campaign_id,
            include_paused=include_paused,
            limit=limit,
        ),
        login_customer_id=login_customer_id,
    )
    campaigns_prev = search(
        cid,
        ads_insights.impression_share_query(
            resource="campaign",
            when=previous_when,
            campaign_id=campaign_id,
            include_paused=include_paused,
            limit=limit,
        ),
        login_customer_id=login_customer_id,
    )
    summary = ads_insights.summarize_impression_share(
        current_account=account_now[0] if account_now else None,
        previous_account=account_prev[0] if account_prev else None,
        current_campaigns=campaigns_now,
        previous_campaigns=campaigns_prev,
    )
    return {
        "customer_id": cid,
        "current_period": {"start": current_start.isoformat(), "end": current_end.isoformat()},
        "previous_period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        **summary,
    }


def get_change_events(
    customer_id: str, limit: int = 50, login_customer_id: str | None = None
) -> dict[str, Any]:
    """Recent account change events (last 7 days)."""
    cid = clean_customer_id(customer_id)
    rows = search(
        cid,
        "SELECT change_event.change_date_time, change_event.user_email, "
        "change_event.client_type, change_event.change_resource_type, "
        "change_event.resource_change_operation, change_event.resource_name "
        "FROM change_event WHERE change_event.change_date_time DURING LAST_7_DAYS "
        f"ORDER BY change_event.change_date_time DESC LIMIT {int(limit)}",
        login_customer_id=login_customer_id,
    )
    return {"count": len(rows), "changes": rows}


def get_recommendations(
    customer_id: str, limit: int = 25, login_customer_id: str | None = None
) -> dict[str, Any]:
    """Google Ads optimization recommendations that are still pending."""
    cid = clean_customer_id(customer_id)
    rows = search(
        cid,
        "SELECT recommendation.resource_name, recommendation.type, recommendation.campaign, "
        "recommendation.impact FROM recommendation WHERE recommendation.dismissed = FALSE "
        f"LIMIT {int(limit)}",
        login_customer_id=login_customer_id,
    )
    return {"count": len(rows), "recommendations": rows}


def get_local_audit(limit: int = 20) -> dict[str, Any]:
    """Read recent mutations and previews stored in the local DuckDB 2.0 audit log."""
    return {"events": get_store().list_recent_audit(limit=limit)}


def list_audience_insights_attributes(
    customer_id: str,
    dimensions: list[str] | None = None,
    query_text: str | None = None,
    country_location: str | None = None,
    location_country_filters: list[str] | None = None,
    entity_capabilities: list[str] | None = None,
    get_all_creator_attributes: bool = False,
    insights_group: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """List audience attributes you can pass into other Insights tools.

    AudienceInsightsService is allowlisted. dimensions examples: AFFINITY_USER_INTEREST,
    IN_MARKET_USER_INTEREST, CATEGORY, AGE_RANGE, GENDER, KNOWLEDGE_GRAPH.
    query_text is required for KNOWLEDGE_GRAPH topic search. entity_capabilities
    filters topics (CREATOR_TOPIC_INSIGHTS, CONTENT_TRENDING_INSIGHTS, BRAND,
    CREATOR_ATTRIBUTE). country_location is a geo target ID such as 2840 (US).
    Requires GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true.
    """
    ads_insights.require_audience_insights()
    return ads_insights.list_audience_insights_attributes(
        customer_id,
        dimensions=dimensions,
        query_text=query_text,
        country_location=country_location,
        location_country_filters=location_country_filters,
        entity_capabilities=entity_capabilities,
        get_all_creator_attributes=get_all_creator_attributes,
        insights_group=insights_group,
        login_customer_id=login_customer_id,
    )


def list_insights_eligible_dates(login_customer_id: str | None = None) -> dict[str, Any]:
    """Months that have audience composition data, plus the current last-30-days window.

    Requires GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true.
    """
    ads_insights.require_audience_insights()
    return ads_insights.list_insights_eligible_dates(login_customer_id=login_customer_id)


def generate_suggested_targeting_insights(
    customer_id: str,
    country_location: str | None = None,
    audience_description: str | None = None,
    audience: dict[str, Any] | None = None,
    marketing_objective: str | None = None,
    dimensions: list[str] | None = None,
    insights_group: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Suggest targetable YouTube audiences from a text description or structured audience.

    Allowlisted. Pass audience_description plus country_location (e.g. 2840), or an
    audience object with country_locations and optional gender/age_ranges/attributes.
    marketing_objective: AWARENESS, CONSIDERATION, or RESEARCH.
    Requires GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true.
    """
    ads_insights.require_audience_insights()
    return ads_insights.generate_suggested_targeting_insights(
        customer_id,
        country_location=country_location,
        audience_description=audience_description,
        audience=audience,
        marketing_objective=marketing_objective,
        dimensions=dimensions,
        insights_group=insights_group,
        login_customer_id=login_customer_id,
    )


def generate_audience_definition(
    customer_id: str,
    country_location: str,
    audience_description: str,
    marketing_objective: str | None = None,
    insights_group: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Turn a text audience description into ranked audience attributes.

    Allowlisted. country_location is a geo target ID such as 2840 (United States).
    Requires GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true.
    """
    ads_insights.require_audience_insights()
    return ads_insights.generate_audience_definition(
        customer_id,
        country_location,
        audience_description,
        marketing_objective=marketing_objective,
        insights_group=insights_group,
        login_customer_id=login_customer_id,
    )


def generate_audience_composition_insights(
    customer_id: str,
    country_locations: list[str],
    dimensions: list[str] | None = None,
    gender: str | None = None,
    age_ranges: list[str] | None = None,
    parental_status: str | None = None,
    attributes: list[dict[str, Any]] | None = None,
    attribute_groups: list[list[dict[str, Any]]] | None = None,
    data_month: str | None = None,
    insights_group: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Compare an audience's affinities and demographics against a baseline.

    Allowlisted. attributes are compact objects such as {"entity": "/m/014trl"} or
    items returned by list_audience_insights_attributes. data_month is YYYY-MM.
    Requires GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true.
    """
    ads_insights.require_audience_insights()
    return ads_insights.generate_audience_composition_insights(
        customer_id,
        country_locations,
        dimensions=dimensions,
        gender=gender,
        age_ranges=age_ranges,
        parental_status=parental_status,
        attributes=attributes,
        attribute_groups=attribute_groups,
        data_month=data_month,
        insights_group=insights_group,
        login_customer_id=login_customer_id,
    )


def generate_audience_overlap_insights(
    customer_id: str,
    country_location: str,
    primary_attribute: dict[str, Any],
    dimensions: list[str] | None = None,
    insights_group: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Estimate YouTube reach overlap between a primary attribute and other audiences.

    Allowlisted. primary_attribute example: {"user_interest": "80428"} or {"entity": "/m/014trl"}.
    Requires GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true.
    """
    ads_insights.require_audience_insights()
    return ads_insights.generate_audience_overlap_insights(
        customer_id,
        country_location,
        primary_attribute,
        dimensions=dimensions,
        insights_group=insights_group,
        login_customer_id=login_customer_id,
    )


def generate_targeting_suggestion_metrics(
    customer_id: str,
    audiences: list[dict[str, Any]] | None = None,
    country_locations: list[str] | None = None,
    gender: str | None = None,
    age_ranges: list[str] | None = None,
    attributes: list[dict[str, Any]] | None = None,
    insights_group: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Estimate YouTube reach for one or more audience definitions.

    Allowlisted. Each audience needs country_locations (geo IDs). You can pass a
    list of audiences or a single audience via country_locations plus filters.
    Requires GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true.
    """
    ads_insights.require_audience_insights()
    return ads_insights.generate_targeting_suggestion_metrics(
        customer_id,
        audiences=audiences,
        country_locations=country_locations,
        gender=gender,
        age_ranges=age_ranges,
        attributes=attributes,
        insights_group=insights_group,
        login_customer_id=login_customer_id,
    )


def generate_insights_finder_report(
    customer_id: str,
    country_locations: list[str],
    attributes: list[dict[str, Any]] | None = None,
    gender: str | None = None,
    age_ranges: list[str] | None = None,
    insights_group: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Create a saved Insights Finder report and return its URL.

    Allowlisted. Does not mutate campaigns. Baseline is the same countries with no extra filters.
    Requires GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true.
    """
    ads_insights.require_audience_insights()
    return ads_insights.generate_insights_finder_report(
        customer_id,
        country_locations,
        attributes=attributes,
        gender=gender,
        age_ranges=age_ranges,
        insights_group=insights_group,
        login_customer_id=login_customer_id,
    )


def generate_creator_insights(
    customer_id: str,
    country_locations: list[str],
    audience_attributes: list[dict[str, Any]] | None = None,
    creator_attributes: list[dict[str, Any]] | None = None,
    topics: list[str] | None = None,
    youtube_channel_ids: list[str] | None = None,
    sub_country_locations: list[str] | None = None,
    supplemental_data: list[str] | None = None,
    insights_group: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Discover YouTube creators or fetch insights for specific channels.

    ContentCreatorInsightsService is allowlisted and in beta. Provide exactly one of:
    audience_attributes (optionally with creator_attributes), topics (knowledge-graph
    IDs from list_audience_insights_attributes), or youtube_channel_ids.
    Topic search allows one country only. supplemental_data: LOCAL_CREATOR_DATA.
    Requires GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true.
    """
    ads_insights.require_audience_insights()
    return ads_insights.generate_creator_insights(
        customer_id,
        country_locations,
        audience_attributes=audience_attributes,
        creator_attributes=creator_attributes,
        topics=topics,
        youtube_channel_ids=youtube_channel_ids,
        sub_country_locations=sub_country_locations,
        supplemental_data=supplemental_data,
        insights_group=insights_group,
        login_customer_id=login_customer_id,
    )


def generate_trending_insights(
    customer_id: str,
    country_location: str,
    audience_attributes: list[dict[str, Any]] | None = None,
    topics: list[str] | None = None,
    supplemental_data: list[str] | None = None,
    insights_group: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """YouTube trending insights for an audience or a list of topics.

    Allowlisted. Provide audience_attributes or topics (knowledge-graph IDs), not both.
    supplemental_data: LOCAL_CREATOR_DATA, BRAND_SENTIMENT_DATA.
    Requires GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true.
    """
    ads_insights.require_audience_insights()
    return ads_insights.generate_trending_insights(
        customer_id,
        country_location,
        audience_attributes=audience_attributes,
        topics=topics,
        supplemental_data=supplemental_data,
        insights_group=insights_group,
        login_customer_id=login_customer_id,
    )


def register(mcp: FastMCP) -> None:
    mcp.tool(get_search_terms)
    mcp.tool(get_search_term_insights)
    mcp.tool(get_search_term_insight_terms)
    mcp.tool(get_impression_share_summary)
    mcp.tool(get_change_events)
    mcp.tool(get_recommendations)
    mcp.tool(get_local_audit)
    if load_settings().audience_insights_enabled:
        for tool in (
            list_audience_insights_attributes,
            list_insights_eligible_dates,
            generate_suggested_targeting_insights,
            generate_audience_definition,
            generate_audience_composition_insights,
            generate_audience_overlap_insights,
            generate_targeting_suggestion_metrics,
            generate_insights_finder_report,
            generate_creator_insights,
            generate_trending_insights,
        ):
            mcp.tool(tool)
