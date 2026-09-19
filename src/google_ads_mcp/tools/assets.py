"""Image uploads and campaign-level callout / structured-snippet assets."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastmcp import FastMCP

from google_ads_mcp.builders.assets import (
    STRUCTURED_SNIPPET_HEADERS,
    build_campaign_asset_create,
    build_campaign_asset_remove,
    empty_asset_diff,
    set_asset_temp_resource_name,
    validate_callout_text,
    validate_structured_snippet,
)
from google_ads_mcp.client import get_client
from google_ads_mcp.config import load_settings
from google_ads_mcp.errors import AdsError
from google_ads_mcp.gaql import search
from google_ads_mcp.ids import clean_customer_id, resource_id
from google_ads_mcp.mutate import TempIds, mutate
from google_ads_mcp.safety import SafetyGate, with_login_arg
from google_ads_mcp.store import get_store

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
BLOCKED_NAMES = {"google-ads.yaml", ".env", "id_rsa", "id_ed25519"}


def _gate() -> SafetyGate:
    return SafetyGate()


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
    args = with_login_arg({"name": name, "source": source}, login_customer_id)
    auth = _gate().authorize_write(
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
    from google_ads_mcp.client import run_ads_call

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


def list_campaign_assets(
    customer_id: str,
    campaign_id: str | None = None,
    field_types: list[str] | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """List campaign-level assets (callouts, structured snippets, sitelinks, …)."""
    cid = clean_customer_id(customer_id)
    conditions = ["campaign_asset.status != 'REMOVED'"]
    if campaign_id is not None:
        conditions.append(f"campaign.id = {int(str(campaign_id).replace('-', ''))}")
    if field_types:
        quoted = ", ".join(f"'{ft.strip().upper()}'" for ft in field_types)
        conditions.append(f"campaign_asset.field_type IN ({quoted})")
    rows = search(
        cid,
        "SELECT campaign.id, campaign.name, campaign_asset.resource_name, "
        "campaign_asset.asset, campaign_asset.field_type, campaign_asset.status, "
        "asset.id, asset.name, asset.type, asset.callout_asset.callout_text, "
        "asset.structured_snippet_asset.header, asset.structured_snippet_asset.values, "
        "asset.sitelink_asset.link_text, asset.policy_summary.approval_status, "
        "asset.policy_summary.review_status "
        "FROM campaign_asset WHERE "
        + " AND ".join(conditions)
        + " ORDER BY campaign.id, campaign_asset.field_type",
        login_customer_id=login_customer_id,
    )
    return {"count": len(rows), "assets": rows}


def get_asset_review_status(
    customer_id: str,
    asset_ids: list[str] | None = None,
    campaign_id: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Return policy / review status for assets (read-only; does not mutate)."""
    cid = clean_customer_id(customer_id)
    if asset_ids:
        ids = ", ".join(str(int(str(a).replace("-", ""))) for a in asset_ids)
        rows = search(
            cid,
            "SELECT asset.id, asset.name, asset.type, asset.resource_name, "
            "asset.policy_summary.approval_status, asset.policy_summary.review_status "
            f"FROM asset WHERE asset.id IN ({ids})",
            login_customer_id=login_customer_id,
        )
    else:
        listed = list_campaign_assets(
            cid, campaign_id=campaign_id, login_customer_id=login_customer_id
        )
        rows = [
            {
                "asset.id": row.get("asset.id"),
                "asset.name": row.get("asset.name"),
                "asset.type": row.get("asset.type"),
                "asset.resource_name": row.get("campaign_asset.asset"),
                "asset.policy_summary.approval_status": row.get(
                    "asset.policy_summary.approval_status"
                ),
                "asset.policy_summary.review_status": row.get(
                    "asset.policy_summary.review_status"
                ),
                "campaign.id": row.get("campaign.id"),
                "campaign_asset.field_type": row.get("campaign_asset.field_type"),
            }
            for row in listed["assets"]
        ]
    return {"count": len(rows), "assets": rows}


def _existing_callouts(
    customer_id: str, texts: list[str], login_customer_id: str | None
) -> dict[str, str]:
    """Map callout_text -> asset resource_name for matching existing assets."""
    if not texts:
        return {}
    escaped = ", ".join("'" + t.replace("'", "\\'") + "'" for t in texts)
    rows = search(
        customer_id,
        "SELECT asset.resource_name, asset.callout_asset.callout_text "
        f"FROM asset WHERE asset.type = 'CALLOUT' "
        f"AND asset.callout_asset.callout_text IN ({escaped})",
        login_customer_id=login_customer_id,
    )
    mapping: dict[str, str] = {}
    for row in rows:
        text = row.get("asset.callout_asset.callout_text")
        rn = row.get("asset.resource_name")
        if text and rn and text not in mapping:
            mapping[str(text)] = str(rn)
    return mapping


