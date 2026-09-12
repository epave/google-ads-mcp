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

logger = logging.getLogger(__name__)


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
    used_at TIMESTAMP
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self.path))
        self._init_schema()

    def _init_schema(self) -> None:
        version = duckdb.__version__
        logger.info("DuckDB Python %s at %s", version, self.path)
        self._conn.execute(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def _variant(self, value: Any) -> str:
        return json.dumps(value, default=str)

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
    ) -> str:
        token = uuid4().hex
        now = datetime.now(UTC).replace(tzinfo=None)
        self._conn.execute(
            """
            INSERT INTO preview_tokens
                (token, created_at, expires_at, tool, customer_id, args, description, used_at)
            VALUES (?, ?, ?, ?, ?, ?::JSON::VARIANT, ?, NULL)
            """,
            [
                token,
                now,
                now + timedelta(seconds=ttl_seconds),
                tool,
                customer_id,
                self._variant(args),
                description,
            ],
        )
        return token

    def _decode_args(self, args: Any) -> dict[str, Any]:
        if isinstance(args, str):
            return json.loads(args)
        if hasattr(args, "as_py"):
            return args.as_py()
        return dict(args) if args else {}

    def consume_preview(
        self,
        token: str,
        *,
        tool: str,
        customer_id: str | None,
        expected_args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT tool, customer_id, args, expires_at, used_at
            FROM preview_tokens
            WHERE token = ?
            """,
            [token],
        ).fetchone()
        if row is None:
            raise ValueError("Unknown confirm_token. Call the tool with dry_run=true first.")
        stored_tool, stored_customer, args, expires_at, used_at = row
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
        self._conn.execute(
            "UPDATE preview_tokens SET used_at = ? WHERE token = ?",
            [datetime.now(UTC).replace(tzinfo=None), token],
        )
        return stored_args

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
        payload = row[0]
        if isinstance(payload, str):
            return json.loads(payload)
        if hasattr(payload, "as_py"):
            return payload.as_py()
        return dict(payload)

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
            payload = row[5]
            if isinstance(payload, str):
                payload = json.loads(payload)
            elif hasattr(payload, "as_py"):
                payload = payload.as_py()
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
