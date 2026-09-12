"""Customer and resource name helpers."""

from __future__ import annotations

import re


def clean_customer_id(customer_id: str | int) -> str:
    """Strip dashes and other non-digits from a Google Ads customer ID."""
    cleaned = re.sub(r"\D", "", str(customer_id))
    if not cleaned:
        raise ValueError("customer_id must contain digits")
    return cleaned


def resource_id(resource_name: str) -> str:
    """Return the last path segment of a resource name."""
    return resource_name.rstrip("/").rsplit("/", 1)[-1]
