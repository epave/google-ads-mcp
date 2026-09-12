"""Image and text asset uploads for Display and Performance Max."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.request import urlopen

from fastmcp import FastMCP

from google_ads_mcp.client import get_client, run_ads_call
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.safety import SafetyGate
from google_ads_mcp.store import get_store


def _read_bytes(source: str) -> bytes:
    if source.startswith("http://") or source.startswith("https://"):
        with urlopen(source, timeout=30) as response:  # noqa: S310
            return response.read()
    path = Path(source).expanduser()
    if not path.is_file():
        raise ValueError(f"Image file not found: {source}")
    return path.read_bytes()


def upload_image_asset(
    customer_id: str,
    name: str,
    source: str,
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    """Upload an image asset from a local file path or HTTP(S) URL.

    Use the returned resource_name when creating Display or Performance Max
    campaigns. Landscape marketing images: 1.91:1, min 600x314. Square: 1:1,
    min 300x300. Logos can be 1:1 or 4:1.
    """
    cid = clean_customer_id(customer_id)
    auth = SafetyGate().authorize_write(
        tool="upload_image_asset",
        customer_id=cid,
        args={"name": name, "source": source},
        description=f"Upload image asset '{name}' from {source}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    data = _read_bytes(source)
    client = get_client()
    service = client.get_service("AssetService")
    operation = client.get_type("AssetOperation")
    asset = operation.create
    asset.name = name
    asset.type_ = client.enums.AssetTypeEnum.IMAGE
    asset.image_asset.data = data
    response = run_ads_call(service.mutate_assets, customer_id=cid, operations=[operation])
    resource_name = response.results[0].resource_name
    get_store().record_audit(
        tool="upload_image_asset",
        action="apply",
        customer_id=cid,
        payload={"name": name, "bytes": len(data), "resource_name": resource_name},
    )
    return {"status": "applied", "resource_name": resource_name, "bytes": len(data)}


def register(mcp: FastMCP) -> None:
    mcp.tool(upload_image_asset)
