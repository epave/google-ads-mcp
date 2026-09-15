from types import SimpleNamespace

from google.ads.googleads.client import _DEFAULT_VERSION, _VALID_API_VERSIONS

from google_ads_mcp.client import (
    ADS_API_VERSION,
    get_client,
    reset_client_cache,
    resolve_login_customer_id,
)
from google_ads_mcp.config import Settings
from tests.fakes import fake_ads_client


def test_ads_api_version_tracks_library_default() -> None:
    assert ADS_API_VERSION == _DEFAULT_VERSION
    assert ADS_API_VERSION == _VALID_API_VERSIONS[0]
    assert fake_ads_client().version == ADS_API_VERSION


def test_resolve_login_uses_settings_unless_overridden() -> None:
    settings = Settings.model_validate({"login_customer_id": "111-111-1111"})
    assert resolve_login_customer_id(None, settings) == "1111111111"
    assert resolve_login_customer_id("none", settings) is None
    assert resolve_login_customer_id("", settings) is None
    assert resolve_login_customer_id("222-222-2222", settings) == "2222222222"


def test_get_client_rebuilds_when_login_changes(monkeypatch) -> None:
    made: list[SimpleNamespace] = []

    def fake_from_settings(settings, login_override=None):
        client = SimpleNamespace(login_customer_id=login_override)
        made.append(client)
        return client

    monkeypatch.setattr("google_ads_mcp.client._client_from_settings", fake_from_settings)
    monkeypatch.delenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", raising=False)
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    reset_client_cache()
    first = get_client("111-111-1111")
    second = get_client("222-222-2222")
    again = get_client("111-111-1111")
    assert first is not second
    assert first is again
    assert first.login_customer_id == "1111111111"
    assert second.login_customer_id == "2222222222"
    assert len(made) == 2