def _existing_snippets(
    customer_id: str,
    header: str,
    values: list[str],
    login_customer_id: str | None,
) -> str | None:
    rows = search(
        customer_id,
        "SELECT asset.resource_name, asset.structured_snippet_asset.header, "
        "asset.structured_snippet_asset.values FROM asset "
        "WHERE asset.type = 'STRUCTURED_SNIPPET' "
        f"AND asset.structured_snippet_asset.header = '{header.replace(chr(39), chr(92)+chr(39))}'",
        login_customer_id=login_customer_id,
    )
    wanted = tuple(values)
    for row in rows:
        existing = tuple(row.get("asset.structured_snippet_asset.values") or [])
        if existing == wanted:
            return str(row["asset.resource_name"])
    return None


def _campaign_links(
    customer_id: str,
    campaign_ids: list[str],
    field_type: str,
    login_customer_id: str | None,
) -> set[tuple[str, str]]:
    """Set of (campaign_id, asset_resource_name) already linked."""
    if not campaign_ids:
        return set()
    ids = ", ".join(str(int(str(c).replace("-", ""))) for c in campaign_ids)
    rows = search(
        customer_id,
        "SELECT campaign.id, campaign_asset.asset FROM campaign_asset "
        f"WHERE campaign.id IN ({ids}) AND campaign_asset.field_type = '{field_type}' "
        "AND campaign_asset.status != 'REMOVED'",
        login_customer_id=login_customer_id,
    )
    linked: set[tuple[str, str]] = set()
    for row in rows:
        linked.add((str(row["campaign.id"]), str(row["campaign_asset.asset"])))
    return linked


def _plan_callouts(
    customer_id: str,
    campaign_ids: list[str],
    callouts: list[str],
    *,
    reuse_existing: bool,
    login_customer_id: str | None,
) -> tuple[dict[str, Any], list[Any] | None]:
    texts = [validate_callout_text(t) for t in callouts]
    if not texts:
        raise AdsError("callouts must not be empty")
    camp_ids = [str(int(str(c).replace("-", ""))) for c in campaign_ids]
    if not camp_ids:
        raise AdsError("campaign_ids must not be empty")

    existing = (
        _existing_callouts(customer_id, texts, login_customer_id) if reuse_existing else {}
    )
    linked = _campaign_links(customer_id, camp_ids, "CALLOUT", login_customer_id)
    diff = empty_asset_diff()
    # Resolve each text to an asset resource (existing or to-create temp key).
    text_to_asset: dict[str, str] = {}
    to_create: list[str] = []
    for text in texts:
        if text in existing:
            text_to_asset[text] = existing[text]
            diff["reused_assets"].append({"type": "CALLOUT", "text": text, "asset": existing[text]})
        else:
            to_create.append(text)

    # Build mutate ops only on apply; for preview we still describe the plan.
    client = get_client(login_customer_id)
    temps = TempIds()
    operations: list[Any] = []
    for text in to_create:
        temp_id = temps.next()
        op = client.get_type("MutateOperation")
        asset = op.asset_operation.create
        asset.type_ = client.enums.AssetTypeEnum.CALLOUT
        asset.callout_asset.callout_text = text
        rn = set_asset_temp_resource_name(client, op, customer_id, temp_id)
        operations.append(op)
        text_to_asset[text] = rn
        diff["created_assets"].append({"type": "CALLOUT", "text": text, "temp_asset": rn})

    for text in texts:
        asset_rn = text_to_asset[text]
        for camp in camp_ids:
            # Newly created temps use temp resource names; existing links use real names.
            if (camp, asset_rn) in linked or (
                text in existing and (camp, existing[text]) in linked
            ):
                diff["already_attached"].append(
                    {"campaign_id": camp, "asset": existing.get(text, asset_rn), "text": text}
                )
                continue
            operations.append(
                build_campaign_asset_create(
                    client,
                    customer_id=customer_id,
                    campaign_id=camp,
                    asset_resource_name=asset_rn,
                    field_type="CALLOUT",
                )
            )
            diff["attached"].append({"campaign_id": camp, "asset": asset_rn, "text": text})

    if not operations:
        for text in texts:
            for camp in camp_ids:
                diff["unchanged"].append({"campaign_id": camp, "text": text})

    return diff, operations


