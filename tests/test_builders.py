import pytest

from google_ads_mcp.builders.display import build_display_campaign
from google_ads_mcp.builders.pmax import build_asset_group_text_ops, build_pmax_campaign
from google_ads_mcp.builders.search import build_search_campaign
from tests.fakes import fake_ads_client


class _Boom:
    """Stand-in so validation runs before any client calls."""


def test_search_requires_headlines() -> None:
    with pytest.raises(ValueError, match="3 headlines"):
        build_search_campaign(
            _Boom(),
            "123",
            name="n",
            daily_budget=10,
            final_url="https://example.com",
            headlines=["a"],
            descriptions=["d1", "d2"],
        )


def test_search_requires_descriptions() -> None:
    with pytest.raises(ValueError, match="2 descriptions"):
        build_search_campaign(
            _Boom(),
            "123",
            name="n",
            daily_budget=10,
            final_url="https://example.com",
            headlines=["h1", "h2", "h3"],
            descriptions=["only one"],
        )


def test_search_builder_creates_paused_campaign() -> None:
    client = fake_ads_client()
    operations = build_search_campaign(
        client,
        "1234567890",
        name="Spring shoes",
        daily_budget=25,
        final_url="https://example.com",
        headlines=["Buy shoes", "Spring sale", "Free shipping"],
        descriptions=["Shop the new drop.", "Limited time offer."],
        keywords=["running shoes"],
    )
    campaign = operations[1].campaign_operation.create
    assert campaign.status == client.enums.CampaignStatusEnum.PAUSED
    assert campaign.advertising_channel_type == client.enums.AdvertisingChannelTypeEnum.SEARCH
    assert any(op.ad_group_criterion_operation.create.keyword.text == "running shoes" for op in operations)


def test_display_and_pmax_builders_are_paused() -> None:
    client = fake_ads_client()
    display = build_display_campaign(
        client,
        "1234567890",
        name="Display",
        daily_budget=10,
        final_url="https://example.com",
        business_name="Acme",
        headlines=["Hello"],
        long_headline="Hello there friends",
        descriptions=["Desc"],
        marketing_image_asset="customers/1/assets/1",
        square_marketing_image_asset="customers/1/assets/2",
    )
    assert display[1].campaign_operation.create.status == client.enums.CampaignStatusEnum.PAUSED
    pmax = build_pmax_campaign(
        client,
        "1234567890",
        name="PMax",
        daily_budget=10,
        final_url="https://example.com",
        business_name="Acme",
        headlines=["H1", "H2", "H3"],
        long_headline="Long headline here",
        descriptions=["D1", "D2"],
        logo_asset="customers/1/assets/3",
        marketing_image_asset="customers/1/assets/1",
        square_marketing_image_asset="customers/1/assets/2",
    )
    assert pmax[1].campaign_operation.create.status == client.enums.CampaignStatusEnum.PAUSED
    assert (
        pmax[1].campaign_operation.create.advertising_channel_type
        == client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
    )


def test_asset_group_text_ops() -> None:
    client = fake_ads_client()
    operations = build_asset_group_text_ops(
        client,
        "1234567890",
        asset_group_id="99",
        headlines=["New headline"],
        descriptions=["New description"],
    )
    assert len(operations) == 4
    assert operations[0].asset_operation.create.text_asset.text == "New headline"
    assert operations[1].asset_group_asset_operation.create.field_type == (
        client.enums.AssetFieldTypeEnum.HEADLINE
    )
