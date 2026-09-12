"""GAQL query construction and row formatting."""

from __future__ import annotations

from typing import Any

import proto
from google.ads.googleads.util import get_nested_attr
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message as PbMessage

from google_ads_mcp.client import get_client, run_ads_call
from google_ads_mcp.ids import clean_customer_id


def build_gaql(
    *,
    fields: list[str],
    resource: str,
    conditions: list[str] | None = None,
    orderings: list[str] | None = None,
    limit: int | None = None,
) -> str:
    if not fields:
        raise ValueError("fields must not be empty")
    if not resource:
        raise ValueError("resource must not be empty")
    parts = [f"SELECT {', '.join(fields)} FROM {resource}"]
    if conditions:
        parts.append("WHERE " + " AND ".join(conditions))
    if orderings:
        parts.append("ORDER BY " + ", ".join(orderings))
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        parts.append(f"LIMIT {limit}")
    parts.append("PARAMETERS omit_unselected_resource_names=true")
    return " ".join(parts)


def format_output_value(value: Any) -> Any:
    if isinstance(value, proto.Enum):
        return value.name
    if isinstance(value, proto.Message):
        return proto.Message.to_dict(value)
    if isinstance(value, PbMessage):
        return MessageToDict(value, preserving_proto_field_name=True)
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
        return [format_output_value(item) for item in value]
    return value


def format_output_row(row: proto.Message, attributes: list[str]) -> dict[str, Any]:
    return {attr: format_output_value(get_nested_attr(row, attr)) for attr in attributes}


def search(
    customer_id: str,
    query: str,
    *,
    client=None,
) -> list[dict[str, Any]]:
    ads_client = client or get_client()
    service = ads_client.get_service("GoogleAdsService")
    cid = clean_customer_id(customer_id)
    stream = run_ads_call(service.search_stream, customer_id=cid, query=query)
    rows: list[dict[str, Any]] = []
    for batch in stream:
        paths = list(batch.field_mask.paths)
        for row in batch.results:
            rows.append(format_output_row(row, paths))
    return rows
