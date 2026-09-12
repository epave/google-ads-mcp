"""Tests for the Google Ads MCP server.

These tests exercise the MCP tool surface end-to-end via an in-memory client
session, and verify the Google Ads service wrapper against a fake client so no
real credentials or network access are required.
"""

from __future__ import annotations

import json

import pytest

from google_ads_mcp import server
from google_ads_mcp.ads_client import GoogleAdsService
from google_ads_mcp.config import GoogleAdsConfig


def _text(result) -> dict:
    """Extract the JSON payload returned by an MCP tool call."""
    assert result.content, "expected tool to return content"
    return json.loads(result.content[0].text)


@pytest.fixture(autouse=True)
def clear_credentials(monkeypatch):
    """Ensure tests run without ambient Google Ads credentials."""
    for name in (
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    server._service = None


async def test_list_tools_exposes_campaign_management():
    tools = await server.mcp.list_tools()
    names = {tool.name for tool in tools}
    assert {
        "health_check",
        "list_accessible_customers",
        "list_campaigns",
        "set_campaign_status",
        "update_campaign_budget",
    } <= names


async def test_health_check_reports_missing_credentials():
    result = await server.mcp.call_tool("health_check", {})
    payload = _text(result)
    assert payload["status"] == "ok"
    assert payload["credentials_configured"] is False
    assert "GOOGLE_ADS_DEVELOPER_TOKEN" in payload["missing_variables"]


async def test_health_check_reports_configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "dev")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "refresh")
    result = await server.mcp.call_tool("health_check", {})
    payload = _text(result)
    assert payload["credentials_configured"] is True
    assert payload["missing_variables"] == []


async def test_list_campaigns_without_credentials_returns_error():
    result = await server.mcp.call_tool("list_campaigns", {"customer_id": "123"})
    payload = _text(result)
    assert "error" in payload
    assert "not configured" in payload["error"]


async def test_set_campaign_status_validates_status():
    config = GoogleAdsConfig("dev", "cid", "secret", "refresh")
    service = GoogleAdsService(config=config)
    with pytest.raises(ValueError):
        service.set_campaign_status("123", "456", "BOGUS")


# --- Service wrapper tests using a fake Google Ads client -----------------


class _FakeRow:
    def __init__(self, data):
        self.campaign = data["campaign"]
        self.campaign_budget = data["campaign_budget"]


class _Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeGoogleAdsService:
    def __init__(self, rows):
        self._rows = rows
        self.last_query = None
        self.last_customer_id = None

    def search(self, customer_id, query):
        self.last_customer_id = customer_id
        self.last_query = query
        return self._rows


class _FakeClient:
    def __init__(self, rows):
        self._service = _FakeGoogleAdsService(rows)

    def get_service(self, name):
        assert name == "GoogleAdsService"
        return self._service


def test_list_campaigns_normalizes_id_and_maps_rows():
    rows = [
        _FakeRow(
            {
                "campaign": _Obj(
                    id=42,
                    name="Spring Sale",
                    status=_Obj(name="ENABLED"),
                    advertising_channel_type=_Obj(name="SEARCH"),
                ),
                "campaign_budget": _Obj(amount_micros=5_000_000),
            }
        )
    ]
    service = GoogleAdsService(config=GoogleAdsConfig("d", "c", "s", "r"))
    service._client = _FakeClient(rows)

    campaigns = service.list_campaigns("123-456-7890")

    assert service._client._service.last_customer_id == "1234567890"
    assert campaigns == [
        {
            "id": "42",
            "name": "Spring Sale",
            "status": "ENABLED",
            "channel_type": "SEARCH",
            "budget_micros": 5_000_000,
        }
    ]
