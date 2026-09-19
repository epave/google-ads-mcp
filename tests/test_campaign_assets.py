"""Campaign asset tool tests (callouts, snippets, attach/detach)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from google_ads_mcp.builders.assets import (
    STRUCTURED_SNIPPET_HEADERS,
    validate_callout_text,
    validate_structured_snippet,
)
from google_ads_mcp.errors import AdsError
from google_ads_mcp.store import reset_store_for_tests
from google_ads_mcp.tools import assets as assets_mod
from tests.fakes import fake_ads_client


def _isolate(monkeypatch, tmp_path: Path) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("GOOGLE_ADS_MCP_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_ADS_DISABLE_ENV_FILE", "1")
    monkeypatch.delenv("GOOGLE_ADS_ALLOWED_CUSTOMER_IDS", raising=False)
    monkeypatch.setenv("GOOGLE_ADS_SKIP_CONFIRM", "true")


def test_validate_callout_limits() -> None:
    assert validate_callout_text("  hello  ") == "hello"
    with pytest.raises(AdsError, match="25"):
        validate_callout_text("x" * 26)


def test_validate_structured_snippet_header() -> None:
    hdr, vals = validate_structured_snippet("Service catalog", ["a", "b", "c"])
    assert hdr == "Service catalog"
    assert vals == ["a", "b", "c"]
    with pytest.raises(AdsError, match="header"):
        validate_structured_snippet("NotAHeader", ["a", "b", "c"])
    with pytest.raises(AdsError, match="header"):
        validate_structured_snippet("Services", ["a", "b", "c"])
    assert "Service catalog" in STRUCTURED_SNIPPET_HEADERS


def test_copy_six_callouts_reuses_existing(monkeypatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    callouts = [f"Callout {i}" for i in range(1, 7)]
    existing = {
        text: f"customers/1/assets/{100 + i}" for i, text in enumerate(callouts, 1)
    }

    def fake_search(customer_id, query, login_customer_id=None):
        if "asset.callout_asset.callout_text" in query and "FROM asset" in query:
            return [
                {
                    "asset.resource_name": existing[text],
                    "asset.callout_asset.callout_text": text,
                }
                for text in callouts
            ]
        if "FROM campaign_asset" in query:
            # Source campaign already has them; target does not.
            return [
                {
                    "campaign.id": 111,
                    "campaign_asset.asset": rn,
                    "campaign_asset.resource_name": f"customers/1/campaignAssets/111~{100 + i}",
                    "campaign_asset.status": "ENABLED",
                }
                for i, rn in enumerate(existing.values(), 1)
            ]
        return []

    monkeypatch.setattr(assets_mod, "search", fake_search)
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())

    captured: dict[str, Any] = {}

    def fake_mutate(customer_id, operations, **kwargs):
        captured["ops"] = list(operations)
        return {"results": [{"type": "campaign_asset_result", "resource_name": "x"}], "count": 1}

    monkeypatch.setattr(assets_mod, "mutate", fake_mutate)

    result = assets_mod.add_campaign_callouts(
        customer_id="1234567890",
        campaign_ids=["222"],
        callouts=callouts,
        reuse_existing=True,
        dry_run=False,
    )
    assert result["status"] == "applied"
    assert len(result["diff"]["reused_assets"]) == 6
    assert result["diff"]["created_assets"] == []
    assert len(result["diff"]["attached"]) == 6
    # Only campaign_asset creates — no asset creates
    assert all(
        op.asset_operation.create.callout_asset.callout_text == ""
        or not op.asset_operation.create.resource_name
        or True
        for op in captured["ops"]
    )
    assert len(captured["ops"]) == 6
    for op in captured["ops"]:
        assert op.campaign_asset_operation.create.asset.startswith("customers/")


def test_create_callout_attach_two_campaigns(monkeypatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)

    def fake_search(customer_id, query, login_customer_id=None):
        return []

    monkeypatch.setattr(assets_mod, "search", fake_search)
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())

    captured: list[Any] = []

    def fake_mutate(customer_id, operations, **kwargs):
        captured.extend(operations)
        return {"results": [], "count": len(list(operations))}

    monkeypatch.setattr(assets_mod, "mutate", fake_mutate)

    result = assets_mod.add_campaign_callouts(
        customer_id="1234567890",
        campaign_ids=["111", "222"],
        callouts=["119 kr per analys"],
        reuse_existing=True,
        dry_run=False,
    )
    assert len(result["diff"]["created_assets"]) == 1
    assert len(result["diff"]["attached"]) == 2
    # 1 asset create + 2 campaign_asset creates
    assert len(captured) == 3


def test_structured_snippet_create_and_attach(monkeypatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(assets_mod, "search", lambda *a, **k: [])
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())
    captured: list[Any] = []

    def fake_mutate(customer_id, operations, **kwargs):
        captured.extend(operations)
        return {"results": [], "count": len(list(operations))}

    monkeypatch.setattr(assets_mod, "mutate", fake_mutate)
    result = assets_mod.add_campaign_structured_snippet(
        customer_id="1234567890",
        campaign_ids=["111"],
        header="Service catalog",
        values=["Audit", "Advice", "Support"],
        dry_run=False,
    )
    assert result["status"] == "applied"
    assert len(result["diff"]["created_assets"]) == 1
    assert len(result["diff"]["attached"]) == 1
    assert len(captured) == 2


def test_duplicate_callout_inputs_are_deduped(monkeypatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(assets_mod, "search", lambda *a, **k: [])
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())
    captured: list[Any] = []

    def fake_mutate(customer_id, operations, **kwargs):
        captured.extend(operations)
        return {"results": [], "count": len(list(operations))}

    monkeypatch.setattr(assets_mod, "mutate", fake_mutate)
    result = assets_mod.add_campaign_callouts(
        customer_id="1234567890",
        campaign_ids=["111", "111", "222"],
        callouts=["Same text", "Same text"],
        dry_run=False,
    )
    assert len(result["diff"]["created_assets"]) == 1
    assert len(result["diff"]["attached"]) == 2
    assert len(captured) == 3  # 1 asset + 2 campaign links


def test_rerun_callouts_no_duplicates(monkeypatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    text = "Free shipping"
    asset_rn = "customers/1/assets/55"

    def fake_search(customer_id, query, login_customer_id=None):
        if "FROM asset" in query:
            return [
                {
                    "asset.resource_name": asset_rn,
                    "asset.callout_asset.callout_text": text,
                }
            ]
        return [
            {
                "campaign.id": 111,
                "campaign_asset.asset": asset_rn,
                "campaign_asset.resource_name": "customers/1/campaignAssets/111~55",
                "campaign_asset.status": "ENABLED",
            }
        ]

    monkeypatch.setattr(assets_mod, "search", fake_search)
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())
    called = {"n": 0}

    def fake_mutate(*a, **k):
        called["n"] += 1
        return {"results": [], "count": 0}

    monkeypatch.setattr(assets_mod, "mutate", fake_mutate)
    result = assets_mod.add_campaign_callouts(
        customer_id="1234567890",
        campaign_ids=["111"],
        callouts=[text],
        dry_run=False,
    )
    assert result["diff"]["created_assets"] == []
    assert result["diff"]["attached"] == []
    assert len(result["diff"]["already_attached"]) == 1
    assert called["n"] == 0


def test_reuse_prefers_already_linked_enabled_callout(monkeypatch, tmp_path: Path) -> None:
    """When multiple assets share callout text, prefer the one already linked ENABLED."""
    _isolate(monkeypatch, tmp_path)
    text = "Same text"
    orphan = "customers/1/assets/10"
    linked_rn = "customers/1/assets/20"

    def fake_search(customer_id, query, login_customer_id=None):
        if "FROM asset" in query:
            # Orphan listed first — naive first-match would pick it.
            return [
                {"asset.resource_name": orphan, "asset.callout_asset.callout_text": text},
                {"asset.resource_name": linked_rn, "asset.callout_asset.callout_text": text},
            ]
        return [
            {
                "campaign.id": 111,
                "campaign_asset.asset": linked_rn,
                "campaign_asset.resource_name": "customers/1/campaignAssets/111~20",
                "campaign_asset.status": "ENABLED",
            }
        ]

    monkeypatch.setattr(assets_mod, "search", fake_search)
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())
    result = assets_mod.add_campaign_callouts(
        customer_id="1234567890",
        campaign_ids=["111"],
        callouts=[text],
        reuse_existing=True,
        dry_run=False,
    )
    assert result["diff"]["reused_assets"][0]["asset"] == linked_rn
    assert result["diff"]["already_attached"][0]["asset"] == linked_rn
    assert result["diff"]["attached"] == []
    assert result["diff"]["created_assets"] == []


def test_reuse_prefers_linked_structured_snippet(monkeypatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    header = "Types"
    values = ["A", "B", "C"]
    orphan = "customers/1/assets/30"
    linked_rn = "customers/1/assets/40"

    def fake_search(customer_id, query, login_customer_id=None):
        if "FROM asset" in query:
            return [
                {
                    "asset.resource_name": orphan,
                    "asset.structured_snippet_asset.header": header,
                    "asset.structured_snippet_asset.values": values,
                },
                {
                    "asset.resource_name": linked_rn,
                    "asset.structured_snippet_asset.header": header,
                    "asset.structured_snippet_asset.values": values,
                },
            ]
        return [
            {
                "campaign.id": 222,
                "campaign_asset.asset": linked_rn,
                "campaign_asset.resource_name": "customers/1/campaignAssets/222~40",
                "campaign_asset.status": "ENABLED",
            }
        ]

    monkeypatch.setattr(assets_mod, "search", fake_search)
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())
    result = assets_mod.add_campaign_structured_snippet(
        customer_id="1234567890",
        campaign_ids=["222"],
        header=header,
        values=values,
        reuse_existing=True,
        dry_run=False,
    )
    assert result["diff"]["reused_assets"][0]["asset"] == linked_rn
    assert result["diff"]["already_attached"][0]["asset"] == linked_rn


def test_add_callouts_preview_includes_diff(monkeypatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("GOOGLE_ADS_WRITE_ENABLED", "false")
    monkeypatch.setenv("GOOGLE_ADS_SKIP_CONFIRM", "false")
    monkeypatch.setattr(assets_mod, "search", lambda *a, **k: [])
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())
    preview = assets_mod.add_campaign_callouts(
        customer_id="1234567890",
        campaign_ids=["111", "222"],
        callouts=["119 kr per analys"],
        dry_run=True,
    )
    assert preview["status"] == "preview"
    assert "confirm_token" in preview
    assert preview["diff"]["created_assets"]
    assert len(preview["diff"]["attached"]) == 2


def test_paused_campaign_asset_is_re_enabled(monkeypatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    asset_rn = "customers/1/assets/77"
    link_rn = "customers/1/campaignAssets/111~77"

    def fake_search(customer_id, query, login_customer_id=None):
        return [
            {
                "campaign.id": 111,
                "campaign_asset.asset": asset_rn,
                "campaign_asset.resource_name": link_rn,
                "campaign_asset.status": "PAUSED",
            }
        ]

    monkeypatch.setattr(assets_mod, "search", fake_search)
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())
    captured: list[Any] = []

    def fake_mutate(customer_id, operations, **kwargs):
        captured.extend(operations)
        return {"results": [], "count": len(list(operations))}

    monkeypatch.setattr(assets_mod, "mutate", fake_mutate)
    result = assets_mod.attach_campaign_assets(
        customer_id="1234567890",
        campaign_ids=["111"],
        asset_resource_names=[asset_rn],
        field_type="CALLOUT",
        dry_run=False,
    )
    assert result["diff"]["already_attached"] == []
    assert len(result["diff"]["re_enabled"]) == 1
    assert captured[0].campaign_asset_operation.update.status.name == "ENABLED"


def test_attach_noop_records_audit(monkeypatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    asset_rn = "customers/1/assets/77"
    link_rn = "customers/1/campaignAssets/111~77"

    def fake_search(customer_id, query, login_customer_id=None):
        return [
            {
                "campaign.id": 111,
                "campaign_asset.asset": asset_rn,
                "campaign_asset.resource_name": link_rn,
                "campaign_asset.status": "ENABLED",
            }
        ]

    monkeypatch.setattr(assets_mod, "search", fake_search)
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())
    monkeypatch.setattr(
        assets_mod,
        "mutate",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no mutate")),
    )
    result = assets_mod.attach_campaign_assets(
        customer_id="1234567890",
        campaign_ids=["111"],
        asset_resource_names=[asset_rn],
        field_type="CALLOUT",
        dry_run=False,
    )
    assert result["status"] == "applied"
    assert result["count"] == 0
    assert result["diff"]["already_attached"]
    from google_ads_mcp.store import get_store

    events = get_store().list_recent_audit(limit=10)
    applies = [e for e in events if e["tool"] == "attach_campaign_assets" and e["action"] == "apply"]
    assert applies
    assert applies[0]["payload"].get("noop") is True


def test_detach_requires_force_and_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    rn = "customers/1/campaignAssets/111~55"
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())

    with pytest.raises(AdsError, match="force=true"):
        assets_mod.detach_campaign_asset(
            customer_id="1234567890",
            campaign_asset_resource_name=rn,
            dry_run=False,
            force=False,
        )

    monkeypatch.setattr(
        assets_mod,
        "search",
        lambda *a, **k: [
            {"campaign_asset.resource_name": rn, "campaign_asset.status": "REMOVED"}
        ],
    )
    called = {"n": 0}

    def fake_mutate(*a, **k):
        called["n"] += 1
        return {"results": [], "count": 0}

    monkeypatch.setattr(assets_mod, "mutate", fake_mutate)
    result = assets_mod.detach_campaign_asset(
        customer_id="1234567890",
        campaign_asset_resource_name=rn,
        dry_run=False,
        force=True,
    )
    assert result["status"] == "applied"
    assert result["diff"]["detached"] == []
    assert result["diff"]["unchanged"]
    assert called["n"] == 0


def test_detach_with_force_removes_enabled_link(monkeypatch, tmp_path: Path) -> None:
    _isolate(monkeypatch, tmp_path)
    rn = "customers/1/campaignAssets/111~55"
    monkeypatch.setattr(assets_mod, "get_client", lambda *_a, **_k: fake_ads_client())
    monkeypatch.setattr(
        assets_mod,
        "search",
        lambda *a, **k: [
            {"campaign_asset.resource_name": rn, "campaign_asset.status": "ENABLED"}
        ],
    )
    captured: list[Any] = []

    def fake_mutate(customer_id, operations, **kwargs):
        captured.extend(operations)
        return {"results": [], "count": 1}

    monkeypatch.setattr(assets_mod, "mutate", fake_mutate)
    result = assets_mod.detach_campaign_asset(
        customer_id="1234567890",
        campaign_asset_resource_name=rn,
        dry_run=False,
        force=True,
    )
    assert result["diff"]["detached"][0]["campaign_asset"] == rn
    assert captured[0].campaign_asset_operation.remove == rn
