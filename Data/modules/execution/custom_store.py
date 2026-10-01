"""Leviathan-owned custom capability definitions (CONTROL SQLite).

Custom tools are declarative wrappers around existing catalog capabilities.
They hydrate into CapabilityCatalog and always execute through ExecutionGateway.
No separate tools database file. No arbitrary code execution.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from Data.modules.function_runtime.types import SideEffect

from .catalog import CapabilityCatalog
from .types import CapabilityDefinition, CapabilityProviderKind

_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,118}$")

# Metadata keys reserved for system provenance — clients cannot overwrite.
PROTECTED_CUSTOM_METADATA_KEYS = frozenset(
    {
        "origin",
        "wraps_capability_id",
        "delegates_to",
        "version",
        "revision",
        "capability_id",
        "created_at",
        "updated_at",
        "owner",
        "owned_by",
        "system_protected",
    }
)


def _sanitize_custom_metadata(
    incoming: dict[str, Any] | None,
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge metadata while refusing protected key overwrites from clients."""
    base = dict(existing or {})
    for key, value in dict(incoming or {}).items():
        key_s = str(key)
        if key_s in PROTECTED_CUSTOM_METADATA_KEYS:
            continue
        base[key_s] = value
    # Strip any protected keys that somehow landed in client payload copies.
    for protected in PROTECTED_CUSTOM_METADATA_KEYS:
        if protected in base and protected not in (existing or {}):
            # Allow system to set origin etc. via existing; drop fresh client injects.
            if protected not in {"origin"}:  # origin may be set by hydrate, not create path
                pass
    return base


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class CustomCapabilityRecord:
    capability_id: str
    name: str
    description: str
    wraps_capability_id: str
    version: str
    enabled: bool
    created_at: str
    updated_at: str
    metadata: dict[str, Any]
    revision: int = 1

    def public_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "wraps_capability_id": self.wraps_capability_id,
            "version": self.version,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "revision": self.revision,
            "origin": "custom",
            "truth": {
                "custom_is_wrapper_not_exec_backdoor": True,
                "execution_via_gateway": True,
            },
        }


