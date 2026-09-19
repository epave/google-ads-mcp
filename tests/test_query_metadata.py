"""Tests for FieldService metadata query and get_server_info."""

from __future__ import annotations

import asyncio

import pytest

from google_ads_mcp import __version__
from google_ads_mcp.client import ADS_API_VERSION
from google_ads_mcp.config import Settings
from google_ads_mcp.server import create_server
from google_ads_mcp.tools.query import build_field_metadata_query
from google_ads_mcp.tools.server_info import build_server_info


def test_field_metadata_query_is_v25_syntax() -> None:
    query = build_field_metadata_query("campaign", limit=50)
    assert "FROM" not in query
    assert "google_ads_field" not in query
    assert "WHERE name LIKE 'campaign.%'" in query
    assert query.startswith("SELECT name, category, data_type, selectable, filterable, sortable")
    assert "LIMIT" not in query


def test_field_metadata_query_rejects_injection() -> None:
    with pytest.raises(ValueError):
        build_field_metadata_query("campaign'; DROP TABLE x")


def test_build_server_info_no_secrets(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "false")
    monkeypatch.setenv("GOOGLE_ADS_ALLOWED_CUSTOMER_IDS", "1234567890, 0987654321")
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "secret-token-value")
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CONFIGURATION_FILE_PATH", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_ADC_PATH", raising=False)
    settings = Settings(
        _env_file=None,
        developer_token="secret-token-value",
        write_enabled=False,
        allowed_customer_ids="1234567890, 0987654321",
    )
    info = build_server_info(tool_names=["get_server_info", "search"], settings=settings)
    assert info["server_version"] == __version__
    assert info["google_ads_api_version"] == ADS_API_VERSION
    assert info["write_enabled"] is False
    assert info["allowed_customer_ids"] == ["0987654321", "1234567890"]
    assert "get_server_info" in info["tools"]
    blob = str(info)
    assert "secret-token-value" not in blob
    assert info["credentials"]["developer_token_present"] is True
    assert "client_secret" not in info["credentials"]
    assert "refresh_token" not in info["credentials"]
    assert set(info["credentials"].keys()) == {
        "config_source",
        "yaml_present",
        "adc_present",
        "developer_token_present",
        "oauth_client_present",
        "refresh_token_present",
        "login_customer_id_configured",
    }

def test_get_server_info_registered(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.delenv("GOOGLE_ADS_AUDIENCE_INSIGHTS_ENABLED", raising=False)
    server = create_server()
    tools = {tool.name for tool in asyncio.run(server.list_tools(run_middleware=False))}
    assert "get_server_info" in tools
    listed = asyncio.run(server.list_tools(run_middleware=False))
    info = build_server_info(tool_names=[t.name for t in listed])
    assert "get_server_info" in info["tools"]
    assert len(info["tools"]) >= 30
