"""Search terms, Ads Insights services, change history, recommendations, and local audit."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp import insights as ads_insights
from google_ads_mcp.config import load_settings
from google_ads_mcp.errors import AdsError
from google_ads_mcp.gaql import search
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.safety import SafetyGate, with_login_arg
from google_ads_mcp.store import get_store

_ACCOUNT_IS_NOTE = (
    "Account-level Search impression share covers all Search inventory, including paused "
    "campaigns. Campaign rows use the requested channel and status filters."
)


def _customer_context(customer_id: str, login_customer_id: str | None = None) -> dict[str, Any]:
    cid = clean_customer_id(customer_id)
    rows = search(
        cid,
        "SELECT customer.id, customer.descriptive_name, customer.manager, customer.time_zone "
        "FROM customer LIMIT 1",
        login_customer_id=login_customer_id,
    )
    row = rows[0] if rows else {}
    return {
        "customer_id": cid,
        "name": row.get("customer.descriptive_name") or cid,
        "manager": bool(row.get("customer.manager")),
        "time_zone": row.get("customer.time_zone"),
    }


def _manager_blocked(account: dict[str, Any]) -> dict[str, Any] | None:
    if not account.get("manager"):
        return None
    name = account["name"]
    return {
        "customer_id": account["customer_id"],
        "manager": True,
        "name": name,
        "count": 0,
        "alerts": [f"{name} is a manager (MCC) account. Call this tool on a client customer_id."],
    }


def _search_optional(customer_id: str, query: str, login_customer_id: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return search(customer_id, query, login_customer_id=login_customer_id), None
    except AdsError as exc:
        return [], str(exc)


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
    inside one category. Empty Google catch-all labels are returned as
    Uncategorized. Search volume is a {min, max} range when Google sends bounds.
    Emerging categories are new versus the previous equal window, or grew
    search volume by 25%+.
    """
    account = _customer_context(customer_id, login_customer_id)
    if blocked := _manager_blocked(account):
        return blocked
    cid = account["customer_id"]
    current_start, current_end = ads_insights.resolve_window(
        date_range, start_date, end_date, today=ads_insights.account_today(account.get("time_zone"))
    )
    current_when = ads_insights.between_condition(current_start, current_end)
    query = ads_insights.search_term_insights_query(
        campaign_id=campaign_id,
        limit=limit,
        when=current_when,
    )
    rows = search(cid, query, login_customer_id=login_customer_id)
    prev_start, prev_end = ads_insights.previous_window(current_start, current_end)
    previous_rows: list[dict[str, Any]] = []
    insight_ids = ads_insights.insight_ids_from_rows(rows)
    if insight_ids:
        previous_query = ads_insights.search_term_insights_by_ids_query(
            insight_ids=insight_ids,
            campaign_id=campaign_id,
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
    Account-level categories only need insight_id. GAQL cannot LIMIT or ORDER BY
    while segmenting by search term, so `limit` is applied after ranking by
    impressions.
    """
    account = _customer_context(customer_id, login_customer_id)
    if blocked := _manager_blocked(account):
        return blocked
    cid = account["customer_id"]
    start, end = ads_insights.resolve_window(
        date_range, start_date, end_date, today=ads_insights.account_today(account.get("time_zone"))
    )
    query = ads_insights.search_term_insight_terms_query(
        insight_id=insight_id,
        campaign_id=campaign_id,
        when=ads_insights.between_condition(start, end),
    )
    rows = ads_insights.rank_search_term_insight_rows(
        search(cid, query, login_customer_id=login_customer_id),
        limit,
    )
    return {"count": len(rows), "search_terms": rows, "query": query}


def get_impression_share_summary(
    customer_id: str,
    campaign_id: str | None = None,
    date_range: str = "LAST_7_DAYS",
    start_date: str | None = None,
    end_date: str | None = None,
    include_paused: bool = False,
    channel: str = "SEARCH",
    limit: int = 100,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Search impression share, top/absolute-top share, and lost share from budget vs rank.

    Returns account and campaign rows for the current window plus deltas versus the
    previous equal-length period. Shares are percents (0-100). Defaults to SEARCH
    campaigns. The account row is customer-level Search impression share (all Search
    inventory); campaign rows use `channel` and status filters. Windows use the Ads
    account timezone and are clamped to yesterday because impression share is not
    available for the current day.
    """
    account = _customer_context(customer_id, login_customer_id)
    if blocked := _manager_blocked(account):
        return blocked
    cid = account["customer_id"]
    today = ads_insights.account_today(account.get("time_zone"))
    current_start, current_end = ads_insights.clamp_completed_days(
        *ads_insights.resolve_window(date_range, start_date, end_date, today=today),
        today=today,
    )
    prev_start, prev_end = ads_insights.previous_window(current_start, current_end)
    current_when = ads_insights.between_condition(current_start, current_end)
    previous_when = ads_insights.between_condition(prev_start, prev_end)
    channel_key = (channel or "SEARCH").strip().upper()
    include_account = channel_key in {"SEARCH", "ALL"}
    account_now: list[dict[str, Any]] = []
    account_prev: list[dict[str, Any]] = []
    extra_alerts: list[str] = []
    if include_account:
        account_now, account_error = _search_optional(
            cid,
            ads_insights.impression_share_query(resource="customer", when=current_when),
            login_customer_id,
        )
        if account_error:
            extra_alerts.append(f"Account-level impression share was unavailable: {account_error}")
        else:
            account_prev, prev_error = _search_optional(
                cid,
                ads_insights.impression_share_query(resource="customer", when=previous_when),
                login_customer_id,
            )
            if prev_error:
                extra_alerts.append(f"Previous-period account impression share was unavailable: {prev_error}")
    campaigns_now = search(
        cid,
        ads_insights.impression_share_query(
            resource="campaign",
            when=current_when,
            campaign_id=campaign_id,
            include_paused=include_paused,
            channel=channel,
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
            channel=channel,
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
    if include_account:
        summary["account"] = {**summary["account"], "scope": "customer_search_network", "note": _ACCOUNT_IS_NOTE}
    else:
        summary["account"] = None
        summary["alerts"] = [item for item in summary["alerts"] if not item.startswith("Account ")]
    summary["alerts"] = extra_alerts + summary["alerts"]
    return {
        "customer_id": cid,
        "filter_channel": channel_key,
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
    customer_id: str,
    campaign_id: str | None = None,
    types: list[str] | None = None,
    limit: int = 25,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Google Ads optimization recommendations that are still pending.

    Optional campaign_id and types filters. Each item is tagged origin=GOOGLE_API
    with type-specific details when the API returns them. Google Ads UI and API
    recommendations may differ or update at different times.
    """
    cid = clean_customer_id(customer_id)
    conditions = ["recommendation.dismissed = FALSE"]
    if campaign_id is not None:
        camp = str(int(str(campaign_id).replace("-", "")))
        conditions.append(
            f"recommendation.campaign = 'customers/{cid}/campaigns/{camp}'"
        )
    if types:
        quoted = ", ".join(f"'{t.strip().upper()}'" for t in types)
        conditions.append(f"recommendation.type IN ({quoted})")
    rows = search(
        cid,
        "SELECT recommendation.resource_name, recommendation.type, recommendation.campaign, "
        "recommendation.campaign_budget, recommendation.ad_group, "
        "recommendation.impact.base_metrics.impressions, "
        "recommendation.impact.base_metrics.clicks, "
        "recommendation.impact.base_metrics.cost_micros, "
        "recommendation.impact.base_metrics.conversions, "
        "recommendation.impact.base_metrics.conversions_value, "
        "recommendation.impact.potential_metrics.impressions, "
        "recommendation.impact.potential_metrics.clicks, "
        "recommendation.impact.potential_metrics.cost_micros, "
        "recommendation.impact.potential_metrics.conversions, "
        "recommendation.impact.potential_metrics.conversions_value, "
        "recommendation.keyword_recommendation.keyword.text, "
        "recommendation.keyword_recommendation.keyword.match_type, "
        "recommendation.keyword_recommendation.recommended_cpc_bid_micros, "
        "recommendation.campaign_budget_recommendation.recommended_budget_amount_micros, "
        "recommendation.callout_asset_recommendation.recommended_campaign_callout_assets, "
        "recommendation.sitelink_asset_recommendation.recommended_campaign_sitelink_assets "
        "FROM recommendation WHERE "
        + " AND ".join(conditions)
        + f" LIMIT {int(limit)}",
        login_customer_id=login_customer_id,
    )
    recommendations = [_normalize_recommendation(row) for row in rows]
    return {
        "count": len(recommendations),
        "origin": "GOOGLE_API",
        "warning": (
            "Google Ads UI and API recommendations may differ or update at different times. "
            "Use get_campaign_hints for local diagnostics tagged LOCAL_DIAGNOSTIC."
        ),
        "recommendations": recommendations,
    }


def _normalize_recommendation(row: dict[str, Any]) -> dict[str, Any]:
    rec_type = row.get("recommendation.type")
    details: dict[str, Any] = {}
    if row.get("recommendation.keyword_recommendation.keyword.text"):
        details["keyword"] = {
            "text": row.get("recommendation.keyword_recommendation.keyword.text"),
            "match_type": row.get("recommendation.keyword_recommendation.keyword.match_type"),
            "recommended_cpc_bid_micros": row.get(
                "recommendation.keyword_recommendation.recommended_cpc_bid_micros"
            ),
        }
    budget = row.get(
        "recommendation.campaign_budget_recommendation.recommended_budget_amount_micros"
    )
    if budget is not None:
        details["budget"] = {"recommended_budget_amount_micros": budget}
    for key, label in (
        (
            "recommendation.callout_asset_recommendation.recommended_campaign_callout_assets",
            "callout_assets",
        ),
        (
            "recommendation.sitelink_asset_recommendation.recommended_campaign_sitelink_assets",
            "sitelink_assets",
        ),
    ):
        if row.get(key) not in (None, [], ""):
            details[label] = row.get(key)

    impact = {
        "base": {
            "impressions": row.get("recommendation.impact.base_metrics.impressions"),
            "clicks": row.get("recommendation.impact.base_metrics.clicks"),
            "cost_micros": row.get("recommendation.impact.base_metrics.cost_micros"),
            "conversions": row.get("recommendation.impact.base_metrics.conversions"),
            "conversions_value": row.get(
                "recommendation.impact.base_metrics.conversions_value"
            ),
        },
        "potential": {
            "impressions": row.get("recommendation.impact.potential_metrics.impressions"),
            "clicks": row.get("recommendation.impact.potential_metrics.clicks"),
            "cost_micros": row.get("recommendation.impact.potential_metrics.cost_micros"),
            "conversions": row.get("recommendation.impact.potential_metrics.conversions"),
            "conversions_value": row.get(
                "recommendation.impact.potential_metrics.conversions_value"
            ),
        },
    }
    return {
        "origin": "GOOGLE_API",
        "type": rec_type,
        "campaign": row.get("recommendation.campaign"),
        "ad_group": row.get("recommendation.ad_group"),
        "resource_name": row.get("recommendation.resource_name"),
        "details": details,
        "impact": impact,
    }


def get_campaign_hints(
    customer_id: str,
    campaign_id: str,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Combine Google API recommendations with local diagnostic findings.

    Google items use origin=GOOGLE_API. Observed problems (IS lost, missing
    callouts, policy review, learning, no delivery, etc.) use origin=LOCAL_DIAGNOSTIC.
    """
    from google_ads_mcp.diagnostics import ORIGIN_GOOGLE, ORIGIN_LOCAL, build_campaign_diagnostics

    diag = build_campaign_diagnostics(
        customer_id, campaign_id, login_customer_id=login_customer_id
    )
    google_items = [f for f in diag.get("findings", []) if f.get("origin") == ORIGIN_GOOGLE]
    local_items = [f for f in diag.get("findings", []) if f.get("origin") == ORIGIN_LOCAL]
    payload: dict[str, Any] = {
        "customer_id": diag.get("customer_id"),
        "campaign_id": diag.get("campaign_id"),
        "warning": (
            "Google Ads UI and API recommendations may differ or update at different times. "
            "Local findings are not Google recommendations."
        ),
        "google_recommendations": google_items,
        "local_diagnostics": local_items,
        "findings": diag.get("findings", []),
        "finding_counts": diag.get("finding_counts", {}),
    }
    if diag.get("error"):
        payload["error"] = diag["error"]
    return payload


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
    dry_run: bool = True,
    confirm_token: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Create a saved Insights Finder report and return its URL.

    Allowlisted. Creates a remote report, so this goes through SafetyGate: preview
    with dry_run=true, then apply with confirm_token. Writes need
    GOOGLE_ADS_WRITE_ENABLED=true. Requires GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED=true.
    """
    ads_insights.require_audience_insights()
    cid = clean_customer_id(customer_id)
    args = with_login_arg(
        {
            "country_locations": country_locations,
            "attributes": attributes,
            "gender": gender,
            "age_ranges": age_ranges,
            "insights_group": insights_group,
        },
        login_customer_id,
    )
    auth = SafetyGate().authorize_write(
        tool="generate_insights_finder_report",
        customer_id=cid,
        args=args,
        description=f"Create Insights Finder report for {cid}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    result = ads_insights.generate_insights_finder_report(
        customer_id,
        country_locations,
        attributes=attributes,
        gender=gender,
        age_ranges=age_ranges,
        insights_group=insights_group,
        login_customer_id=login_customer_id,
    )
    get_store().record_audit(
        tool="generate_insights_finder_report",
        action="apply",
        customer_id=cid,
        payload=result,
    )
    return result


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
    mcp.tool(get_campaign_hints)
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
