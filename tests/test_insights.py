from datetime import date
from types import SimpleNamespace

import pytest

from google_ads_mcp.errors import AdsError
from google_ads_mcp.insights import (
    account_today,
    annotate_emerging,
    as_float,
    clamp_completed_days,
    date_condition,
    generate_creator_insights,
    generate_suggested_targeting_insights,
    geo_target_constant,
    impression_share_query,
    insight_ids_from_rows,
    insight_row_key,
    insights_audience,
    list_audience_insights_attributes,
    parse_attribute,
    previous_window,
    proto_to_plain,
    require_audience_insights,
    resolve_window,
    search_term_insight_terms_query,
    search_term_insights_by_ids_query,
    search_term_insights_query,
    summarize_impression_share,
)
from google_ads_mcp.store import reset_store_for_tests
from google_ads_mcp.tools import insights as insights_tools
from tests.fakes import fake_ads_client


def test_geo_target_constant_accepts_id_and_resource() -> None:
    assert geo_target_constant("2840") == "geoTargetConstants/2840"
    assert geo_target_constant("geoTargetConstants/2840") == "geoTargetConstants/2840"
    assert geo_target_constant({"geo_target_constant": "geoTargetConstants/2250"}) == "geoTargetConstants/2250"
    with pytest.raises(AdsError, match="geo target"):
        geo_target_constant("United States")


def test_parse_attribute_simple_and_nested() -> None:
    client = fake_ads_client()
    entity = parse_attribute(client, "/m/014trl")
    assert entity.entity.knowledge_graph_machine_id == "/m/014trl"
    nested = parse_attribute(
        client,
        {"attribute": {"entity": {"knowledge_graph_machine_id": "/m/0f2f9"}}},
    )
    assert nested.entity.knowledge_graph_machine_id == "/m/0f2f9"
    age = parse_attribute(client, {"age_range": "AGE_RANGE_18_24"})
    assert age.age_range.type_.name == "AGE_RANGE_18_24"
    interest = parse_attribute(client, {"user_interest": "80428"}, customer_id="1234567890")
    assert interest.user_interest.user_interest_category == "customers/1234567890/userInterests/80428"


def test_insights_audience_and_proto_to_plain() -> None:
    client = fake_ads_client()
    audience = insights_audience(
        client,
        country_locations=["2840"],
        gender="MALE",
        age_ranges=["AGE_RANGE_25_34"],
        attributes=[{"entity": "/m/014trl"}],
    )
    plain = proto_to_plain(audience)
    assert plain["country_locations"] == [{"geo_target_constant": "geoTargetConstants/2840"}]
    assert plain["gender"] == {"type": "MALE"}
    assert plain["age_ranges"] == [{"type": "AGE_RANGE_25_34"}]
    assert plain["topic_audience_combinations"][0]["attributes"][0]["entity"]["knowledge_graph_machine_id"] == "/m/014trl"


def test_date_condition_validates_inputs() -> None:
    assert date_condition("last_7_days") == "segments.date DURING LAST_7_DAYS"
    assert date_condition(start_date="2026-01-01", end_date="2026-01-31") == (
        "segments.date BETWEEN '2026-01-01' AND '2026-01-31'"
    )
    with pytest.raises(AdsError, match="date_range"):
        date_condition("LAST_YEAR")
    with pytest.raises(AdsError, match="YYYY-MM-DD"):
        date_condition(start_date="2026-1-1", end_date="2026-01-31")


def test_search_term_insight_queries() -> None:
    categories = search_term_insights_query(campaign_id="111", date_range="LAST_30_DAYS")
    assert "FROM campaign_search_term_insight" in categories
    assert "campaign_search_term_insight.campaign_id = 111" in categories
    assert "DURING LAST_30_DAYS" in categories
    account = search_term_insights_query()
    assert "FROM customer_search_term_insight" in account
    terms = search_term_insight_terms_query(campaign_id="111", insight_id="9")
    assert "segments.search_term" in terms
    assert "campaign_search_term_insight.id = 9" in terms


