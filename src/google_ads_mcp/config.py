"""Environment and YAML-backed settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_state_dir() -> Path:
    return Path.home() / ".google-ads-mcp"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    developer_token: str | None = Field(default=None, validation_alias="GOOGLE_ADS_DEVELOPER_TOKEN")
    client_id: str | None = Field(default=None, validation_alias="GOOGLE_ADS_CLIENT_ID")
    client_secret: str | None = Field(default=None, validation_alias="GOOGLE_ADS_CLIENT_SECRET")
    refresh_token: str | None = Field(default=None, validation_alias="GOOGLE_ADS_REFRESH_TOKEN")
    login_customer_id: str | None = Field(default=None, validation_alias="GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    yaml_path: Path | None = Field(default=None, validation_alias="GOOGLE_ADS_CONFIGURATION_FILE_PATH")
    write_enabled: bool = Field(default=False, validation_alias="GOOGLE_ADS_WRITE_ENABLED")
    skip_confirm: bool = Field(default=False, validation_alias="GOOGLE_ADS_SKIP_CONFIRM")
    allowed_customer_ids: str | None = Field(
        default=None, validation_alias="GOOGLE_ADS_ALLOWED_CUSTOMER_IDS"
    )
    budget_increase_cap: float = Field(default=0.20, validation_alias="GOOGLE_ADS_BUDGET_INCREASE_CAP")
    db_path: Path | None = Field(default=None, validation_alias="GOOGLE_ADS_MCP_DB")
    preview_ttl_seconds: int = Field(default=15 * 60, validation_alias="GOOGLE_ADS_PREVIEW_TTL_SECONDS")

    def allowlist(self) -> set[str] | None:
        if not self.allowed_customer_ids:
            return None
        from google_ads_mcp.ids import clean_customer_id

        return {clean_customer_id(item) for item in self.allowed_customer_ids.split(",") if item.strip()}

    def resolved_yaml_path(self) -> Path | None:
        if self.yaml_path and self.yaml_path.exists():
            return self.yaml_path
        candidates = [
            Path.cwd() / "google-ads.yaml",
            Path.home() / "google-ads.yaml",
            default_state_dir() / "google-ads.yaml",
        ]
        for path in candidates:
            if path.exists():
                return path
        return None

    def resolved_db_path(self) -> Path:
        if self.db_path:
            path = self.db_path
        else:
            path = default_state_dir() / "state.duckdb"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


def load_settings() -> Settings:
    return Settings()
