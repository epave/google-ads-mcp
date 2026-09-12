"""Configuration loading for the Google Ads MCP server.

Credentials are read from environment variables so that no secrets need to be
committed to the repository. See ``.env.example`` for the full list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

REQUIRED_VARS = (
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
)


@dataclass(frozen=True)
class GoogleAdsConfig:
    """Credentials and settings for the Google Ads API client."""

    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    login_customer_id: str | None = None

    def to_client_dict(self) -> dict[str, str]:
        """Return a config dict compatible with ``GoogleAdsClient.load_from_dict``."""
        config: dict[str, str] = {
            "developer_token": self.developer_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "use_proto_plus": True,
        }
        if self.login_customer_id:
            config["login_customer_id"] = _normalize_customer_id(self.login_customer_id)
        return config


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _normalize_customer_id(customer_id: str) -> str:
    """Strip dashes/whitespace from a customer id (e.g. ``123-456-7890``)."""
    return customer_id.replace("-", "").replace(" ", "").strip()


def missing_config_vars() -> list[str]:
    """Return the list of required environment variables that are not set."""
    return [name for name in REQUIRED_VARS if not os.environ.get(name)]


def load_config() -> GoogleAdsConfig:
    """Load configuration from the environment.

    Raises:
        ConfigError: If any required environment variable is missing.
    """
    missing = missing_config_vars()
    if missing:
        raise ConfigError(
            "Missing required Google Ads credentials: "
            + ", ".join(missing)
            + ". See .env.example for setup instructions."
        )

    return GoogleAdsConfig(
        developer_token=os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        client_id=os.environ["GOOGLE_ADS_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        refresh_token=os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        login_customer_id=os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID"),
    )
