"""Shared mutate helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from google.api_core import protobuf_helpers

from google_ads_mcp.client import get_client, run_ads_call
from google_ads_mcp.ids import clean_customer_id


class TempIds:
    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        self._n -= 1
        return self._n


def apply_update_mask(client, operation, resource) -> None:
    client.copy_from(operation.update_mask, protobuf_helpers.field_mask(None, resource._pb))


def mutate(customer_id: str, operations: Iterable[Any], *, client=None) -> dict[str, Any]:
    ads_client = client or get_client()
    service = ads_client.get_service("GoogleAdsService")
    cid = clean_customer_id(customer_id)
    ops = list(operations)
    response = run_ads_call(service.mutate, customer_id=cid, mutate_operations=ops)
    results = []
    for result in response.mutate_operation_responses:
        resource_name = None
        for field in result._pb.DESCRIPTOR.fields:
            if result._pb.HasField(field.name):
                inner = getattr(result, field.name)
                resource_name = getattr(inner, "resource_name", None)
                if resource_name:
                    results.append({"type": field.name, "resource_name": resource_name})
                    break
    return {
        "results": results,
        "count": len(results),
    }


def status_enum(client, enum_name: str, status: str):
    enum = getattr(client.enums, enum_name)
    key = status.strip().upper()
    if not hasattr(enum, key):
        valid = [name for name in dir(enum) if name.isupper() and not name.startswith("_")]
        raise ValueError(f"Invalid status {status!r}. Expected one of: {', '.join(sorted(valid))}")
    return getattr(enum, key)
