import pytest
from google.ads.googleads.v25.common.types.metrics import SearchVolumeRange
from google.ads.googleads.v25.services.types.google_ads_service import GoogleAdsRow

from google_ads_mcp.gaql import build_gaql, fold_search_volume, format_output_row, format_output_value


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


def test_format_output_value_search_volume_uses_min_max() -> None:
    volume = SearchVolumeRange()
    volume.min = 100
    volume.max = 1000
    assert format_output_value(volume) == {"min": 100, "max": 1000}
    assert format_output_value(SearchVolumeRange()) == {}


def test_format_output_row_folds_search_volume_bounds() -> None:
    row = GoogleAdsRow()
    row.metrics.search_volume.min = 80
    row.metrics.search_volume.max = 120
    formatted = format_output_row(row, ["metrics.search_volume"])
    assert formatted["metrics.search_volume"] == {"min": 80, "max": 120}
    folded = fold_search_volume(
        {"metrics.search_volume.min": 10, "metrics.search_volume.max": 20, "metrics.impressions": 5}
    )
    assert folded["metrics.search_volume"] == {"min": 10, "max": 20}
