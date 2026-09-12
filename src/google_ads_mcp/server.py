"""MCP server exposing Google Ads campaign management tools."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__
from .ads_client import GoogleAdsService
from .config import ConfigError, missing_config_vars

mcp = MCPServer("google-ads-mcp", version=__version__)

_service: GoogleAdsService | None = None


def get_service() -> GoogleAdsService:
    """Return a lazily-created :class:`GoogleAdsService` singleton."""
    global _service
    if _service is None:
        _service = GoogleAdsService()
    return _service


def _guard() -> str | None:
    """Return a helpful error string when credentials are not configured."""
    missing = missing_config_vars()
    if missing:
        return (
            "Google Ads credentials are not configured. Missing environment "
            f"variables: {', '.join(missing)}. See .env.example for setup steps."
        )
    return None


@mcp.tool()
def health_check() -> dict[str, Any]:
    """Report server status and whether Google Ads credentials are configured."""
    missing = missing_config_vars()
    return {
        "status": "ok",
        "server": "google-ads-mcp",
        "credentials_configured": not missing,
        "missing_variables": missing,
    }


@mcp.tool()
def list_accessible_customers() -> dict[str, Any]:
    """List the Google Ads customer accounts accessible with the configured credentials."""
    error = _guard()
    if error:
        return {"error": error}
    try:
        return {"customers": get_service().list_accessible_customers()}
    except (ConfigError, Exception) as exc:  # noqa: BLE001 - surface API errors to caller
        return {"error": str(exc)}


@mcp.tool()
def list_campaigns(customer_id: str) -> dict[str, Any]:
    """List campaigns for a Google Ads customer account.

    Args:
        customer_id: The 10-digit customer id (dashes are allowed).
    """
    error = _guard()
    if error:
        return {"error": error}
    try:
        return {"campaigns": get_service().list_campaigns(customer_id)}
    except Exception as exc:  # noqa: BLE001 - surface API errors to caller
        return {"error": str(exc)}


@mcp.tool()
def set_campaign_status(
    customer_id: str, campaign_id: str, status: str
) -> dict[str, Any]:
    """Enable, pause, or remove a campaign.

    Args:
        customer_id: The 10-digit customer id (dashes are allowed).
        campaign_id: The numeric campaign id.
        status: One of ``ENABLED``, ``PAUSED``, or ``REMOVED``.
    """
    error = _guard()
    if error:
        return {"error": error}
    try:
        return get_service().set_campaign_status(customer_id, campaign_id, status)
    except Exception as exc:  # noqa: BLE001 - surface API/validation errors to caller
        return {"error": str(exc)}


@mcp.tool()
def update_campaign_budget(
    customer_id: str, budget_id: str, amount_micros: int
) -> dict[str, Any]:
    """Update the daily amount of a campaign budget.

    Args:
        customer_id: The 10-digit customer id (dashes are allowed).
        budget_id: The numeric campaign budget id.
        amount_micros: The new daily amount in micros (1_000_000 = 1 currency unit).
    """
    error = _guard()
    if error:
        return {"error": error}
    try:
        return get_service().update_campaign_budget(
            customer_id, budget_id, amount_micros
        )
    except Exception as exc:  # noqa: BLE001 - surface API/validation errors to caller
        return {"error": str(exc)}


def run() -> None:
    """Run the MCP server over stdio."""
    mcp.run()
