"""Server health and discovery without revealing secrets."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from google_ads_mcp import __version__
from google_ads_mcp.client import ADS_API_VERSION
from google_ads_mcp.config import Settings, load_settings


def _flags_from_mapping(data: dict[str, Any]) -> tuple[bool, bool, bool, bool, bool]:
    nested = data.get("google_ads") if isinstance(data.get("google_ads"), dict) else {}
    installed = data.get("installed") if isinstance(data.get("installed"), dict) else {}
    merged = {**installed, **nested, **data}
    return (
        bool(merged.get("developer_token") or merged.get("developerToken")),
        bool(merged.get("client_id") or merged.get("clientId")),
        bool(merged.get("client_secret") or merged.get("clientSecret")),
        bool(merged.get("refresh_token") or merged.get("refreshToken")),
        bool(merged.get("login_customer_id") or merged.get("loginCustomerId")),
    )


def _load_yaml_config(path: Any) -> dict[str, Any] | None:
    try:
        import yaml
    except ImportError:
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _credential_health(settings: Settings) -> dict[str, Any]:
    """Booleans only — never return token values or file contents.

    Presence flags mirror client load order (YAML → ADC → env): only the active
    source is inspected, not OR'd across files and environment.
    """
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

    # Match _client_from_settings: YAML wins, then ADC, then env.
    if yaml_path is not None:
        source = "yaml"
        yaml_data = _load_yaml_config(yaml_path) or {}
        (
            has_developer_token,
            has_client_id,
            has_client_secret,
            has_refresh_token,
            has_login_customer_id,
        ) = _flags_from_mapping(yaml_data)
    elif adc_path is not None:
        source = "adc"
        try:
            adc = settings.load_adc() or {}
        except (OSError, ValueError, json.JSONDecodeError):
            adc = {}
        (
            has_developer_token,
            has_client_id,
            has_client_secret,
            has_refresh_token,
            has_login_customer_id,
        ) = _flags_from_mapping(adc)
        # client_config_from_adc lets env fill gaps on the ADC path.
        has_developer_token = has_developer_token or bool(settings.developer_token)
        has_client_id = has_client_id or bool(settings.client_id)
        has_client_secret = has_client_secret or bool(settings.client_secret)
        has_refresh_token = has_refresh_token or bool(settings.refresh_token)
        has_login_customer_id = has_login_customer_id or bool(settings.login_customer_id)
    elif settings.developer_token or settings.client_id or settings.refresh_token:
        source = "env"
        has_developer_token = bool(settings.developer_token)
        has_client_id = bool(settings.client_id)
        has_client_secret = bool(settings.client_secret)
        has_refresh_token = bool(settings.refresh_token)
        has_login_customer_id = bool(settings.login_customer_id)
    else:
        source = "none"
        has_developer_token = False
        has_client_id = False
        has_client_secret = False
        has_refresh_token = False
        has_login_customer_id = False

    return {
        "config_source": source,
        "yaml_present": yaml_path is not None,
        "adc_present": adc_path is not None,
        "developer_token_present": has_developer_token,
        "oauth_client_present": has_client_id and has_client_secret,
        "refresh_token_present": has_refresh_token,
        "login_customer_id_configured": has_login_customer_id,
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