class CustomCapabilityStore:
    """Persists Leviathan-owned custom capability wrappers in CONTROL DB."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_capability_definitions (
                    capability_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    wraps_capability_id TEXT NOT NULL,
                    version TEXT NOT NULL DEFAULT '1.0.0',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_custom_capabilities_wraps "
                "ON custom_capability_definitions(wraps_capability_id)"
            )

    def list(self) -> list[CustomCapabilityRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM custom_capability_definitions ORDER BY capability_id ASC"
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, capability_id: str) -> CustomCapabilityRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM custom_capability_definitions WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
        return self._row(row) if row else None

    def create(
        self,
        *,
        name: str,
        description: str,
        wraps_capability_id: str,
        capability_id: str | None = None,
        version: str = "1.0.0",
        metadata: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> CustomCapabilityRecord:
        now = _utc_now()
        cid = (capability_id or "").strip().lower() or f"custom.{uuid.uuid4().hex[:12]}"
        if not _ID_RE.match(cid):
            raise ValueError(
                "capability_id must match ^[a-z][a-z0-9_.-]{1,118}$"
            )
        if not wraps_capability_id.strip():
            raise ValueError("wraps_capability_id is required")
        clean_meta = _sanitize_custom_metadata(metadata)
        record = CustomCapabilityRecord(
            capability_id=cid,
            name=(name or cid).strip(),
            description=(description or "").strip(),
            wraps_capability_id=wraps_capability_id.strip(),
            version=(version or "1.0.0").strip(),
            enabled=bool(enabled),
            created_at=now,
            updated_at=now,
            metadata=clean_meta,
            revision=1,
        )
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT capability_id FROM custom_capability_definitions WHERE capability_id = ?",
                (record.capability_id,),
            ).fetchone()
            if existing:
                raise ValueError(f"Custom capability already exists: {record.capability_id}")
            conn.execute(
                """
                INSERT INTO custom_capability_definitions(
                    capability_id, name, description, wraps_capability_id, version,
                    enabled, created_at, updated_at, metadata_json, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.capability_id,
                    record.name,
                    record.description,
                    record.wraps_capability_id,
                    record.version,
                    1 if record.enabled else 0,
                    record.created_at,
                    record.updated_at,
                    json.dumps(record.metadata),
                    record.revision,
                ),
            )
        return record

    def update(
        self,
        capability_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        version: str | None = None,
        metadata: dict[str, Any] | None = None,
        expected_revision: int | None = None,
    ) -> CustomCapabilityRecord:
        current = self.get(capability_id)
        if current is None:
            raise KeyError(capability_id)
        if expected_revision is not None and current.revision != expected_revision:
            raise ValueError(
                f"Revision conflict: expected {expected_revision}, got {current.revision}"
            )
        next_meta = (
            _sanitize_custom_metadata(metadata, existing=current.metadata)
            if metadata is not None
            else dict(current.metadata)
        )
        updated = CustomCapabilityRecord(
            capability_id=current.capability_id,
            name=(name if name is not None else current.name).strip(),
            description=(description if description is not None else current.description),
            wraps_capability_id=current.wraps_capability_id,
            version=(version if version is not None else current.version).strip(),
            enabled=current.enabled if enabled is None else bool(enabled),
            created_at=current.created_at,
            updated_at=_utc_now(),
            metadata=next_meta,
            revision=current.revision + 1,
        )
        with self.connect() as conn:
            # Optimistic concurrency: atomic UPDATE WHERE revision=?
            fence_revision = (
                int(expected_revision) if expected_revision is not None else int(current.revision)
            )
            cur = conn.execute(
                """
                UPDATE custom_capability_definitions
                SET name = ?, description = ?, version = ?, enabled = ?,
                    updated_at = ?, metadata_json = ?, revision = ?
                WHERE capability_id = ? AND revision = ?
                """,
                (
                    updated.name,
                    updated.description,
                    updated.version,
                    1 if updated.enabled else 0,
                    updated.updated_at,
                    json.dumps(updated.metadata),
                    updated.revision,
                    updated.capability_id,
                    fence_revision,
                ),
            )
            if cur.rowcount != 1:
                raise ValueError(
                    f"Revision conflict: expected {fence_revision}, concurrent update detected"
                )
        return updated

    def delete(self, capability_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM custom_capability_definitions WHERE capability_id = ?",
                (capability_id,),
            )
            return cur.rowcount > 0

    def hydrate_into_catalog(self, catalog: CapabilityCatalog) -> int:
        """Register/upsert custom wrappers into CapabilityCatalog."""
        count = 0
        for record in self.list():
            target = catalog.get(record.wraps_capability_id)
            if target is None:
                # Target missing — register as unavailable custom stub.
                definition = CapabilityDefinition(
                    id=record.capability_id,
                    name=record.name,
                    description=record.description or f"Custom wrapper for {record.wraps_capability_id}",
                    side_effects=(SideEffect.READ,),
                    provider_kind=CapabilityProviderKind.INTERNAL,
                    provider_ref=record.wraps_capability_id,
                    input_schema={"type": "object", "properties": {}},
                    output_schema={"type": "object"},
                    available=False,
                    availability_reason=f"Wrapped capability unavailable: {record.wraps_capability_id}",
                    enabled=record.enabled,
                    metadata={
                        "origin": "custom",
                        "version": record.version,
                        "wraps_capability_id": record.wraps_capability_id,
                        "delegates_to": record.wraps_capability_id,
                        "domains": ["system"],
                        "tags": ["custom"],
                        **dict(record.metadata),
                    },
                )
            else:
                definition = CapabilityDefinition(
                    id=record.capability_id,
                    name=record.name,
                    description=record.description or target.description,
                    side_effects=target.side_effects,
                    provider_kind=target.provider_kind,
                    provider_ref=target.provider_ref,
                    input_schema=dict(target.input_schema),
                    output_schema=dict(target.output_schema),
                    required_permissions=target.required_permissions,
                    available=target.available and record.enabled,
                    availability_reason=(
                        None
                        if target.available and record.enabled
                        else (
                            "Custom tool disabled"
                            if not record.enabled
                            else target.availability_reason
                        )
                    ),
                    enabled=record.enabled and target.enabled,
                    metadata={
                        **dict(target.normalized_metadata()),
                        "origin": "custom",
                        "version": record.version,
                        "wraps_capability_id": record.wraps_capability_id,
                        "delegates_to": record.wraps_capability_id,
                        "tags": list(
                            dict.fromkeys([*(target.normalized_metadata().get("tags") or []), "custom"])
                        ),
                        **dict(record.metadata),
                    },
                )
            catalog.upsert(definition)
            count += 1
        return count

    @staticmethod
    def _row(row: sqlite3.Row) -> CustomCapabilityRecord:
        return CustomCapabilityRecord(
            capability_id=row["capability_id"],
            name=row["name"],
            description=row["description"] or "",
            wraps_capability_id=row["wraps_capability_id"],
            version=row["version"] or "1.0.0",
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            revision=int(row["revision"] or 1),
        )
