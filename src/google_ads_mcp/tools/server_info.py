"""Server health and discovery without revealing secrets."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from google_ads_mcp import __version__
from google_ads_mcp.client import ADS_API_VERSION
from google_ads_mcp.config import Settings, load_settings


def _credential_health(settings: Settings) -> dict[str, Any]:
    """Booleans only — never return token values or file contents."""
    yaml_path = None
    adc_path = None
    try:
        yaml_path = settings.resolved_yaml_path()
    except FileNotFoundError:
        yaml_path = None
    try:
        adc_path = settings.resolved_adc_path()
    except FileNotFoundError:
        adc_path = None

    adc: dict[str, Any] | None = None
    if adc_path is not None:
        try:
            adc = settings.load_adc()
        except (OSError, ValueError, json.JSONDecodeError):
            adc = None

    has_developer_token = bool(settings.developer_token)
    has_client_id = bool(settings.client_id)
    has_client_secret = bool(settings.client_secret)
    has_refresh_token = bool(settings.refresh_token)

    if adc:
        nested = adc.get("google_ads") if isinstance(adc.get("google_ads"), dict) else {}
        installed = adc.get("installed") if isinstance(adc.get("installed"), dict) else {}
        merged = {**installed, **nested, **adc}
        has_developer_token = has_developer_token or bool(
            merged.get("developer_token") or merged.get("developerToken")
        )
        has_client_id = has_client_id or bool(merged.get("client_id") or merged.get("clientId"))
        has_client_secret = has_client_secret or bool(
            merged.get("client_secret") or merged.get("clientSecret")
        )
        has_refresh_token = has_refresh_token or bool(
            merged.get("refresh_token") or merged.get("refreshToken")
        )

    source = "none"
    if yaml_path is not None:
        source = "yaml"
    elif adc_path is not None:
        source = "adc"
    elif settings.developer_token or settings.client_id or settings.refresh_token:
        source = "env"

    return {
        "config_source": source,
        "yaml_present": yaml_path is not None,
        "adc_present": adc_path is not None,
        "developer_token_present": has_developer_token,
        "oauth_client_present": has_client_id and has_client_secret,
        "refresh_token_present": has_refresh_token,
        "login_customer_id_configured": bool(settings.login_customer_id),
    }


def build_server_info(
    *,
    tool_names: list[str] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    cfg = settings or load_settings()
    allowlist = cfg.allowlist()
    return {
        "server_version": __version__,
        "google_ads_api_version": ADS_API_VERSION,
        "write_enabled": cfg.write_enabled,
        "skip_confirm": cfg.skip_confirm,
        "audience_insights_enabled": cfg.audience_insights_enabled,
        "allowed_customer_ids": sorted(allowlist) if allowlist is not None else None,
        "preview_ttl_seconds": cfg.preview_ttl_seconds,
        "tools": sorted(tool_names or []),
        "credentials": _credential_health(cfg),
    }


def register(mcp: FastMCP) -> None:
    async def get_server_info() -> dict[str, Any]:
        """Return server version, API version, write state, tools, and credential health.

        Credential fields are booleans only — secrets are never returned. Safe to call
        when writes are disabled or Ads credentials are missing.
        """
        listed = await mcp.list_tools(run_middleware=False)
        names = [tool.name for tool in listed]
        return build_server_info(tool_names=names)

    mcp.tool(get_server_info)
