"""BehaviorProfile persistence — uses existing behavior_profiles table.

Editable system prompt is behavior, not authority.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .behavior import DEFAULT_BEHAVIOR_PROFILE, BehaviorProfile


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BehaviorProfileStore:
    """Load/save BehaviorProfile from the canonical metadata database."""

    DEFAULT_ID = DEFAULT_BEHAVIOR_PROFILE.id

    def __init__(self, database_path: Path) -> None:
        self.path = Path(database_path)

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
        """Return stored default profile or built-in default."""
        profile = self.get(self.DEFAULT_ID)
        return profile

    def save(self, profile: BehaviorProfile, *, updated_by: str = "operator") -> BehaviorProfile:
        hashed = profile.with_hash()
        overlays = {
            "project_prompt_overlays": list(hashed.project_prompt_overlays),
            "task_prompt_overlays": list(hashed.task_prompt_overlays),
        }
        metadata = dict(hashed.metadata)
        metadata["updated_by"] = updated_by
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO behavior_profiles (
                    id, version, system_prompt, overlays_json,
                    reasoning_mode_default, tool_use_style, hash,
                    metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    version=excluded.version,
                    system_prompt=excluded.system_prompt,
                    overlays_json=excluded.overlays_json,
                    reasoning_mode_default=excluded.reasoning_mode_default,
                    tool_use_style=excluded.tool_use_style,
                    hash=excluded.hash,
                    metadata_json=excluded.metadata_json,
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
                    utc_now(),
                ),
            )
        return hashed

    def update_system_prompt(
        self,
        system_prompt: str,
        *,
        profile_id: str | None = None,
        updated_by: str = "operator",
    ) -> BehaviorProfile:
        current = self.get(profile_id)
        # Bump version lightly for history honesty without a separate table.
        try:
            ver_i = int(current.version)
            version = str(ver_i + 1)
        except ValueError:
            version = f"{current.version}.1"
        updated = BehaviorProfile(
            id=current.id if profile_id is None else (profile_id or current.id),
            version=version,
            system_prompt=system_prompt,
            project_prompt_overlays=current.project_prompt_overlays,
            task_prompt_overlays=current.task_prompt_overlays,
            reasoning_mode_default=current.reasoning_mode_default,
            tool_use_style=current.tool_use_style,
            metadata={**dict(current.metadata), "updated_by": updated_by},
        )
        return self.save(updated, updated_by=updated_by)

    def reset_to_default(self, *, profile_id: str | None = None) -> BehaviorProfile:
        pid = profile_id or self.DEFAULT_ID
        reset = BehaviorProfile(
            id=pid,
            version=DEFAULT_BEHAVIOR_PROFILE.version,
            system_prompt=DEFAULT_BEHAVIOR_PROFILE.system_prompt,
            project_prompt_overlays=DEFAULT_BEHAVIOR_PROFILE.project_prompt_overlays,
            task_prompt_overlays=DEFAULT_BEHAVIOR_PROFILE.task_prompt_overlays,
            reasoning_mode_default=DEFAULT_BEHAVIOR_PROFILE.reasoning_mode_default,
            tool_use_style=DEFAULT_BEHAVIOR_PROFILE.tool_use_style,
            metadata={"reset": True},
        )
        return self.save(reset, updated_by="operator:reset")

    def public_effective(self, *, include_prompt: bool = True) -> dict[str, Any]:
        effective = self.get_effective()
        default = DEFAULT_BEHAVIOR_PROFILE
        payload = effective.public_dict(include_prompt=include_prompt)
        payload["default_system_prompt"] = default.system_prompt if include_prompt else None
        payload["is_default"] = effective.compute_hash() == default.compute_hash()
        payload["truth"] = {
            **payload.get("truth", {}),
            "behavior_is_not_authority": True,
            "system_prompt_is_not_capability_grant": True,
            "does_not_bypass_execution_gateway": True,
            "does_not_bypass_approvals": True,
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
        project = overlays.get("project_prompt_overlays") or []
        task = overlays.get("task_prompt_overlays") or []
        return BehaviorProfile(
            id=str(row["id"]),
            version=str(row["version"]),
            system_prompt=str(row["system_prompt"] or ""),
            project_prompt_overlays=tuple(project) if isinstance(project, list) else (),
            task_prompt_overlays=tuple(task) if isinstance(task, list) else (),
            reasoning_mode_default=str(row["reasoning_mode_default"] or "standard"),
            tool_use_style=str(row["tool_use_style"] or "balanced"),
            metadata=metadata if isinstance(metadata, dict) else {},
            hash=str(row["hash"]) if row["hash"] else None,
        ).with_hash()
