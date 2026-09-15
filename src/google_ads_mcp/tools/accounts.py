"""Account discovery tools."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from google_ads_mcp.client import get_client, run_ads_call
from google_ads_mcp.errors import AdsError
from google_ads_mcp.gaql import search
from google_ads_mcp.ids import resource_id


def list_accessible_customers(login_customer_id: str | None = None) -> list[dict[str, Any]]:
    """List Google Ads accounts the authenticated user can access.

    Returns customer IDs and, when queryable, descriptive names. Use a returned
    customer_id on every later tool call. If you access accounts through a
    manager (MCC), pass login_customer_id or set GOOGLE_ADS_LOGIN_CUSTOMER_ID.
    Pass login_customer_id="none" to omit a cached MCC header.
    """
    client = get_client(login_customer_id)
    service = client.get_service("CustomerService")
    response = run_ads_call(service.list_accessible_customers)
    customers: list[dict[str, Any]] = []
    for resource_name in response.resource_names:
        cid = resource_id(resource_name)
        entry: dict[str, Any] = {
            "customer_id": cid,
            "resource_name": resource_name,
        }
        try:
            rows = search(
                cid,
                "SELECT customer.id, customer.descriptive_name, customer.currency_code, "
                "customer.time_zone, customer.manager FROM customer LIMIT 1",
                login_customer_id=login_customer_id,
            )
            if rows:
                entry.update(rows[0])
        except AdsError as exc:
            entry["name_error"] = str(exc)
        customers.append(entry)
    return customers


def register(mcp: FastMCP) -> None:
    mcp.tool(list_accessible_customers)
