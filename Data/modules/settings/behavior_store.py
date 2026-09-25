"""BehaviorProfile persistence — uses existing behavior_profiles table.

Editable system prompt / identity / language / retrieval knobs are behavior, not authority.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .behavior import (
    DEFAULT_BEHAVIOR_PROFILE,
    BehaviorProfile,
    merge_behavior_patch,
    validate_behavior_patch,
)
from .seed import SEED_SYSTEM_PROMPT


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BehaviorProfileStore:
    """Load/save BehaviorProfile from the canonical metadata database."""

    DEFAULT_ID = DEFAULT_BEHAVIOR_PROFILE.id

    def __init__(self, database_path: Path) -> None:
        self.path = Path(database_path)
        self._listeners: list[Any] = []

    def on_change(self, callback: Any) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS behavior_profiles (
                    id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    system_prompt TEXT NOT NULL,
                    overlays_json TEXT NOT NULL DEFAULT '{}',
                    reasoning_mode_default TEXT NOT NULL DEFAULT 'standard',
                    tool_use_style TEXT NOT NULL DEFAULT 'balanced',
                    hash TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(behavior_profiles)").fetchall()}
            if "settings_json" not in cols:
                conn.execute(
                    "ALTER TABLE behavior_profiles ADD COLUMN settings_json TEXT NOT NULL DEFAULT '{}'"
                )

    def get(self, profile_id: str | None = None) -> BehaviorProfile:
        pid = profile_id or self.DEFAULT_ID
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM behavior_profiles WHERE id = ?",
                (pid,),
            ).fetchone()
        if row is None:
            return DEFAULT_BEHAVIOR_PROFILE
        return self._row_to_profile(row)

    def get_effective(self) -> BehaviorProfile:
        """Return stored default profile or built-in seed default."""
        return self.get(self.DEFAULT_ID)

    def fingerprint(self, profile_id: str | None = None) -> dict[str, str | None]:
        """Persisted revision identity for hot-apply / cross-process freshness.

        One SQLite read. Safe to call once per independent model operation.
        """
        profile = self.get(profile_id)
        hashed = profile if profile.hash else profile.with_hash()
        updated_at: str | None = None
        try:
            with self.connect() as conn:
                row = conn.execute(
                    "SELECT updated_at FROM behavior_profiles WHERE id = ?",
                    (hashed.id,),
                ).fetchone()
                if row:
                    updated_at = str(row["updated_at"])
        except Exception:  # noqa: BLE001
            updated_at = None
        return {
            "id": hashed.id,
            "version": str(hashed.version),
            "hash": hashed.hash,
            "updated_at": updated_at,
            "source": "behavior_store" if updated_at else "seed",
        }

    def save(self, profile: BehaviorProfile, *, updated_by: str = "operator") -> BehaviorProfile:
        hashed = profile.with_hash()
        overlays = {
            "project_prompt_overlays": list(hashed.project_prompt_overlays),
            "task_prompt_overlays": list(hashed.task_prompt_overlays),
        }
        metadata = dict(hashed.metadata)
        metadata["updated_by"] = updated_by
        settings = hashed.settings_blob()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO behavior_profiles (
                    id, version, system_prompt, overlays_json,
                    reasoning_mode_default, tool_use_style, hash,
                    metadata_json, settings_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    version=excluded.version,
                    system_prompt=excluded.system_prompt,
                    overlays_json=excluded.overlays_json,
                    reasoning_mode_default=excluded.reasoning_mode_default,
                    tool_use_style=excluded.tool_use_style,
                    hash=excluded.hash,
                    metadata_json=excluded.metadata_json,
                    settings_json=excluded.settings_json,
                    updated_at=excluded.updated_at
                """,
                (
                    hashed.id,
                    hashed.version,
                    hashed.system_prompt,
                    json.dumps(overlays, ensure_ascii=False),
                    hashed.reasoning_mode_default,
                    hashed.tool_use_style,
                    hashed.hash,
                    json.dumps(metadata, ensure_ascii=False),
                    json.dumps(settings, ensure_ascii=False),
                    utc_now(),
                ),
            )
        self._notify()
        return hashed

    def update_system_prompt(
        self,
        system_prompt: str,
        *,
        profile_id: str | None = None,
        updated_by: str = "operator",
    ) -> BehaviorProfile:
        current = self.get(profile_id)
        return self.patch({"system_prompt": system_prompt}, profile_id=profile_id, updated_by=updated_by)

    def patch(
        self,
        payload: dict[str, Any],
        *,
        profile_id: str | None = None,
        updated_by: str = "operator",
    ) -> BehaviorProfile:
        errors = validate_behavior_patch(payload)
        if errors:
            raise ValueError("; ".join(errors))
        current = self.get(profile_id)
        updated = merge_behavior_patch(current, payload)
        meta = dict(updated.metadata)
        meta["updated_by"] = updated_by
        updated = BehaviorProfile(**{**updated.__dict__, "metadata": meta, "hash": None}).with_hash()  # type: ignore[arg-type]
        return self.save(updated, updated_by=updated_by)

    def reset_to_default(self, *, profile_id: str | None = None) -> BehaviorProfile:
        pid = profile_id or self.DEFAULT_ID
        reset = BehaviorProfile(
            id=pid,
            version=DEFAULT_BEHAVIOR_PROFILE.version,
            system_prompt=SEED_SYSTEM_PROMPT,
            metadata={"reset": True},
        )
        # Copy all seed defaults from DEFAULT_BEHAVIOR_PROFILE
        fields = {k: v for k, v in DEFAULT_BEHAVIOR_PROFILE.__dict__.items() if k not in {"id", "hash", "metadata"}}
        reset = BehaviorProfile(id=pid, metadata={"reset": True}, **fields).with_hash()  # type: ignore[arg-type]
        return self.save(reset, updated_by="operator:reset")

    def public_effective(self, *, include_prompt: bool = True) -> dict[str, Any]:
        effective = self.get_effective()
        default = DEFAULT_BEHAVIOR_PROFILE
        payload = effective.public_dict(include_prompt=include_prompt)
        payload["default_system_prompt"] = default.system_prompt if include_prompt else None
        payload["is_default"] = effective.compute_hash() == default.compute_hash()
        payload["updated_at"] = None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT updated_at FROM behavior_profiles WHERE id = ?",
                (effective.id,),
            ).fetchone()
            if row:
                payload["updated_at"] = row["updated_at"]
        payload["truth"] = {
            **payload.get("truth", {}),
            "behavior_is_not_authority": True,
            "system_prompt_is_not_capability_grant": True,
            "does_not_bypass_execution_gateway": True,
            "does_not_bypass_approvals": True,
            "settings_are_sole_identity_authority": True,
        }
        return payload

    @staticmethod
    def _row_to_profile(row: sqlite3.Row) -> BehaviorProfile:
        try:
            overlays = json.loads(row["overlays_json"] or "{}")
        except json.JSONDecodeError:
            overlays = {}
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        try:
            keys = row.keys()
            settings_raw = row["settings_json"] if "settings_json" in keys else "{}"
            settings = json.loads(settings_raw or "{}")
        except (json.JSONDecodeError, IndexError, KeyError):
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        project = overlays.get("project_prompt_overlays") or []
        task = overlays.get("task_prompt_overlays") or []
        base = {
            "id": str(row["id"]),
            "version": str(row["version"]),
            "system_prompt": str(row["system_prompt"] or ""),
            "project_prompt_overlays": tuple(project) if isinstance(project, list) else (),
            "task_prompt_overlays": tuple(task) if isinstance(task, list) else (),
            "reasoning_mode_default": str(row["reasoning_mode_default"] or "standard"),
            "tool_use_style": str(row["tool_use_style"] or "balanced"),
            "metadata": metadata if isinstance(metadata, dict) else {},
            "hash": str(row["hash"]) if row["hash"] else None,
        }
        # Merge extended settings; ignore unknown keys
        known = {f.name for f in BehaviorProfile.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        for key, value in settings.items():
            if key in known and key not in {"id", "hash"}:
                if key in {
                    "aliases",
                    "stop_sequences",
                    "retrieval_dataset_scopes",
                    "project_prompt_overlays",
                    "task_prompt_overlays",
                }:
                    if isinstance(value, list):
                        base[key] = tuple(value)
                    elif value is None:
                        base[key] = ()
                    else:
                        base[key] = (value,)
                else:
                    base[key] = value
        return BehaviorProfile(**base).with_hash()  # type: ignore[arg-type]
