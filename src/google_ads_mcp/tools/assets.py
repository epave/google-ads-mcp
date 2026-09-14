"""Image and text asset uploads for Display and Performance Max."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastmcp import FastMCP

from google_ads_mcp.client import get_client, run_ads_call
from google_ads_mcp.config import load_settings
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.safety import SafetyGate
from google_ads_mcp.store import get_store

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
BLOCKED_NAMES = {"google-ads.yaml", ".env", "id_rsa", "id_ed25519"}


def _is_public_ip(ip: str) -> bool:
    address = ipaddress.ip_address(ip)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _resolved_public_ip(host: str, port: int) -> str:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for info in infos:
        ip = info[4][0]
        if _is_public_ip(ip):
            return ip
    raise ValueError(f"Refusing to fetch non-public host {host}")


def _assert_public_https(url: str) -> tuple[str, str, int, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Only https URLs are allowed for image assets")
    host = parsed.hostname
    if not host:
        raise ValueError("Invalid image URL")
    port = parsed.port or 443
    ip = _resolved_public_ip(host, port)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return host, ip, port, path


def _read_https(url: str) -> bytes:
    host, ip, port, path = _assert_public_https(url)
    context = ssl.create_default_context()
    raw = socket.create_connection((ip, port), timeout=30)
    ssock = context.wrap_socket(raw, server_hostname=host)
    connection = http.client.HTTPSConnection(host, port=port, timeout=30, context=context)
    connection.sock = ssock
    try:
        connection.request("GET", path, headers={"Host": host})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ValueError("Redirects are not allowed when fetching image assets")
        if response.status != 200:
            raise ValueError(f"Image URL returned HTTP {response.status}")
        data = response.read(MAX_IMAGE_BYTES + 1)
    finally:
        connection.close()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES} bytes")
    return data


def _read_local(source: str) -> bytes:
    root = load_settings().resolved_asset_root()
    path = Path(source).expanduser().resolve()
    if path.name in BLOCKED_NAMES:
        raise ValueError(f"Refusing to read credential-like file {path.name}")
    if not path.is_relative_to(root):
        raise ValueError(f"Image path must be under {root}")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"Unsupported image type {path.suffix}. Use png/jpg/gif/webp.")
    if not path.is_file():
        raise ValueError(f"Image file not found: {source}")
    data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES} bytes")
    return data


def read_asset_bytes(source: str) -> bytes:
    if source.startswith("http://") or source.startswith("https://"):
        return _read_https(source)
    return _read_local(source)


def upload_image_asset(
    customer_id: str,
    name: str,
    source: str,
    dry_run: bool = True,
    confirm_token: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Upload an image asset from a local file path or HTTPS URL.

    Local paths must stay under GOOGLE_ADS_ASSET_ROOT (cwd by default).
    HTTPS URLs must resolve to a public IP; redirects are rejected.
    """
    cid = clean_customer_id(customer_id)
    args = {"name": name, "source": source}
    auth = SafetyGate().authorize_write(
        tool="upload_image_asset",
        customer_id=cid,
        args=args,
        description=f"Upload image asset '{name}' from {source}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return auth
    data = read_asset_bytes(source)
    client = get_client(login_customer_id)
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