def test_windows_and_emerging_terms() -> None:
    start, end = resolve_window("LAST_7_DAYS", today=date(2026, 9, 16))
    assert (start, end) == (date(2026, 9, 9), date(2026, 9, 15))
    assert previous_window(start, end) == (date(2026, 9, 2), date(2026, 9, 8))
    assert clamp_completed_days(date(2026, 9, 1), date(2026, 9, 16), today=date(2026, 9, 16)) == (
        date(2026, 9, 1),
        date(2026, 9, 15),
    )
    assert clamp_completed_days(date(2026, 9, 16), date(2026, 9, 16), today=date(2026, 9, 16)) == (
        date(2026, 9, 15),
        date(2026, 9, 15),
    )
    rows = annotate_emerging(
        [
            {
                "campaign_search_term_insight.id": 1,
                "campaign_search_term_insight.category_label": "trail shoes",
                "metrics.search_volume": 130,
            },
            {
                "campaign_search_term_insight.id": 2,
                "campaign_search_term_insight.category_label": "stable",
                "metrics.search_volume": 80,
            },
        ],
        [
            {
                "campaign_search_term_insight.id": 2,
                "campaign_search_term_insight.category_label": "stable",
                "metrics.search_volume": 80,
            },
        ],
    )
    assert rows[0]["is_new"] is True
    assert rows[0]["emerging"] is True
    assert rows[1]["emerging"] is False


def test_search_volume_range_message_is_numeric() -> None:
    assert as_float({"min": 100, "max": 200}) == 200.0
    overlapping = annotate_emerging(
        [
            {
                "campaign_search_term_insight.id": 1,
                "campaign_search_term_insight.category_label": "trail shoes",
                "metrics.search_volume": {"min": 100, "max": 200},
            }
        ],
        [
            {
                "campaign_search_term_insight.id": 1,
                "campaign_search_term_insight.category_label": "trail shoes",
                "metrics.search_volume": {"min": 80, "max": 120},
            }
        ],
    )
    assert overlapping[0]["volume_delta"] == 80.0
    assert overlapping[0]["previous_search_volume"] == 120.0
    assert overlapping[0]["volume_growth"] == round(100 / 120 - 1, 4)
    assert overlapping[0]["is_new"] is False
    assert overlapping[0]["emerging"] is False
    grew = annotate_emerging(
        [
            {
                "campaign_search_term_insight.id": 1,
                "campaign_search_term_insight.category_label": "trail shoes",
                "metrics.search_volume": {"min": 200, "max": 400},
            }
        ],
        [
            {
                "campaign_search_term_insight.id": 1,
                "campaign_search_term_insight.category_label": "trail shoes",
                "metrics.search_volume": {"min": 80, "max": 120},
            }
        ],
    )
    assert grew[0]["emerging"] is True
    assert grew[0]["volume_growth"] == round(200 / 120 - 1, 4)


def test_get_search_term_insights_uses_built_query(monkeypatch) -> None:
    seen: list[str] = []

    def fake_search(cid, query, login_customer_id=None):
        seen.append(query)
        if "customer.manager" in query:
            return [{"customer.id": 1, "customer.descriptive_name": "Acme", "customer.manager": False}]
        if "IN (" in query:
            return []
        return [
            {
                "campaign_search_term_insight.id": 1,
                "campaign_search_term_insight.campaign_id": 222,
                "campaign_search_term_insight.category_label": "running shoes",
                "metrics.search_volume": 40,
                "metrics.clicks": 8,
                "metrics.conversions": 1,
            }
        ]

    monkeypatch.setattr(insights_tools, "search", fake_search)
    payload = insights_tools.get_search_term_insights("123-456-7890", campaign_id="222", limit=5)
    assert payload["count"] == 1
    assert payload["emerging_count"] == 1
    assert payload["insights"][0]["emerging"] is True
    assert any("campaign_search_term_insight.id IN (1)" in query for query in seen)
    assert "campaign_search_term_insight.campaign_id = 222" in seen[1]
    assert "BETWEEN" in seen[1]


def test_search_term_insights_reject_manager(monkeypatch) -> None:
    def fake_search(cid, query, login_customer_id=None):
        return [{"customer.id": 1, "customer.descriptive_name": "MCC", "customer.manager": True}]

    monkeypatch.setattr(insights_tools, "search", fake_search)
    payload = insights_tools.get_search_term_insights("1234567890")
    assert payload["manager"] is True
    assert payload["count"] == 0


