from types import SimpleNamespace

import pytest

from google_ads_mcp.builders.demand_gen import (
    DISPLAY_LIST_THRESHOLD,
    STOCKHOLM_GEO_TARGET_ID,
    build_audience_create,
    build_conversion_goal_operations,
    build_demand_gen_campaign,
    evaluate_demand_gen_readiness,
    meets_display_threshold,
    validate_demand_gen_copy,
)
from google_ads_mcp.errors import AdsError
from google_ads_mcp.store import reset_store_for_tests
from google_ads_mcp.tools import audiences as audience_tools
from google_ads_mcp.tools import demand_gen as demand_gen_tools
from tests.fakes import fake_ads_client


def _ops(**overrides):
    args = {
        "name": "Senva DG",
        "daily_budget": 25,
        "final_url": "https://example.com",
        "business_name": "Senva",
        "headlines": ["Book analysis", "Find your fit", "Start in minutes"],
        "descriptions": ["Paused Demand Gen for remarketing."],
        "marketing_image_assets": ["customers/1/assets/1"],
        "square_marketing_image_assets": ["customers/1/assets/2"],
        "logo_image_assets": ["customers/1/assets/3"],
        "audience_id": "55",
        "conversion_action_ids": ["99"],
        "target_cpc": 3.0,
    }
    args.update(overrides)
    return build_demand_gen_campaign(fake_ads_client(), "1234567890", **args)


def test_demand_gen_copy_requires_three_headlines() -> None:
    with pytest.raises(ValueError, match="3 headlines"):
        validate_demand_gen_copy(["one"], ["desc"], "Senva")


def test_demand_gen_builder_is_paused_display_only() -> None:
    client = fake_ads_client()
    operations = _ops()
    kinds = [op._pb.WhichOneof("operation") for op in operations]
    assert kinds[0] == "campaign_budget_operation"
    assert operations[0].campaign_budget_operation.create.explicitly_shared is False
    campaign = operations[1].campaign_operation.create
    assert campaign.advertising_channel_type == client.enums.AdvertisingChannelTypeEnum.DEMAND_GEN
    assert campaign.status == client.enums.CampaignStatusEnum.PAUSED
    assert campaign.target_spend.cpc_bid_ceiling_micros == 3_000_000

    ad_group = next(op.ad_group_operation.create for op in operations if op._pb.WhichOneof("operation") == "ad_group_operation")
    assert ad_group.status == client.enums.AdGroupStatusEnum.PAUSED
    assert ad_group.audience_setting.use_audience_grouped is True
    assert ad_group.optimized_targeting_enabled is False
    channels = ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels
    assert channels.display is True
    assert channels.gmail is False
    assert channels.discover is False
    assert channels.maps is False
    assert channels.youtube_in_feed is False
    assert channels.youtube_in_stream is False
    assert channels.youtube_shorts is False

    audience = next(
        op.ad_group_criterion_operation.create
        for op in operations
        if op._pb.WhichOneof("operation") == "ad_group_criterion_operation"
        and op.ad_group_criterion_operation.create.audience.audience
    )
    assert audience.audience.audience == "customers/1234567890/audiences/55"

    geos = [
        op.ad_group_criterion_operation.create.location.geo_target_constant
        for op in operations
        if op._pb.WhichOneof("operation") == "ad_group_criterion_operation"
        and op.ad_group_criterion_operation.create.location.geo_target_constant
    ]
    assert geos == [f"geoTargetConstants/{STOCKHOLM_GEO_TARGET_ID}"]

    ad = next(op.ad_group_ad_operation.create for op in operations if op._pb.WhichOneof("operation") == "ad_group_ad_operation")
    assert ad.status == client.enums.AdGroupAdStatusEnum.PAUSED
    assert ad.ad.demand_gen_multi_asset_ad.business_name == "Senva"

    goal = next(
        op.custom_conversion_goal_operation.create
        for op in operations
        if op._pb.WhichOneof("operation") == "custom_conversion_goal_operation"
    )
    assert goal.conversion_actions == ["customers/1234567890/conversionActions/99"]
    config = next(
        op.conversion_goal_campaign_config_operation.update
        for op in operations
        if op._pb.WhichOneof("operation") == "conversion_goal_campaign_config_operation"
    )
    assert config.goal_config_level == client.enums.GoalConfigLevelEnum.CAMPAIGN


def test_audience_create_includes_and_excludes_lists() -> None:
    client = fake_ads_client()
    operation = build_audience_create(
        client,
        "1234567890",
        name="Senva | High intent | No purchase",
        included_user_list_ids=["11", "22"],
        excluded_user_list_ids=["33"],
    )
    audience = operation.create
    segments = audience.dimensions[0].audience_segments.segments
    assert [item.user_list.user_list for item in segments] == [
        "customers/1234567890/userLists/11",
        "customers/1234567890/userLists/22",
    ]
    assert audience.exclusion_dimension.exclusions[0].user_list.user_list == "customers/1234567890/userLists/33"
    with pytest.raises(AdsError, match="Duplicate"):
        build_audience_create(client, "1234567890", name="x", included_user_list_ids=["11", "11"])


