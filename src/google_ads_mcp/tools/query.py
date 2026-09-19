"""Official-parity GAQL search and resource metadata."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp.client import get_client, run_ads_call
from google_ads_mcp.gaql import build_gaql
from google_ads_mcp.gaql import search as run_search
from google_ads_mcp.ids import clean_customer_id


def build_field_metadata_query(resource: str, limit: int = 200) -> str:
    """Build a GoogleAdsFieldService catalog query (API v25+).

    FieldService queries must not include a FROM clause. Pagination is controlled
    by the RPC page_size, not a GAQL LIMIT clause.
    """
    safe = resource.strip()
    if not safe or any(ch in safe for ch in ("'", '"', ";", "\\", "\n", "\r")):
        raise ValueError(f"Invalid resource name: {resource!r}")
    # limit is applied via page_size on the RPC; keep the signature for callers.
    _ = int(limit)
    return (
        "SELECT name, category, data_type, selectable, filterable, sortable "
        f"WHERE name LIKE '{safe}.%'"
    )


def search(
    customer_id: str,
    fields: list[str],
    resource: str,
    conditions: list[str] | None = None,
    orderings: list[str] | None = None,
    limit: int | None = 100,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Run a Google Ads Query Language (GAQL) search.

    Same capability as the official Google Ads MCP `search` tool. Example:
    fields=["campaign.id", "campaign.name", "metrics.clicks"], resource="campaign",
    conditions=["campaign.status = 'ENABLED'", "segments.date DURING LAST_7_DAYS"].
    Use get_resource_metadata first if you are unsure which fields exist.
    """
    cid = clean_customer_id(customer_id)
    query = build_gaql(
        fields=fields,
        resource=resource,
        conditions=conditions or [],
        orderings=orderings or [],
        limit=limit,
    )
    rows = run_search(cid, query, login_customer_id=login_customer_id)
    return {"query": query, "row_count": len(rows), "rows": rows}


def get_resource_metadata(
    resource: str, limit: int = 200, login_customer_id: str | None = None
) -> dict[str, Any]:
    """Describe selectable fields for a Google Ads resource such as campaign or ad_group.

    Mirrors the official `get_resource_metadata` tool so an agent can discover
    valid GAQL fields before calling search.
    """
    client = get_client(login_customer_id)
    service = client.get_service("GoogleAdsFieldService")
    query = build_field_metadata_query(resource, limit=limit)
    # page_size caps results; FieldService rejects LIMIT in the query string.
    request = {
        "query": query,
        "page_size": int(limit),
    }
    response = run_ads_call(service.search_google_ads_fields, request=request)
    fields = []
    for field in response:
        fields.append(
            {
                "name": field.name,
                "category": field.category.name if field.category else None,
                "data_type": field.data_type.name if field.data_type else None,
                "selectable": field.selectable,
                "filterable": field.filterable,
                "sortable": field.sortable,
            }
        )
    return {"resource": resource, "field_count": len(fields), "fields": fields}


def register(mcp: FastMCP) -> None:
    mcp.tool(search)
    mcp.tool(get_resource_metadata)
