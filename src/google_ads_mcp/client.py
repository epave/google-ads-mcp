"""Google Ads API client factory."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from google_ads_mcp.config import Settings, load_settings
from google_ads_mcp.errors import AdsError, format_google_ads_exception
from google_ads_mcp.ids import clean_customer_id

logger = logging.getLogger(__name__)


def _client_from_settings(settings: Settings) -> GoogleAdsClient:
    yaml_path = settings.resolved_yaml_path()
    if yaml_path is not None:
        logger.info("Loading Google Ads client from %s", yaml_path)
        return GoogleAdsClient.load_from_storage(str(yaml_path))

    if not settings.developer_token:
        raise AdsError(
            "Missing Google Ads credentials. Set GOOGLE_ADS_DEVELOPER_TOKEN and OAuth "
            "fields, or provide google-ads.yaml (see README)."
        )
    if not (settings.client_id and settings.client_secret and settings.refresh_token):
        raise AdsError(
            "Missing OAuth credentials. Run `google-ads-mcp-auth` or set "
            "GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, and GOOGLE_ADS_REFRESH_TOKEN."
        )

    config: dict[str, Any] = {
        "developer_token": settings.developer_token,
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "refresh_token": settings.refresh_token,
        "use_proto_plus": True,
    }
    if settings.login_customer_id:
        config["login_customer_id"] = clean_customer_id(settings.login_customer_id)
    return GoogleAdsClient.load_from_dict(config)


@lru_cache(maxsize=1)
def get_client() -> GoogleAdsClient:
    return _client_from_settings(load_settings())


def reset_client_cache() -> None:
    get_client.cache_clear()


def run_ads_call(fn, *args, **kwargs):
    """Execute an API callable and map GoogleAdsException to AdsError."""
    try:
        return fn(*args, **kwargs)
    except GoogleAdsException as exc:
        raise format_google_ads_exception(exc) from exc
