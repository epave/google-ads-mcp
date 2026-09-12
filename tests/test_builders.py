import pytest

from google_ads_mcp.builders.search import build_search_campaign


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
