"""Thin wrapper around the official Google Ads Python client.

The wrapper isolates all direct use of the ``google-ads`` library so the rest of
the codebase (and the tests) can depend on a small, well-defined surface. The
underlying client is created lazily on first use so the MCP server can start and
advertise its tools even before credentials are configured.
"""

from __future__ import annotations

from typing import Any

from .config import GoogleAdsConfig, _normalize_customer_id, load_config


class GoogleAdsService:
    """High-level operations for managing Google Ads campaigns."""

    def __init__(self, config: GoogleAdsConfig | None = None) -> None:
        self._config = config
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        """Return a cached ``GoogleAdsClient``, creating it on first access."""
        if self._client is None:
            # Imported lazily so the module can be imported without the
            # google-ads dependency being fully configured.
            from google.ads.googleads.client import GoogleAdsClient

            config = self._config or load_config()
            self._client = GoogleAdsClient.load_from_dict(config.to_client_dict())
        return self._client

    def list_accessible_customers(self) -> list[str]:
        """Return the resource names of customers the credentials can access."""
        service = self.client.get_service("CustomerService")
        response = service.list_accessible_customers()
        return list(response.resource_names)

    def list_campaigns(self, customer_id: str) -> list[dict[str, Any]]:
        """Return campaigns for ``customer_id`` with basic fields."""
        customer_id = _normalize_customer_id(customer_id)
        ga_service = self.client.get_service("GoogleAdsService")
        query = """
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                campaign_budget.amount_micros
            FROM campaign
            ORDER BY campaign.id
        """
        rows = ga_service.search(customer_id=customer_id, query=query)
        campaigns: list[dict[str, Any]] = []
        for row in rows:
            campaigns.append(
                {
                    "id": str(row.campaign.id),
                    "name": row.campaign.name,
                    "status": row.campaign.status.name,
                    "channel_type": row.campaign.advertising_channel_type.name,
                    "budget_micros": row.campaign_budget.amount_micros,
                }
            )
        return campaigns

    def set_campaign_status(
        self, customer_id: str, campaign_id: str, status: str
    ) -> dict[str, Any]:
        """Enable, pause, or remove a campaign.

        Args:
            status: One of ``ENABLED``, ``PAUSED`` or ``REMOVED``.
        """
        status = status.upper()
        valid = {"ENABLED", "PAUSED", "REMOVED"}
        if status not in valid:
            raise ValueError(f"status must be one of {sorted(valid)}, got {status!r}")

        customer_id = _normalize_customer_id(customer_id)
        campaign_service = self.client.get_service("CampaignService")
        operation = self.client.get_type("CampaignOperation")
        campaign = operation.update
        campaign.resource_name = campaign_service.campaign_path(customer_id, campaign_id)
        campaign.status = self.client.enums.CampaignStatusEnum[status]

        field_mask = self.client.get_type("FieldMask")
        field_mask.paths.append("status")
        operation.update_mask.CopyFrom(field_mask)

        response = campaign_service.mutate_campaigns(
            customer_id=customer_id, operations=[operation]
        )
        return {"resource_name": response.results[0].resource_name, "status": status}

    def update_campaign_budget(
        self, customer_id: str, budget_id: str, amount_micros: int
    ) -> dict[str, Any]:
        """Update the daily amount (in micros) of a campaign budget."""
        customer_id = _normalize_customer_id(customer_id)
        budget_service = self.client.get_service("CampaignBudgetService")
        operation = self.client.get_type("CampaignBudgetOperation")
        budget = operation.update
        budget.resource_name = budget_service.campaign_budget_path(
            customer_id, budget_id
        )
        budget.amount_micros = int(amount_micros)

        field_mask = self.client.get_type("FieldMask")
        field_mask.paths.append("amount_micros")
        operation.update_mask.CopyFrom(field_mask)

        response = budget_service.mutate_campaign_budgets(
            customer_id=customer_id, operations=[operation]
        )
        return {
            "resource_name": response.results[0].resource_name,
            "amount_micros": int(amount_micros),
        }
