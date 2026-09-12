from pathlib import Path

import pytest

from google_ads_mcp.client import client_config_from_adc
from google_ads_mcp.config import Settings
from google_ads_mcp.errors import AdsError


def test_resolved_adc_path(tmp_path: Path) -> None:
    adc = tmp_path / "adc.json"
    adc.write_text('{"developer_token": "tok"}', encoding="utf-8")
    settings = Settings.model_validate({"adc_path": adc})
    assert settings.resolved_adc_path() == adc
    assert settings.load_adc()["developer_token"] == "tok"


def test_adc_maps_authorized_user_fields() -> None:
    settings = Settings.model_validate({})
    config = client_config_from_adc(
        {
            "type": "authorized_user",
            "client_id": "id.apps.googleusercontent.com",
            "client_secret": "secret",
            "refresh_token": "1//refresh",
            "developer_token": "devtok",
            "login_customer_id": "123-456-7890",
        },
        settings,
    )
    assert config["developer_token"] == "devtok"
    assert config["client_id"].endswith("googleusercontent.com")
    assert config["login_customer_id"] == "1234567890"
    assert config["use_proto_plus"] is True


def test_adc_requires_developer_token() -> None:
    settings = Settings.model_validate({})
    with pytest.raises(AdsError, match="developer_token"):
        client_config_from_adc(
            {
                "type": "authorized_user",
                "client_id": "id",
                "client_secret": "secret",
                "refresh_token": "refresh",
            },
            settings,
        )
