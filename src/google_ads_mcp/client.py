"""Google Ads API client factory."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from google.ads.googleads.client import _DEFAULT_VERSION as ADS_API_VERSION
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from google_ads_mcp.config import Settings, load_settings
from google_ads_mcp.errors import AdsError, format_google_ads_exception
from google_ads_mcp.ids import clean_customer_id

logger = logging.getLogger(__name__)


def _pick(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        if data.get(name):
            return data[name]
    return None


def client_config_from_adc(adc: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Map ~/.config/google-ads-mcp/adc.json (or similar) to a GoogleAdsClient dict."""
    nested = adc.get("google_ads") if isinstance(adc.get("google_ads"), dict) else {}
    installed = adc.get("installed") if isinstance(adc.get("installed"), dict) else {}
    merged = {**installed, **nested, **adc}

    developer_token = settings.developer_token or _pick(merged, "developer_token", "developerToken")
    login_customer_id = settings.login_customer_id or _pick(
        merged, "login_customer_id", "loginCustomerId"
    )
    client_id = settings.client_id or _pick(merged, "client_id", "clientId")
    client_secret = settings.client_secret or _pick(merged, "client_secret", "clientSecret")
    refresh_token = settings.refresh_token or _pick(merged, "refresh_token", "refreshToken")
    use_adc_flag = bool(merged.get("use_application_default_credentials")) or merged.get(
        "type"
    ) in {"authorized_user", "service_account"}

    if not developer_token:
        raise AdsError(
            "ADC file is missing developer_token. Add it to adc.json or set "
            "GOOGLE_ADS_DEVELOPER_TOKEN."
        )

    config: dict[str, Any] = {"developer_token": developer_token, "use_proto_plus": True}
    if login_customer_id:
        config["login_customer_id"] = clean_customer_id(str(login_customer_id))

    if client_id and client_secret and refresh_token:
        config.update(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            }
        )
        return config
    if use_adc_flag:
        config["use_application_default_credentials"] = True
        return config
    raise AdsError(
        "ADC file needs client_id, client_secret, and refresh_token "
        "(authorized_user) or a usable Application Default Credentials type."
    )


def resolve_login_customer_id(
    explicit: str | None = None,
    settings: Settings | None = None,
) -> str | None:
    """Resolve the login-customer header.

    ``None`` uses ``GOOGLE_ADS_LOGIN_CUSTOMER_ID`` / settings.
    Empty, ``none``, ``null``, or ``-`` forces no MCC header (needed when a
    cached manager header breaks client-account reads).
    """
    cfg = settings or load_settings()
    if explicit is not None:
        value = str(explicit).strip()
        if not value or value.lower() in {"none", "null", "-"}:
            return None
        return clean_customer_id(value)
    if cfg.login_customer_id:
        return clean_customer_id(cfg.login_customer_id)
    return None


def _apply_login(client: GoogleAdsClient, login_customer_id: str | None) -> GoogleAdsClient:
    client.login_customer_id = login_customer_id
    return client


def _client_from_settings(
    settings: Settings, login_override: str | None = None
) -> GoogleAdsClient:
    yaml_path = settings.resolved_yaml_path()
    if yaml_path is not None:
        logger.info("Loading Google Ads client from %s (API %s)", yaml_path, ADS_API_VERSION)
        return _apply_login(
            GoogleAdsClient.load_from_storage(str(yaml_path), version=ADS_API_VERSION),
            login_override,
        )

    adc = settings.load_adc()
    if adc is not None:
        adc_path = settings.resolved_adc_path()
        logger.info("Loading Google Ads client from ADC %s (API %s)", adc_path, ADS_API_VERSION)
        config = client_config_from_adc(adc, settings)
        if login_override:
            config["login_customer_id"] = login_override
        else:
            config.pop("login_customer_id", None)
        if config.get("use_application_default_credentials") and adc_path is not None:
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(adc_path))
        return _apply_login(
            GoogleAdsClient.load_from_dict(config, version=ADS_API_VERSION),
            login_override,
        )

    if not settings.developer_token:
        raise AdsError(
            "Missing Google Ads credentials. Set GOOGLE_ADS_DEVELOPER_TOKEN and OAuth "
            "fields, provide google-ads.yaml, or ~/.config/google-ads-mcp/adc.json."
        )
    if not (settings.client_id and settings.client_secret and settings.refresh_token):
        raise AdsError(
            "Missing OAuth credentials. Run `google-ads-mcp auth` or set "
            "GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, and GOOGLE_ADS_REFRESH_TOKEN."
        )

    config: dict[str, Any] = {
        "developer_token": settings.developer_token,
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "refresh_token": settings.refresh_token,
        "use_proto_plus": True,
    }
    if login_override:
        config["login_customer_id"] = login_override
    logger.info("Loading Google Ads client from env (API %s)", ADS_API_VERSION)
    return _apply_login(
        GoogleAdsClient.load_from_dict(config, version=ADS_API_VERSION),
        login_override,
    )


@lru_cache(maxsize=8)
def _cached_client(resolved_login: str | None) -> GoogleAdsClient:
    return _client_from_settings(load_settings(), resolved_login)


def get_client(login_customer_id: str | None = None) -> GoogleAdsClient:
    """Return a process-cached client for the resolved login-customer header.

    A different ``login_customer_id`` rebuilds the client instead of reusing a
    stale MCC header. Pass ``none`` to omit the header even if settings set one.
    """
    return _cached_client(resolve_login_customer_id(login_customer_id))


def reset_client_cache() -> None:
    _cached_client.cache_clear()


def run_ads_call(fn, *args, **kwargs):
    """Execute an API callable and map GoogleAdsException to AdsError."""
    try:
        return fn(*args, **kwargs)
    except GoogleAdsException as exc:
        raise format_google_ads_exception(exc) from exc
