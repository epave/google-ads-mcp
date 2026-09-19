"""Builders and validators for campaign-level text assets (callouts, snippets)."""

from __future__ import annotations

from typing import Any

from google_ads_mcp.errors import AdsError

CALLOUT_MAX_CHARS = 25
SNIPPET_VALUE_MAX_CHARS = 25
SNIPPET_MIN_VALUES = 3
SNIPPET_MAX_VALUES = 10

# Official Structured Snippet headers (Google Ads UI / API).
STRUCTURED_SNIPPET_HEADERS = frozenset(
    {
        "Amenities",
        "Brands",
        "Courses",
        "Degree programs",
        "Destinations",
        "Featured hotels",
        "Insurance coverage",
        "Models",
        "Neighborhoods",
        "Services",
        "Shows",
        "Styles",
        "Types",
    }
)


def validate_callout_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise AdsError("Callout text must not be empty.")
    if len(cleaned) > CALLOUT_MAX_CHARS:
        raise AdsError(
            f"Callout exceeds {CALLOUT_MAX_CHARS} characters ({len(cleaned)}): {cleaned!r}"
        )
    return cleaned


def validate_structured_snippet(header: str, values: list[str]) -> tuple[str, list[str]]:
    hdr = header.strip()
    if hdr not in STRUCTURED_SNIPPET_HEADERS:
        allowed = ", ".join(sorted(STRUCTURED_SNIPPET_HEADERS))
        raise AdsError(f"Invalid structured-snippet header {hdr!r}. Allowed: {allowed}")
    cleaned: list[str] = []
    for value in values:
        item = value.strip()
        if not item:
            raise AdsError("Structured-snippet values must not be empty.")
        if len(item) > SNIPPET_VALUE_MAX_CHARS:
            raise AdsError(
                f"Structured-snippet value exceeds {SNIPPET_VALUE_MAX_CHARS} characters "
                f"({len(item)}): {item!r}"
            )
        cleaned.append(item)
    if len(cleaned) < SNIPPET_MIN_VALUES or len(cleaned) > SNIPPET_MAX_VALUES:
        raise AdsError(
            f"Structured snippets require {SNIPPET_MIN_VALUES}–{SNIPPET_MAX_VALUES} values "
            f"(got {len(cleaned)})."
        )
    return hdr, cleaned


def set_asset_temp_resource_name(client, operation: Any, customer_id: str, temp_id: int) -> str:
    service = client.get_service("AssetService")
    resource_name = service.asset_path(customer_id, str(temp_id))
    operation.asset_operation.create.resource_name = resource_name
    return resource_name


def build_campaign_asset_create(
    client,
    *,
    customer_id: str,
    campaign_id: str,
    asset_resource_name: str,
    field_type: str,
) -> Any:
    op = client.get_type("MutateOperation")
    link = op.campaign_asset_operation.create
    campaign_service = client.get_service("CampaignService")
    link.campaign = campaign_service.campaign_path(customer_id, campaign_id)
    link.asset = asset_resource_name
    link.field_type = getattr(client.enums.AssetFieldTypeEnum, field_type)
    return op


def build_campaign_asset_remove(client, *, resource_name: str) -> Any:
    op = client.get_type("MutateOperation")
    op.campaign_asset_operation.remove = resource_name
    return op


def empty_asset_diff() -> dict[str, list[Any]]:
    return {
        "created_assets": [],
        "reused_assets": [],
        "attached": [],
        "already_attached": [],
        "detached": [],
        "unchanged": [],
    }
