from google_ads_mcp.ids import clean_customer_id, resource_id


def test_clean_customer_id_strips_dashes() -> None:
    assert clean_customer_id("123-456-7890") == "1234567890"


def test_resource_id() -> None:
    assert resource_id("customers/1234567890/campaigns/99") == "99"
