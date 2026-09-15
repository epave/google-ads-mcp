import pytest

from google_ads_mcp.gaql import build_gaql


def test_build_gaql_minimal() -> None:
    query = build_gaql(fields=["campaign.id"], resource="campaign")
    assert query.startswith("SELECT campaign.id FROM campaign")
    assert "PARAMETERS omit_unselected_resource_names=true" in query


def test_build_gaql_full() -> None:
    query = build_gaql(
        fields=["campaign.id", "metrics.clicks"],
        resource="campaign",
        conditions=["campaign.status = 'ENABLED'"],
        orderings=["metrics.clicks DESC"],
        limit=10,
    )
    assert "WHERE campaign.status = 'ENABLED'" in query
    assert "ORDER BY metrics.clicks DESC" in query
    assert "LIMIT 10" in query


def test_build_gaql_rejects_empty_fields() -> None:
    with pytest.raises(ValueError):
        build_gaql(fields=[], resource="campaign")
