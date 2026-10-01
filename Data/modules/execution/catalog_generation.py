"""Durable capability-catalog generation for custom wrappers + plugins.

MCP already persists per-server ``catalog_generation``. Custom capabilities and
declarative plugins need the same cross-process reconciliation so API and
execution workers project identical dynamic catalog state after CRUD / refresh.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCOPE_CUSTOM = "custom"
SCOPE_PLUGINS = "plugins"
SCOPE_GLOBAL = "global"

_VALID_SCOPES = frozenset({SCOPE_CUSTOM, SCOPE_PLUGINS, SCOPE_GLOBAL})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CatalogGenerationStore:
    """CONTROL-DB generation counters + optional content hashes for catalog scopes."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_catalog_generations (
                    scope TEXT PRIMARY KEY,
                    catalog_generation INTEGER NOT NULL DEFAULT 0,
                    content_hash TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            for scope in (SCOPE_CUSTOM, SCOPE_PLUGINS, SCOPE_GLOBAL):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO capability_catalog_generations(
                        scope, catalog_generation, content_hash, updated_at
                    ) VALUES (?, 0, NULL, ?)
                    """,
                    (scope, _utc_now()),
                )

    def get_generation(self, scope: str) -> int:
        scope = self._require_scope(scope)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT catalog_generation FROM capability_catalog_generations WHERE scope = ?",
                (scope,),
            ).fetchone()
        return int(row["catalog_generation"]) if row else 0

    def get_content_hash(self, scope: str) -> str | None:
        scope = self._require_scope(scope)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT content_hash FROM capability_catalog_generations WHERE scope = ?",
                (scope,),
            ).fetchone()
        if row is None:
            return None
        value = row["content_hash"]
        return str(value) if value else None

    def bump(
        self,
        scope: str,
        *,
        content_hash: str | None = None,
        bump_global: bool = True,
    ) -> int:
        scope = self._require_scope(scope)
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO capability_catalog_generations(scope, catalog_generation, content_hash, updated_at)
                VALUES (?, 0, NULL, ?)
                ON CONFLICT(scope) DO NOTHING
                """,
                (scope, now),
            )
            conn.execute(
                """
                UPDATE capability_catalog_generations
                SET catalog_generation = catalog_generation + 1,
                    content_hash = COALESCE(?, content_hash),
                    updated_at = ?
                WHERE scope = ?
                """,
                (content_hash, now, scope),
            )
            if bump_global and scope != SCOPE_GLOBAL:
                conn.execute(
                    """
                    INSERT INTO capability_catalog_generations(scope, catalog_generation, content_hash, updated_at)
                    VALUES (?, 0, NULL, ?)
                    ON CONFLICT(scope) DO NOTHING
                    """,
                    (SCOPE_GLOBAL, now),
                )
                conn.execute(
                    """
                    UPDATE capability_catalog_generations
                    SET catalog_generation = catalog_generation + 1, updated_at = ?
                    WHERE scope = ?
                    """,
                    (now, SCOPE_GLOBAL),
                )
            row = conn.execute(
                "SELECT catalog_generation FROM capability_catalog_generations WHERE scope = ?",
                (scope,),
            ).fetchone()
        return int(row["catalog_generation"]) if row else 0

    def snapshot(self) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT scope, catalog_generation, content_hash, updated_at "
                "FROM capability_catalog_generations ORDER BY scope"
            ).fetchall()
        return {
            "scopes": {
                str(row["scope"]): {
                    "catalog_generation": int(row["catalog_generation"] or 0),
                    "content_hash": row["content_hash"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            },
            "truth": {
                "generation_is_not_authorization": True,
                "process_local_catalog_is_not_source_of_truth": True,
            },
        }

    @staticmethod
    def hash_payload(payload: Any) -> str:
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _require_scope(scope: str) -> str:
        text = str(scope or "").strip().lower()
        if text not in _VALID_SCOPES:
            raise ValueError(f"Unknown catalog generation scope: {scope!r}")
        return text


class CatalogProjectionTracker:
    """Process-local projection watermark vs durable generations."""

    def __init__(self) -> None:
        self._projected: dict[str, int] = {}

    def mark(self, scope: str, generation: int) -> None:
        self._projected[str(scope)] = int(generation)

    def projected(self, scope: str) -> int:
        return int(self._projected.get(str(scope), -1))

    def is_stale(self, store: CatalogGenerationStore, scope: str) -> bool:
        return store.get_generation(scope) != self.projected(scope)

    def stale_scopes(self, store: CatalogGenerationStore) -> list[str]:
        return [
            scope
            for scope in (SCOPE_CUSTOM, SCOPE_PLUGINS)
            if self.is_stale(store, scope)
        ]