def test_impression_share_summary(monkeypatch) -> None:
    def fake_search(cid, query, login_customer_id=None):
        if "customer.manager" in query:
            return [{"customer.id": 1, "customer.descriptive_name": "Acme", "customer.manager": False}]
        if "FROM customer" in query and "2026-09-09" in query:
            return [{"metrics.search_impression_share": 0.4}]
        if "FROM customer" in query:
            return [{"metrics.search_impression_share": 0.5}]
        if "FROM campaign" in query and "2026-09-09" in query:
            return [
                {
                    "campaign.id": 9,
                    "campaign.name": "Search",
                    "campaign.status": "ENABLED",
                    "campaign.advertising_channel_type": "SEARCH",
                    "metrics.search_impression_share": 0.3,
                    "metrics.search_top_impression_share": 0.12,
                    "metrics.search_absolute_top_impression_share": 0.05,
                    "metrics.search_budget_lost_impression_share": 0.22,
                    "metrics.search_rank_lost_impression_share": 0.4,
                }
            ]
        return [
            {
                "campaign.id": 9,
                "campaign.name": "Search",
                "metrics.search_impression_share": 0.35,
                "metrics.search_budget_lost_impression_share": 0.1,
                "metrics.search_rank_lost_impression_share": 0.2,
            }
        ]

    monkeypatch.setattr(insights_tools, "search", fake_search)
    monkeypatch.setattr(insights_tools.ads_insights, "resolve_window", lambda *a, **k: (date(2026, 9, 9), date(2026, 9, 15)))
    payload = insights_tools.get_impression_share_summary("1234567890")
    assert payload["account"]["impression_share"] == 40.0
    assert payload["account"]["lost_to_budget"] is None
    assert payload["account"]["top_impression_share"] is None
    assert payload["account"]["scope"] == "customer_search_network"
    assert payload["filter_channel"] == "SEARCH"
    assert payload["account"]["deltas"]["impression_share"] == -10.0
    assert payload["campaigns"][0]["top_impression_share"] == 12.0
    assert any("budget" in item for item in payload["alerts"])
    campaign_query = impression_share_query(resource="campaign", when="segments.date DURING LAST_7_DAYS")
    assert "FROM campaign" in campaign_query
    assert "advertising_channel_type = 'SEARCH'" in campaign_query
    assert "metrics.search_budget_lost_impression_share" in campaign_query
    account_query = impression_share_query(resource="customer", when="segments.date DURING LAST_7_DAYS")
    assert "FROM customer" in account_query
    assert "metrics.search_impression_share" in account_query
    assert "metrics.search_top_impression_share" not in account_query
    assert "metrics.search_absolute_top_impression_share" not in account_query
    assert "metrics.search_budget_lost_impression_share" not in account_query
    assert "metrics.search_rank_lost_impression_share" not in account_query
    account = summarize_impression_share(
        current_account={"metrics.search_impression_share": 0.4},
        previous_account={"metrics.search_impression_share": 0.5},
        current_campaigns=[],
        previous_campaigns=[],
    )
    assert account["account"]["deltas"]["impression_share"] == -10.0


