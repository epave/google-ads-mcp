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


def _load_yaml_config(path: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Return (mapping, error). error is set when the file exists but cannot be used."""
    try:
        import yaml
    except ImportError:
        return None, "PyYAML is not installed; cannot read google-ads.yaml"
    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except Exception as exc:
        return None, f"YAML config is unreadable or malformed ({type(exc).__name__})"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, "YAML config must be a mapping"
    return data, None


def _empty_flags() -> dict[str, bool]:
    return {
        "developer_token_present": False,
        "oauth_client_present": False,
        "refresh_token_present": False,
        "login_customer_id_configured": False,
    }


def _credential_health(settings: Settings) -> dict[str, Any]:
    """Booleans only — never return token values or file contents.

    Presence flags mirror client load order (YAML → ADC → env): only the active
    source is inspected, not OR'd across files and environment.
    Explicit missing paths and unreadable files surface as config_error.
    """
    empty = _empty_flags()

    # Explicit YAML path that does not exist: client raises and never falls through.
    if settings.yaml_path is not None and not settings.yaml_path.exists():
        return {
            "config_source": "yaml",
            "config_error": (
                f"GOOGLE_ADS_CONFIGURATION_FILE_PATH={settings.yaml_path} does not exist"
            ),
            "yaml_present": False,
            "adc_present": False,
            **empty,
        }

    yaml_path = None
    try:
        yaml_path = settings.resolved_yaml_path()
    except FileNotFoundError:
        yaml_path = None

    # YAML wins — a broken ADC path is irrelevant when YAML is available.
    if yaml_path is not None:
        yaml_data, yaml_error = _load_yaml_config(yaml_path)
        adc_present = False
        try:
            adc_present = settings.resolved_adc_path() is not None
        except FileNotFoundError:
            adc_present = False
        if yaml_error is not None:
            return {
                "config_source": "yaml",
                "config_error": yaml_error,
                "yaml_present": True,
                "adc_present": adc_present,
                **empty,
            }
        (
            has_developer_token,
            has_client_id,
            has_client_secret,
            has_refresh_token,
            has_login_customer_id,
        ) = _flags_from_mapping(yaml_data or {})
        return {
            "config_source": "yaml",
            "config_error": None,
            "yaml_present": True,
            "adc_present": adc_present,
            "developer_token_present": has_developer_token,
            "oauth_client_present": has_client_id and has_client_secret,
            "refresh_token_present": has_refresh_token,
            "login_customer_id_configured": has_login_customer_id,
        }

    # No YAML: explicit missing ADC is fatal (client would raise next).
    if settings.adc_path is not None and not settings.adc_path.exists():
        return {
            "config_source": "adc",
            "config_error": f"GOOGLE_ADS_ADC_PATH={settings.adc_path} does not exist",
            "yaml_present": False,
            "adc_present": False,
            **empty,
        }

    adc_path = None
    try:
        adc_path = settings.resolved_adc_path()
    except FileNotFoundError:
        adc_path = None

    if adc_path is not None:
        try:
            adc = settings.load_adc()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "config_source": "adc",
                "config_error": f"ADC file is unreadable or malformed ({type(exc).__name__})",
                "yaml_present": False,
                "adc_present": True,
                **empty,
            }
        if not isinstance(adc, dict):
            return {
                "config_source": "adc",
                "config_error": "ADC file must contain a JSON object",
                "yaml_present": False,
                "adc_present": True,
                **empty,
            }
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
        return {
            "config_source": "adc",
            "config_error": None,
            "yaml_present": False,
            "adc_present": True,
            "developer_token_present": has_developer_token,
            "oauth_client_present": has_client_id and has_client_secret,
            "refresh_token_present": has_refresh_token,
            "login_customer_id_configured": has_login_customer_id,
        }

    if settings.developer_token or settings.client_id or settings.refresh_token:
        return {
            "config_source": "env",
            "config_error": None,
            "yaml_present": False,
            "adc_present": False,
            "developer_token_present": bool(settings.developer_token),
            "oauth_client_present": bool(settings.client_id) and bool(settings.client_secret),
            "refresh_token_present": bool(settings.refresh_token),
            "login_customer_id_configured": bool(settings.login_customer_id),
        }

    return {
        "config_source": "none",
        "config_error": None,
        "yaml_present": False,
        "adc_present": False,
        **empty,
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
