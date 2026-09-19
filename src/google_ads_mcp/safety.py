"""Write-safety: allowlists, confirmation tokens, budget caps."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from google_ads_mcp.config import Settings, load_settings
from google_ads_mcp.errors import AdsError
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.store import OBSERVED_UNSET, Store, get_store

logger = logging.getLogger(__name__)

CREATE_STATUSES = frozenset({"ENABLED", "PAUSED"})


def _token_fingerprint(token: str) -> str:
    """Non-reusable digest for audit logs — never store the live confirm_token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def normalize_status(status: str) -> str:
    return status.strip().upper()


def require_force_for_removed(status: str, force: bool) -> str:
    """Reject REMOVED unless the caller opted in with force=true."""
    key = normalize_status(status)
    if key == "REMOVED" and not force:
        raise AdsError(
            "REMOVED permanently deletes the entity. Pass force=true if this is intentional."
        )
    return key


def normalize_create_status(status: str) -> str:
    key = normalize_status(status)
    if key not in CREATE_STATUSES:
        raise AdsError(f"Create status must be PAUSED or ENABLED, not {status!r}.")
    return key


def with_login_arg(args: dict[str, Any], login_customer_id: str | None) -> dict[str, Any]:
    if login_customer_id is None:
        return args
    return {**args, "login_customer_id": login_customer_id}


def _iso_expires(expires_at: datetime) -> str:
    if expires_at.tzinfo is None:
        return expires_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z")


class SafetyGate:
    def __init__(self, settings: Settings | None = None, store: Store | None = None):
        self.settings = settings or load_settings()
        self.store = store or get_store(self.settings.resolved_db_path())

    def assert_customer_allowed(self, customer_id: str) -> str:
        cid = clean_customer_id(customer_id)
        allowlist = self.settings.allowlist()
        if allowlist is not None and cid not in allowlist:
            raise AdsError(
                f"Customer {cid} is not in GOOGLE_ADS_ALLOWED_CUSTOMER_IDS."
            )
        return cid

    def assert_writes_enabled(self) -> None:
        if not self.settings.write_enabled:
            raise AdsError(
                "Writes are disabled. Set GOOGLE_ADS_WRITE_ENABLED=true after reviewing "
                "the preview. New campaigns are created PAUSED."
            )

    def authorize_write(
        self,
        *,
        tool: str,
        customer_id: str,
        args: dict[str, Any],
        description: str,
        dry_run: bool = True,
        confirm_token: str | None = None,
        observed_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cid = self.assert_customer_allowed(customer_id)
        if confirm_token and dry_run:
            raise AdsError(
                "confirm_token applies a write. Re-call with the same arguments, "
                "dry_run=false, and the confirm_token."
            )
        if dry_run:
            token, expires_at = self.store.create_preview(
                tool=tool,
                customer_id=cid,
                args=args,
                description=description,
                ttl_seconds=self.settings.preview_ttl_seconds,
                observed_state=observed_state,
            )
            self.store.record_audit(
                tool=tool,
                action="preview",
                customer_id=cid,
                payload={
                    "description": description,
                    "args": args,
                    "planned": args,
                    "observed_state": observed_state,
                },
            )
            return {
                "status": "preview",
                "dry_run": True,
                "confirm_token": token,
                "expires_in_seconds": self.settings.preview_ttl_seconds,
                "expires_at": _iso_expires(expires_at),
                "description": description,
                "args": args,
                "observed_state": observed_state,
                "next_step": (
                    f"Re-call {tool} with the same arguments, dry_run=false, and confirm_token."
                ),
            }

        self.assert_writes_enabled()
        if self.settings.skip_confirm:
            logger.warning(
                "GOOGLE_ADS_SKIP_CONFIRM is on: applying %s without a confirm token",
                tool,
            )
        if not self.settings.skip_confirm:
            if not confirm_token:
                raise AdsError(
                    "Missing confirm_token. Call again with dry_run=true, then pass "
                    "the returned confirm_token with dry_run=false."
                )
            try:
                self.store.consume_preview(
                    confirm_token,
                    tool=tool,
                    customer_id=cid,
                    expected_args=args,
                )
            except ValueError as exc:
                raise AdsError(str(exc)) from exc
        return {"status": "authorized", "customer_id": cid}

    def peek_write(
        self,
        *,
        tool: str,
        customer_id: str,
        args: dict[str, Any],
        confirm_token: str,
    ) -> dict[str, Any]:
        """Validate confirm_token without consuming it (for drift checks)."""
        cid = self.assert_customer_allowed(customer_id)
        try:
            return self.store.peek_preview(
                confirm_token,
                tool=tool,
                customer_id=cid,
                expected_args=args,
            )
        except ValueError as exc:
            raise AdsError(str(exc)) from exc

    def refresh_preview(
        self,
        confirm_token: str,
        observed_state: dict[str, Any] | None | object = OBSERVED_UNSET,
    ) -> dict[str, Any]:
        """Extend an unused preview token's TTL and optionally refresh observed_state.

        Pass ``observed_state=None`` to clear a prior snapshot; omit the argument
        (or pass ``OBSERVED_UNSET``) to leave the stored snapshot unchanged.
        """
        try:
            refreshed = self.store.refresh_preview(
                confirm_token,
                ttl_seconds=self.settings.preview_ttl_seconds,
                observed_state=observed_state,
            )
        except ValueError as exc:
            raise AdsError(str(exc)) from exc
        audit_observed = (
            None if observed_state is OBSERVED_UNSET else observed_state  # type: ignore[assignment]
        )
        self.store.record_audit(
            tool=refreshed["tool"],
            action="refresh_preview",
            customer_id=refreshed.get("customer_id"),
            payload={
                # Never persist the live token — audit is readable via get_local_audit.
                "confirm_token_fingerprint": _token_fingerprint(confirm_token),
                "observed_state": audit_observed,
            },
        )
        return {
            "status": "refreshed",
            "confirm_token": refreshed["confirm_token"],
            "expires_at": _iso_expires(refreshed["expires_at"]),
            "expires_in_seconds": refreshed["expires_in_seconds"],
            "tool": refreshed["tool"],
            "customer_id": refreshed.get("customer_id"),
            "args": refreshed["args"],
            "description": refreshed.get("description"),
            "observed_state": refreshed.get("observed_state"),
        }

    def assert_budget_increase_ok(self, current_amount: float, new_amount: float, force: bool) -> None:
        if force or new_amount <= current_amount or current_amount <= 0:
            return
        increase = (new_amount - current_amount) / current_amount
        cap = self.settings.budget_increase_cap
        if increase > cap:
            raise AdsError(
                f"Budget increase {increase:.0%} exceeds GOOGLE_ADS_BUDGET_INCREASE_CAP "
                f"({cap:.0%}). Pass force=true if this is intentional."
            )
