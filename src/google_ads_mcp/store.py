"""Local DuckDB 2.0 store for audit events, preview tokens, and dashboard snapshots.

DuckDB 2.0 is still alpha. Payloads use the new VARIANT type so agents can query
structured JSON without a separate JSON extension step.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb

from google_ads_mcp.config import mkdir_private

logger = logging.getLogger(__name__)

# Sentinel: leave preview_tokens.observed_state unchanged on refresh.
OBSERVED_UNSET: object = object()


def canonical_args(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    tool VARCHAR NOT NULL,
    customer_id VARCHAR,
    action VARCHAR NOT NULL,
    payload VARIANT,
    request_id VARCHAR
);

CREATE TABLE IF NOT EXISTS preview_tokens (
    token VARCHAR PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    tool VARCHAR NOT NULL,
    customer_id VARCHAR,
    args VARIANT,
    description VARCHAR,
    used_at TIMESTAMP,
    observed_state VARIANT
);

CREATE TABLE IF NOT EXISTS dashboard_snapshots (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    customer_id VARCHAR NOT NULL,
    payload VARIANT
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        mkdir_private(self.path.parent)
        self._conn = duckdb.connect(str(self.path))
        if self.path.exists():
            self.path.chmod(0o600)
        self._init_schema()

    def _init_schema(self) -> None:
        version = duckdb.__version__
        logger.info("DuckDB Python %s at %s", version, self.path)
        self._conn.execute(_SCHEMA)
        self._ensure_observed_state_column()

    def _ensure_observed_state_column(self) -> None:
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info('preview_tokens')").fetchall()
        }
        if "observed_state" not in cols:
            self._conn.execute("ALTER TABLE preview_tokens ADD COLUMN observed_state VARIANT")

    def close(self) -> None:
        self._conn.close()

    def _variant(self, value: Any) -> str:
        return json.dumps(value, default=str)

    def _decode_variant(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        if hasattr(value, "as_py"):
            return value.as_py()
        if isinstance(value, dict):
            return value
        return value

    def record_audit(
        self,
        *,
        tool: str,
        action: str,
        customer_id: str | None = None,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> str:
        event_id = str(uuid4())
        self._conn.execute(
            """
            INSERT INTO audit_events (id, created_at, tool, customer_id, action, payload, request_id)
            VALUES (?, ?, ?, ?, ?, ?::JSON::VARIANT, ?)
            """,
            [
                event_id,
                datetime.now(UTC).replace(tzinfo=None),
                tool,
                customer_id,
                action,
                self._variant(payload or {}),
                request_id,
            ],
        )
        return event_id

    def create_preview(
        self,
        *,
        tool: str,
        customer_id: str | None,
        args: dict[str, Any],
        description: str,
        ttl_seconds: int,
        observed_state: dict[str, Any] | None = None,
    ) -> tuple[str, datetime]:
        token = uuid4().hex
        now = datetime.now(UTC).replace(tzinfo=None)
        expires_at = now + timedelta(seconds=ttl_seconds)
        self._conn.execute(
            """
            INSERT INTO preview_tokens
                (token, created_at, expires_at, tool, customer_id, args, description,
                 used_at, observed_state)
            VALUES (?, ?, ?, ?, ?, ?::JSON::VARIANT, ?, NULL, ?::JSON::VARIANT)
            """,
            [
                token,
                now,
                expires_at,
                tool,
                customer_id,
                self._variant(args),
                description,
                self._variant(observed_state) if observed_state is not None else None,
            ],
        )
        return token, expires_at

    def _decode_args(self, args: Any) -> dict[str, Any]:
        decoded = self._decode_variant(args)
        return dict(decoded) if decoded else {}

    def peek_preview(
        self,
        token: str,
        *,
        tool: str,
        customer_id: str | None,
        expected_args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate a token without consuming it."""
        row = self._conn.execute(
            """
            SELECT tool, customer_id, args, expires_at, used_at, observed_state, description
            FROM preview_tokens
            WHERE token = ?
            """,
            [token],
        ).fetchone()
        if row is None:
            raise ValueError("Unknown confirm_token. Call the tool with dry_run=true first.")
        stored_tool, stored_customer, args, expires_at, used_at, observed_state, description = row
        if used_at is not None:
            raise ValueError("confirm_token has already been used.")
        if expires_at < datetime.now(UTC).replace(tzinfo=None):
            raise ValueError("confirm_token expired. Preview the mutation again.")
        if stored_tool != tool:
            raise ValueError(f"confirm_token was issued for {stored_tool}, not {tool}.")
        if stored_customer and customer_id and stored_customer != customer_id:
            raise ValueError("confirm_token customer_id does not match.")
        stored_args = self._decode_args(args)
        if expected_args is not None and canonical_args(stored_args) != canonical_args(expected_args):
            raise ValueError(
                "confirm_token does not match these arguments. Preview the mutation again "
                "with the exact payload you want to apply."
            )
        return {
            "tool": stored_tool,
            "customer_id": stored_customer,
            "args": stored_args,
            "expires_at": expires_at,
            "observed_state": self._decode_variant(observed_state),
            "description": description,
        }

    def refresh_preview(
        self,
        token: str,
        *,
        ttl_seconds: int,
        observed_state: dict[str, Any] | None | object = OBSERVED_UNSET,
    ) -> dict[str, Any]:
        """Extend expiry and optionally refresh observed_state for an unused token.

        ``OBSERVED_UNSET`` (default) leaves the stored snapshot alone.
        ``None`` clears it (SQL NULL). A dict replaces it.
        """
        row = self._conn.execute(
            """
            SELECT tool, customer_id, args, expires_at, used_at, description, observed_state
            FROM preview_tokens WHERE token = ?
            """,
            [token],
        ).fetchone()
        if row is None:
            raise ValueError("Unknown confirm_token.")
        tool, customer_id, args, expires_at, used_at, description, stored_observed = row
        if used_at is not None:
            raise ValueError("confirm_token has already been used.")
        now = datetime.now(UTC).replace(tzinfo=None)
        if expires_at < now:
            raise ValueError(
                "confirm_token expired. Preview the mutation again; "
                "refresh_preview cannot revive an expired token."
            )
        new_expires = now + timedelta(seconds=ttl_seconds)
        if observed_state is OBSERVED_UNSET:
            self._conn.execute(
                """
                UPDATE preview_tokens SET expires_at = ?
                WHERE token = ? AND used_at IS NULL
                """,
                [new_expires, token],
            )
            result_observed = self._decode_variant(stored_observed)
        else:
            self._conn.execute(
                """
                UPDATE preview_tokens
                SET expires_at = ?, observed_state = ?::JSON::VARIANT
                WHERE token = ? AND used_at IS NULL
                """,
                [
                    new_expires,
                    self._variant(observed_state) if observed_state is not None else None,
                    token,
                ],
            )
            result_observed = observed_state
        return {
            "confirm_token": token,
            "tool": tool,
            "customer_id": customer_id,
            "args": self._decode_args(args),
            "description": description,
            "expires_at": new_expires,
            "expires_in_seconds": ttl_seconds,
            "observed_state": result_observed,
        }

    def consume_preview(
        self,
        token: str,
        *,
        tool: str,
        customer_id: str | None,
        expected_args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        peeked = self.peek_preview(
            token, tool=tool, customer_id=customer_id, expected_args=expected_args
        )
        claimed = self._conn.execute(
            """
            UPDATE preview_tokens
            SET used_at = ?
            WHERE token = ? AND used_at IS NULL
            RETURNING token
            """,
            [datetime.now(UTC).replace(tzinfo=None), token],
        ).fetchone()
        if claimed is None:
            raise ValueError("confirm_token has already been used.")
        return peeked["args"]

    def save_dashboard_snapshot(self, customer_id: str, payload: dict[str, Any]) -> str:
        snapshot_id = str(uuid4())
        self._conn.execute(
            """
            INSERT INTO dashboard_snapshots (id, created_at, customer_id, payload)
            VALUES (?, ?, ?, ?::JSON::VARIANT)
            """,
            [
                snapshot_id,
                datetime.now(UTC).replace(tzinfo=None),
                customer_id,
                self._variant(payload),
            ],
        )
        return snapshot_id

    def previous_dashboard_snapshot(self, customer_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT payload
            FROM dashboard_snapshots
            WHERE customer_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [customer_id],
        ).fetchone()
        if row is None:
            return None
        return self._decode_variant(row[0])

    def list_recent_audit(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, created_at, tool, customer_id, action, payload, request_id
            FROM audit_events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        events = []
        for row in rows:
            payload = self._decode_variant(row[5])
            events.append(
                {
                    "id": row[0],
                    "created_at": row[1].isoformat() if row[1] else None,
                    "tool": row[2],
                    "customer_id": row[3],
                    "action": row[4],
                    "payload": payload,
                    "request_id": row[6],
                }
            )
        return events


_STORE: Store | None = None


def get_store(path: Path | None = None) -> Store:
    global _STORE
    if _STORE is None:
        if path is None:
            from google_ads_mcp.config import load_settings

            path = load_settings().resolved_db_path()
        _STORE = Store(path)
    return _STORE


def reset_store_for_tests() -> None:
    global _STORE
    if _STORE is not None:
        _STORE.close()
        _STORE = None
