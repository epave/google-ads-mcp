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
        "config_error",
        "yaml_present",
        "adc_present",
        "developer_token_present",
        "oauth_client_present",
        "refresh_token_present",
        "login_customer_id_configured",
    }
    assert info["credentials"]["config_error"] is None

def test_build_server_info_reads_yaml_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.delenv("GOOGLE_ADS_DEVELOPER_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_REFRESH_TOKEN", raising=False)
    yaml_path = tmp_path / "google-ads.yaml"
    yaml_path.write_text(
        "developer_token: yaml-dev-token\n"
        "client_id: yaml-client\n"
        "client_secret: yaml-secret\n"
        "refresh_token: yaml-refresh\n"
        "login_customer_id: '1112223333'\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, yaml_path=yaml_path)
    info = build_server_info(tool_names=["get_server_info"], settings=settings)
    assert info["credentials"]["config_source"] == "yaml"
    assert info["credentials"]["developer_token_present"] is True
    assert info["credentials"]["oauth_client_present"] is True
    assert info["credentials"]["refresh_token_present"] is True
    assert info["credentials"]["login_customer_id_configured"] is True
    assert "yaml-dev-token" not in str(info)
    assert "yaml-secret" not in str(info)


def test_credential_health_yaml_ignores_env_tokens(tmp_path, monkeypatch) -> None:
    """Active YAML source must not OR in env credential flags."""
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    yaml_path = tmp_path / "google-ads.yaml"
    yaml_path.write_text(
        "developer_token: yaml-only\nclient_id: yaml-client\nclient_secret: yaml-secret\n",
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        yaml_path=yaml_path,
        developer_token="env-token",
        refresh_token="env-refresh",
    )
    info = build_server_info(tool_names=["get_server_info"], settings=settings)
    assert info["credentials"]["config_source"] == "yaml"
    assert info["credentials"]["developer_token_present"] is True
    assert info["credentials"]["oauth_client_present"] is True
    # refresh_token only in env — must not appear when YAML is the active source
    assert info["credentials"]["refresh_token_present"] is False
    assert info["credentials"]["config_error"] is None


def test_credential_health_reports_missing_explicit_yaml(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    missing = tmp_path / "missing-google-ads.yaml"
    settings = Settings(
        _env_file=None,
        yaml_path=missing,
        developer_token="env-token",
        client_id="env-client",
        client_secret="env-secret",
        refresh_token="env-refresh",
    )
    info = build_server_info(tool_names=["get_server_info"], settings=settings)
    assert info["credentials"]["config_source"] == "yaml"
    assert info["credentials"]["config_error"]
    assert "does not exist" in info["credentials"]["config_error"]
    assert info["credentials"]["developer_token_present"] is False
    assert info["credentials"]["oauth_client_present"] is False
    assert info["credentials"]["refresh_token_present"] is False


def test_get_resource_metadata_respects_limit(monkeypatch) -> None:
    from types import SimpleNamespace

    from google_ads_mcp.tools import query as query_mod

    class FakePager:
        def __iter__(self):
            for i in range(50):
                yield SimpleNamespace(
                    name=f"campaign.field_{i}",
                    category=SimpleNamespace(name="ATTRIBUTE"),
                    data_type=SimpleNamespace(name="STRING"),
                    selectable=True,
                    filterable=True,
                    sortable=True,
                )

    class FakeService:
        def search_google_ads_fields(self, request=None, **kwargs):
            return FakePager()

    class FakeClient:
        def get_service(self, name):
            return FakeService()

    monkeypatch.setattr(query_mod, "get_client", lambda *_a, **_k: FakeClient())
    monkeypatch.setattr(query_mod, "run_ads_call", lambda fn, **kw: fn(**kw))
    result = query_mod.get_resource_metadata("campaign", limit=10)
    assert result["field_count"] == 10
    assert len(result["fields"]) == 10


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