def test_audience_tools_require_flag(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.delenv("GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED", raising=False)
    with pytest.raises(AdsError, match="AUDIENCE_INSIGHTS_ENABLED"):
        require_audience_insights()
    monkeypatch.setenv("GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED", "true")
    require_audience_insights()


def test_list_attributes_builds_knowledge_graph_request(monkeypatch) -> None:
    client = fake_ads_client()
    captured: dict[str, object] = {}

    def fake_call(ads, service_name, method_name, request):
        captured["service"] = service_name
        captured["method"] = method_name
        captured["request"] = request
        return SimpleNamespace(attributes=[])

    monkeypatch.setattr("google_ads_mcp.insights._call", fake_call)
    list_audience_insights_attributes(
        "1234567890",
        query_text="cosmetics",
        country_location="2840",
        entity_capabilities=["CREATOR_TOPIC_INSIGHTS"],
        client=client,
    )
    request = captured["request"]
    assert captured == {
        "service": "AudienceInsightsService",
        "method": "list_audience_insights_attributes",
        "request": request,
    }
    assert request.customer_id == "1234567890"
    assert request.query_text == "cosmetics"
    assert request.customer_insights_group == "google-ads-mcp"
    names = {item.name for item in request.dimensions}
    assert "KNOWLEDGE_GRAPH" in names
    assert request.youtube_reach_location.geo_target_constant == "geoTargetConstants/2840"
    assert request.knowledge_graph_entity_search_options.search_filter.entity_capability_filters[0].name == (
        "CREATOR_TOPIC_INSIGHTS"
    )


def test_suggested_targeting_from_description(monkeypatch) -> None:
    client = fake_ads_client()
    captured: dict[str, object] = {}

    def fake_call(ads, service_name, method_name, request):
        captured["request"] = request
        return SimpleNamespace(suggestions=[])

    monkeypatch.setattr("google_ads_mcp.insights._call", fake_call)
    generate_suggested_targeting_insights(
        "1234567890",
        country_location="2840",
        audience_description="fathers in their 30s who enjoy fishing",
        marketing_objective="AWARENESS",
        client=client,
    )
    request = captured["request"]
    assert request.audience_description.audience_description == "fathers in their 30s who enjoy fishing"
    assert request.audience_description.country_locations[0].geo_target_constant == "geoTargetConstants/2840"
    assert request.audience_description.marketing_objective.name == "AWARENESS"
    with pytest.raises(AdsError, match="oneof"):
        generate_suggested_targeting_insights(
            "1234567890",
            country_location="2840",
            audience_description="fathers who fish",
            marketing_objective="AWARENESS",
            dimensions=["AFFINITY_USER_INTEREST"],
            client=client,
        )


def test_creator_insights_topics_require_one_country(monkeypatch) -> None:
    client = fake_ads_client()
    captured: dict[str, object] = {}

    def fake_call(ads, service_name, method_name, request):
        captured.update({"service": service_name, "method": method_name, "request": request})
        return SimpleNamespace(creator_insights=[], local_creator_insights=[])

    monkeypatch.setattr("google_ads_mcp.insights._call", fake_call)
    with pytest.raises(AdsError, match="exactly one country"):
        generate_creator_insights(
            "1234567890",
            country_locations=["2840", "2124"],
            topics=["/m/014trl"],
            client=client,
        )
    payload = generate_creator_insights(
        "1234567890",
        country_locations=["2840"],
        topics=["/m/014trl"],
        supplemental_data=["LOCAL_CREATOR_DATA"],
        client=client,
    )
    request = captured["request"]
    assert payload == {"count": 0, "creators": [], "local_creators": []}
    assert captured["service"] == "ContentCreatorInsightsService"
    assert request.search_topics.entities[0].knowledge_graph_machine_id == "/m/014trl"
    assert request.supplemental_data[0].name == "LOCAL_CREATOR_DATA"


def test_knowledge_graph_requires_query_text() -> None:
    with pytest.raises(AdsError, match="query_text"):
        list_audience_insights_attributes(
            "1234567890",
            dimensions=["KNOWLEDGE_GRAPH"],
            client=fake_ads_client(),
        )


def test_creator_attributes_cannot_combine_with_capability_filter() -> None:
    with pytest.raises(AdsError, match="cannot be combined"):
        list_audience_insights_attributes(
            "1234567890",
            get_all_creator_attributes=True,
            entity_capabilities=["CREATOR_TOPIC_INSIGHTS"],
            client=fake_ads_client(),
        )


def test_creator_attributes_cannot_combine_with_query_text() -> None:
    with pytest.raises(AdsError, match="query_text"):
        list_audience_insights_attributes(
            "1234567890",
            query_text="cosmetics",
            get_all_creator_attributes=True,
            client=fake_ads_client(),
        )


def test_insight_terms_use_resolved_window(monkeypatch) -> None:
    seen: list[str] = []

    def fake_search(cid, query, login_customer_id=None):
        seen.append(query)
        if "customer.manager" in query:
            return [{"customer.id": 1, "customer.descriptive_name": "Acme", "customer.manager": False}]
        return []

    monkeypatch.setattr(insights_tools, "search", fake_search)
    monkeypatch.setattr(
        insights_tools.ads_insights, "resolve_window", lambda *a, **k: (date(2026, 9, 9), date(2026, 9, 15))
    )
    insights_tools.get_search_term_insight_terms("1234567890", insight_id="9", campaign_id="111")
    assert any("BETWEEN '2026-09-09' AND '2026-09-15'" in query for query in seen)
    query = search_term_insights_by_ids_query(
        insight_ids=[1, 2], campaign_id="111", when="segments.date BETWEEN '2026-09-02' AND '2026-09-08'"
    )
    assert "id IN (1, 2)" in query


def test_insights_finder_report_previews(monkeypatch, tmp_path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "false")
    monkeypatch.setenv("GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED", "true")
    preview = insights_tools.generate_insights_finder_report("1234567890", country_locations=["2840"])
    assert preview["status"] == "preview"
    assert preview["confirm_token"]


def test_catch_all_insight_id_zero_is_kept() -> None:
    rows = [
        {
            "campaign_search_term_insight.id": 0,
            "campaign_search_term_insight.campaign_id": 222,
            "campaign_search_term_insight.category_label": "",
            "metrics.search_volume": 100,
        }
    ]
    assert insight_ids_from_rows(rows) == [0]
    assert insight_row_key(rows[0]) == "222:0"
    annotated = annotate_emerging(rows, rows)
    assert annotated[0]["is_new"] is False
    assert annotated[0]["emerging"] is False


def test_get_search_term_insights_keeps_catch_all_id_zero(monkeypatch) -> None:
    seen: list[str] = []

    def fake_search(cid, query, login_customer_id=None):
        seen.append(query)
        if "customer.manager" in query:
            return [{"customer.id": 1, "customer.descriptive_name": "Acme", "customer.manager": False}]
        row = {
            "campaign_search_term_insight.id": 0,
            "campaign_search_term_insight.campaign_id": 222,
            "campaign_search_term_insight.category_label": "",
            "metrics.search_volume": 40,
        }
        return [row]

    monkeypatch.setattr(insights_tools, "search", fake_search)
    payload = insights_tools.get_search_term_insights("1234567890", campaign_id="222")
    assert any("campaign_search_term_insight.id IN (0)" in query for query in seen)
    assert payload["insights"][0]["is_new"] is False
    assert payload["emerging_count"] == 0


def test_search_term_windows_use_account_timezone(monkeypatch) -> None:
    def fake_search(cid, query, login_customer_id=None):
        if "customer.manager" in query:
            return [
                {
                    "customer.id": 1,
                    "customer.descriptive_name": "Acme",
                    "customer.manager": False,
                    "customer.time_zone": "Pacific/Auckland",
                }
            ]
        return []

    monkeypatch.setattr(insights_tools, "search", fake_search)
    payload = insights_tools.get_search_term_insights("1234567890")
    today = account_today("Pacific/Auckland")
    start, end = resolve_window("LAST_7_DAYS", today=today)
    assert payload["current_period"] == {"start": start.isoformat(), "end": end.isoformat()}
    assert account_today("Not/AZone") == date.today()


def test_impression_share_keeps_campaigns_when_account_query_fails(monkeypatch) -> None:
    seen: list[str] = []

    def fake_search(cid, query, login_customer_id=None):
        seen.append(query)
        if "customer.manager" in query:
            return [{"customer.id": 1, "customer.descriptive_name": "Acme", "customer.manager": False}]
        if "FROM customer" in query:
            raise AdsError("customer metrics unavailable")
        return [
            {
                "campaign.id": 9,
                "campaign.name": "Search",
                "metrics.search_impression_share": 0.3,
            }
        ]

    monkeypatch.setattr(insights_tools, "search", fake_search)
    monkeypatch.setattr(
        insights_tools.ads_insights, "resolve_window", lambda *a, **k: (date(2026, 9, 9), date(2026, 9, 15))
    )
    payload = insights_tools.get_impression_share_summary("1234567890")
    assert payload["campaigns"][0]["campaign_id"] == 9
    assert payload["account"]["impression_share"] is None
    assert [item for item in payload["alerts"] if "unavailable" in item] == [
        "Account-level impression share was unavailable: customer metrics unavailable"
    ]
    customer_is = [query for query in seen if "search_impression_share" in query and "FROM customer" in query]
    assert len(customer_is) == 1


def test_impression_share_skips_account_for_non_search_channel(monkeypatch) -> None:
    seen: list[str] = []

    def fake_search(cid, query, login_customer_id=None):
        seen.append(query)
        if "customer.manager" in query:
            return [{"customer.id": 1, "customer.descriptive_name": "Acme", "customer.manager": False}]
        return []

    monkeypatch.setattr(insights_tools, "search", fake_search)
    monkeypatch.setattr(
        insights_tools.ads_insights, "resolve_window", lambda *a, **k: (date(2026, 9, 9), date(2026, 9, 15))
    )
    payload = insights_tools.get_impression_share_summary("1234567890", channel="DISPLAY")
    assert payload["account"] is None
    assert payload["filter_channel"] == "DISPLAY"
    assert not any("search_impression_share" in query and "FROM customer" in query for query in seen)