def test_conversion_goal_ops_use_campaign_level_custom_goal() -> None:
    client = fake_ads_client()
    operations = build_conversion_goal_operations(
        client, "1234567890", campaign_id="111", conversion_action_ids=["99"], name="Purchase only"
    )
    assert operations[0].custom_conversion_goal_operation.create.name == "Purchase only"
    assert operations[1].conversion_goal_campaign_config_operation.update.resource_name.endswith("/111")


def test_display_threshold() -> None:
    assert meets_display_threshold(100, True) is True
    assert meets_display_threshold(99, True) is False
    assert meets_display_threshold(500, False) is False
    assert meets_display_threshold(-1, True) is None
    assert DISPLAY_LIST_THRESHOLD == 100


def test_readiness_reports_blocking_gaps() -> None:
    verdict = evaluate_demand_gen_readiness(
        campaign={"campaign.advertising_channel_type": "DEMAND_GEN"},
        ad_groups=[
            {
                "ad_group.optimized_targeting_enabled": True,
                "ad_group.demand_gen_ad_group_settings.channel_controls.channel_strategy": "ALL_CHANNELS",
            }
        ],
        criteria=[],
        ads=[],
        user_lists=[{"user_list.name": "High intent", "user_list.size_for_display": 12, "user_list.eligible_for_display": True}],
        goal_config={"conversion_goal_campaign_config.goal_config_level": "CUSTOMER"},
        expected_channels=["DISPLAY"],
        expected_geo_ids=[STOCKHOLM_GEO_TARGET_ID],
        purchase_action_ids=["99"],
    )
    assert verdict["ready"] is False
    text = " ".join(verdict["failures"])
    assert "No audience" in text
    assert "below 100" in text
    assert "Optimized targeting" in text
    assert "channels" in text
    assert "Stockholm" in text
    assert "Purchase" in text
    assert "assets" in text


def test_readiness_passes_when_controls_match() -> None:
    verdict = evaluate_demand_gen_readiness(
        campaign={"campaign.advertising_channel_type": "DEMAND_GEN"},
        ad_groups=[
            {
                "ad_group.optimized_targeting_enabled": False,
                "ad_group.demand_gen_ad_group_settings.channel_controls.channel_config": "SELECTED_CHANNELS",
                "ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.display": True,
            }
        ],
        criteria=[
            {"ad_group_criterion.audience.audience": "customers/1/audiences/55", "ad_group_criterion.negative": False},
            {
                "ad_group_criterion.location.geo_target_constant": f"geoTargetConstants/{STOCKHOLM_GEO_TARGET_ID}",
                "ad_group_criterion.negative": False,
            },
        ],
        ads=[
            {
                "ad_group_ad.policy_summary.approval_status": "APPROVED",
                "ad_group_ad.ad.demand_gen_multi_asset_ad.headlines": [{"text": "H1"}],
                "ad_group_ad.ad.demand_gen_multi_asset_ad.marketing_images": [{"asset": "a"}],
                "ad_group_ad.ad.demand_gen_multi_asset_ad.square_marketing_images": [{"asset": "b"}],
                "ad_group_ad.ad.demand_gen_multi_asset_ad.logo_images": [{"asset": "c"}],
            }
        ],
        user_lists=[{"user_list.name": "High intent", "user_list.size_for_display": 150, "user_list.eligible_for_display": True}],
        goal_config={
            "conversion_goal_campaign_config.goal_config_level": "CAMPAIGN",
            "custom_conversion_goal.conversion_actions": ["customers/1/conversionActions/99"],
        },
        expected_channels=["DISPLAY"],
        expected_geo_ids=[STOCKHOLM_GEO_TARGET_ID],
        purchase_action_ids=["99"],
    )
    assert verdict == {"ready": True, "failures": [], "warnings": []}


def test_create_demand_gen_previews(monkeypatch, tmp_path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "false")
    preview = demand_gen_tools.create_demand_gen_campaign(
        customer_id="1234567890",
        name="Senva DG",
        daily_budget=25,
        final_url="https://example.com",
        business_name="Senva",
        headlines=["Book analysis", "Find your fit", "Start in minutes"],
        descriptions=["Paused Demand Gen for remarketing."],
        marketing_image_assets=["customers/1/assets/1"],
        square_marketing_image_assets=["customers/1/assets/2"],
        logo_image_assets=["customers/1/assets/3"],
        audience_id="55",
    )
    assert preview["status"] == "preview"
    assert preview["args"]["channels"] == ["DISPLAY"]
    assert preview["args"]["geo_target_constant_ids"] == [STOCKHOLM_GEO_TARGET_ID]