def add_campaign_callouts(
    customer_id: str,
    campaign_ids: list[str],
    callouts: list[str],
    reuse_existing: bool = True,
    dry_run: bool = True,
    confirm_token: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Create or reuse callout assets and attach them to one or more campaigns.

    Idempotent: re-running the same request does not create duplicate assets or links.
    Defaults to dry_run; re-call with confirm_token to apply. Multi-campaign attaches
    are one atomic GoogleAdsService.mutate.
    """
    cid = clean_customer_id(customer_id)
    cleaned_callouts = [validate_callout_text(t) for t in callouts]
    cleaned_campaigns = [str(int(str(c).replace("-", ""))) for c in campaign_ids]
    args = with_login_arg(
        {
            "campaign_ids": cleaned_campaigns,
            "callouts": cleaned_callouts,
            "reuse_existing": reuse_existing,
        },
        login_customer_id,
    )
    diff, operations = _plan_callouts(
        cid,
        cleaned_campaigns,
        cleaned_callouts,
        reuse_existing=reuse_existing,
        login_customer_id=login_customer_id,
    )
    description = (
        f"Add {len(cleaned_callouts)} callout(s) to {len(cleaned_campaigns)} campaign(s)"
    )
    auth = _gate().authorize_write(
        tool="add_campaign_callouts",
        customer_id=cid,
        args=args,
        description=description,
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return {**auth, "diff": diff}
    if not operations:
        get_store().record_audit(
            tool="add_campaign_callouts",
            action="apply",
            customer_id=cid,
            payload={"diff": diff, "noop": True},
        )
        return {"status": "applied", "diff": diff, "count": 0, "results": []}
    result = mutate(cid, operations, login_customer_id=login_customer_id)
    get_store().record_audit(
        tool="add_campaign_callouts",
        action="apply",
        customer_id=cid,
        payload={"diff": diff, **result},
    )
    return {"status": "applied", "diff": diff, **result}


def add_campaign_structured_snippet(
    customer_id: str,
    campaign_ids: list[str],
    header: str,
    values: list[str],
    reuse_existing: bool = True,
    dry_run: bool = True,
    confirm_token: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Create or reuse a structured snippet and attach it to campaigns atomically."""
    cid = clean_customer_id(customer_id)
    hdr, vals = validate_structured_snippet(header, values)
    cleaned_campaigns = [str(int(str(c).replace("-", ""))) for c in campaign_ids]
    if not cleaned_campaigns:
        raise AdsError("campaign_ids must not be empty")
    args = with_login_arg(
        {
            "campaign_ids": cleaned_campaigns,
            "header": hdr,
            "values": vals,
            "reuse_existing": reuse_existing,
        },
        login_customer_id,
    )
    existing_rn = (
        _existing_snippets(cid, hdr, vals, login_customer_id) if reuse_existing else None
    )
    linked = _campaign_links(cid, cleaned_campaigns, "STRUCTURED_SNIPPET", login_customer_id)
    diff = empty_asset_diff()
    client = get_client(login_customer_id)
    operations: list[Any] = []
    temps = TempIds()
    if existing_rn:
        asset_rn = existing_rn
        diff["reused_assets"].append(
            {"type": "STRUCTURED_SNIPPET", "header": hdr, "values": vals, "asset": asset_rn}
        )
    else:
        temp_id = temps.next()
        op = client.get_type("MutateOperation")
        asset = op.asset_operation.create
        asset.type_ = client.enums.AssetTypeEnum.STRUCTURED_SNIPPET
        asset.structured_snippet_asset.header = hdr
        asset.structured_snippet_asset.values.extend(vals)
        asset_rn = set_asset_temp_resource_name(client, op, cid, temp_id)
        operations.append(op)
        diff["created_assets"].append(
            {"type": "STRUCTURED_SNIPPET", "header": hdr, "values": vals, "temp_asset": asset_rn}
        )

    for camp in cleaned_campaigns:
        if (camp, asset_rn) in linked or (existing_rn and (camp, existing_rn) in linked):
            diff["already_attached"].append(
                {"campaign_id": camp, "asset": existing_rn or asset_rn, "header": hdr}
            )
            continue
        operations.append(
            build_campaign_asset_create(
                client,
                customer_id=cid,
                campaign_id=camp,
                asset_resource_name=asset_rn,
                field_type="STRUCTURED_SNIPPET",
            )
        )
        diff["attached"].append({"campaign_id": camp, "asset": asset_rn, "header": hdr})

    if not operations:
        for camp in cleaned_campaigns:
            diff["unchanged"].append({"campaign_id": camp, "header": hdr})

    description = f"Add structured snippet '{hdr}' to {len(cleaned_campaigns)} campaign(s)"
    auth = _gate().authorize_write(
        tool="add_campaign_structured_snippet",
        customer_id=cid,
        args=args,
        description=description,
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return {**auth, "diff": diff}
    if not operations:
        get_store().record_audit(
            tool="add_campaign_structured_snippet",
            action="apply",
            customer_id=cid,
            payload={"diff": diff, "noop": True},
        )
        return {"status": "applied", "diff": diff, "count": 0, "results": []}
    result = mutate(cid, operations, login_customer_id=login_customer_id)
    get_store().record_audit(
        tool="add_campaign_structured_snippet",
        action="apply",
        customer_id=cid,
        payload={"diff": diff, **result},
    )
    return {"status": "applied", "diff": diff, **result}


def attach_campaign_assets(
    customer_id: str,
    campaign_ids: list[str],
    asset_resource_names: list[str],
    field_type: str,
    dry_run: bool = True,
    confirm_token: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Attach existing assets to campaigns. Skips links that already exist."""
    cid = clean_customer_id(customer_id)
    ft = field_type.strip().upper()
    if not hasattr(get_client(login_customer_id).enums.AssetFieldTypeEnum, ft):
        raise AdsError(f"Unknown asset field_type {field_type!r}")
    cleaned_campaigns = [str(int(str(c).replace("-", ""))) for c in campaign_ids]
    assets = [str(a) for a in asset_resource_names]
    if not cleaned_campaigns or not assets:
        raise AdsError("campaign_ids and asset_resource_names must not be empty")
    args = with_login_arg(
        {
            "campaign_ids": cleaned_campaigns,
            "asset_resource_names": assets,
            "field_type": ft,
        },
        login_customer_id,
    )
    linked = _campaign_links(cid, cleaned_campaigns, ft, login_customer_id)
    diff = empty_asset_diff()
    client = get_client(login_customer_id)
    operations: list[Any] = []
    for camp in cleaned_campaigns:
        for asset_rn in assets:
            if (camp, asset_rn) in linked:
                diff["already_attached"].append(
                    {"campaign_id": camp, "asset": asset_rn, "field_type": ft}
                )
                continue
            operations.append(
                build_campaign_asset_create(
                    client,
                    customer_id=cid,
                    campaign_id=camp,
                    asset_resource_name=asset_rn,
                    field_type=ft,
                )
            )
            diff["attached"].append(
                {"campaign_id": camp, "asset": asset_rn, "field_type": ft}
            )
    auth = _gate().authorize_write(
        tool="attach_campaign_assets",
        customer_id=cid,
        args=args,
        description=f"Attach {len(assets)} asset(s) as {ft} to {len(cleaned_campaigns)} campaign(s)",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return {**auth, "diff": diff}
    if not operations:
        return {"status": "applied", "diff": diff, "count": 0, "results": []}
    result = mutate(cid, operations, login_customer_id=login_customer_id)
    get_store().record_audit(
        tool="attach_campaign_assets",
        action="apply",
        customer_id=cid,
        payload={"diff": diff, **result},
    )
    return {"status": "applied", "diff": diff, **result}


def detach_campaign_asset(
    customer_id: str,
    campaign_asset_resource_name: str,
    dry_run: bool = True,
    confirm_token: str | None = None,
    login_customer_id: str | None = None,
) -> dict[str, Any]:
    """Detach an asset from a campaign (reversible). Does not delete the asset globally."""
    cid = clean_customer_id(customer_id)
    rn = campaign_asset_resource_name.strip()
    if "/campaignAssets/" not in rn:
        raise AdsError(
            "campaign_asset_resource_name must be a campaign_asset resource "
            "(customers/.../campaignAssets/...)."
        )
    args = with_login_arg({"campaign_asset_resource_name": rn}, login_customer_id)
    diff = empty_asset_diff()
    diff["detached"].append({"campaign_asset": rn})
    client = get_client(login_customer_id)
    operations = [build_campaign_asset_remove(client, resource_name=rn)]
    auth = _gate().authorize_write(
        tool="detach_campaign_asset",
        customer_id=cid,
        args=args,
        description=f"Detach campaign asset {resource_id(rn)}",
        dry_run=dry_run,
        confirm_token=confirm_token,
    )
    if auth.get("status") == "preview":
        return {**auth, "diff": diff}
    result = mutate(cid, operations, login_customer_id=login_customer_id)
    get_store().record_audit(
        tool="detach_campaign_asset",
        action="apply",
        customer_id=cid,
        payload={"diff": diff, **result},
    )
    return {"status": "applied", "diff": diff, **result}


def register(mcp: FastMCP) -> None:
    mcp.tool(upload_image_asset)
    mcp.tool(list_campaign_assets)
    mcp.tool(add_campaign_callouts)
    mcp.tool(add_campaign_structured_snippet)
    mcp.tool(attach_campaign_assets)
    mcp.tool(detach_campaign_asset)
    mcp.tool(get_asset_review_status)


# Re-export for docs/tests
__all__ = [
    "STRUCTURED_SNIPPET_HEADERS",
    "add_campaign_callouts",
    "add_campaign_structured_snippet",
    "attach_campaign_assets",
    "detach_campaign_asset",
    "get_asset_review_status",
    "list_campaign_assets",
    "read_asset_bytes",
    "register",
    "upload_image_asset",
]