def test_list_user_lists_shapes_threshold(monkeypatch) -> None:
    def fake_search(cid, query, login_customer_id=None):
        assert "user_list.size_for_display" in query
        return [
            {
                "user_list.id": 11,
                "user_list.name": "High intent",
                "user_list.type": "RULE_BASED",
                "user_list.membership_status": "OPEN",
                "user_list.size_for_display": 140,
                "user_list.eligible_for_display": True,
                "user_list.membership_life_span": 30,
            }
        ]

    monkeypatch.setattr(audience_tools, "search", fake_search)
    payload = audience_tools.list_user_lists("123-456-7890")
    assert payload["user_lists"][0]["meets_display_threshold"] is True
    assert payload["user_lists"][0]["prepopulation_status"] is None
    assert payload["user_lists"][0]["membership_duration_days"] == 30


def test_create_audience_and_attach_preview(monkeypatch, tmp_path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "false")
    preview = audience_tools.create_audience(
        "1234567890",
        name="Senva | High intent | No purchase",
        included_user_list_ids=["11"],
        excluded_user_list_ids=["33"],
    )
    assert preview["status"] == "preview"
    attach = audience_tools.attach_audience_to_ad_group("1234567890", ad_group_id="8", audience_id="55")
    assert attach["status"] == "preview"


def test_get_demand_gen_readiness_uses_evaluator(monkeypatch) -> None:
    def fake_search(cid, query, login_customer_id=None):
        if "FROM campaign" in query:
            return [{"campaign.advertising_channel_type": "DEMAND_GEN"}]
        if "FROM ad_group " in query:
            return [
                {
                    "ad_group.optimized_targeting_enabled": False,
                    "ad_group.demand_gen_ad_group_settings.channel_controls.selected_channels.display": True,
                }
            ]
        if "FROM ad_group_criterion" in query:
            return [
                {"ad_group_criterion.audience.audience": "customers/1/audiences/55"},
                {"ad_group_criterion.location.geo_target_constant": f"geoTargetConstants/{STOCKHOLM_GEO_TARGET_ID}"},
            ]
        if "FROM ad_group_ad" in query:
            return [
                {
                    "ad_group_ad.policy_summary.approval_status": "APPROVED",
                    "ad_group_ad.ad.demand_gen_multi_asset_ad.headlines": [{"text": "H"}],
                    "ad_group_ad.ad.demand_gen_multi_asset_ad.marketing_images": [{"asset": "a"}],
                    "ad_group_ad.ad.demand_gen_multi_asset_ad.square_marketing_images": [{"asset": "b"}],
                    "ad_group_ad.ad.demand_gen_multi_asset_ad.logo_images": [{"asset": "c"}],
                }
            ]
        if "FROM conversion_goal_campaign_config" in query:
            return [
                {
                    "conversion_goal_campaign_config.goal_config_level": "CAMPAIGN",
                    "custom_conversion_goal.conversion_actions": ["customers/1/conversionActions/99"],
                }
            ]
        if "FROM audience" in query:
            return [
                {
                    "audience.dimensions": [
                        {"audience_segments": {"segments": [{"user_list": {"user_list": "customers/1/userLists/11"}}]}}
                    ]
                }
            ]
        if "FROM user_list" in query:
            return [{"user_list.name": "High intent", "user_list.size_for_display": 200, "user_list.eligible_for_display": True}]
        return []

    monkeypatch.setattr(demand_gen_tools, "search", fake_search)
    payload = demand_gen_tools.get_demand_gen_readiness(
        "1234567890", campaign_id="111", purchase_action_ids=["99"]
    )
    assert payload["ready"] is True


def test_create_audience_apply_uses_audience_service(monkeypatch, tmp_path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_ADS_SKIP_CONFIRM", "true")
    captured: list[object] = []

    def fake_run(method, **kwargs):
        captured.extend(kwargs.get("operations") or [])
        return SimpleNamespace(results=[SimpleNamespace(resource_name="customers/1234567890/audiences/77")])

    monkeypatch.setattr(audience_tools, "get_client", lambda login_customer_id=None: fake_ads_client())
    monkeypatch.setattr(audience_tools, "run_ads_call", fake_run)
    result = audience_tools.create_audience(
        "1234567890",
        name="Senva | High intent | No purchase",
        included_user_list_ids=["11"],
        excluded_user_list_ids=["33"],
        dry_run=False,
    )
    assert result["audience_id"] == "77"
    assert captured[0].create.dimensions[0].audience_segments.segments[0].user_list.user_list.endswith("/11")
