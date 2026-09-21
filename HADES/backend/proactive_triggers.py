"""Opt-in proactive help with explicit bounds — never silent autonomy expansion.

Default: compact suggestion or prepared proposal.
External mutations only when existing authorization covers that concrete action.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Literal

from database import new_id, utc_now

TriggerKind = Literal[
    "source_changed",
    "dependency_available",
    "long_task_resumable",
    "deadline_approaching",
    "result_recheck",
]

TRIGGER_KINDS = frozenset(
    {
        "source_changed",
        "dependency_available",
        "long_task_resumable",
        "deadline_approaching",
        "result_recheck",
    }
)


def event_fingerprint(kind: str, scope: str, payload: dict[str, Any] | None = None) -> str:
    material = {"kind": kind, "scope": scope, "payload": payload or {}}
    raw = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class ProactiveTriggerService:
    """Store opt-in triggers, dedupe identical events, pause/disable cleanly."""

    def __init__(self, db: Any) -> None:
        self.db = db
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return self.db.connection()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS proactive_triggers (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT '',
                    permission TEXT NOT NULL DEFAULT 'suggest',
                    frequency_seconds INTEGER NOT NULL DEFAULT 3600,
                    resource_budget_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    paused INTEGER NOT NULL DEFAULT 0,
                    project_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS proactive_suggestions (
                    id TEXT PRIMARY KEY,
                    trigger_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    action_kind TEXT NOT NULL DEFAULT 'suggest',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    UNIQUE(trigger_id, fingerprint)
                );

                CREATE INDEX IF NOT EXISTS idx_proactive_suggestions_status
                    ON proactive_suggestions(status, created_at);
                """
            )

    def register_trigger(
        self,
        *,
        kind: str,
        title: str,
        scope: str = "",
        permission: str = "suggest",
        frequency_seconds: int = 3600,
        resource_budget: dict[str, Any] | None = None,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        kind = str(kind or "").strip()
        if kind not in TRIGGER_KINDS:
            raise ValueError(f"Unknown trigger kind: {kind}")
        permission = str(permission or "suggest").strip()
        if permission not in {"suggest", "prepare", "mutate_if_authorized"}:
            raise ValueError(f"Unknown permission: {permission}")
        now = utc_now()
        item = {
            "id": new_id("ptrig"),
            "kind": kind,
            "title": (title or kind).strip()[:200],
            "scope": (scope or "").strip()[:500],
            "permission": permission,
            "frequency_seconds": max(60, int(frequency_seconds or 3600)),
            "resource_budget_json": json.dumps(resource_budget or {}, ensure_ascii=False),
            "enabled": 1 if enabled else 0,
            "paused": 0,
            "project_id": project_id,
            "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO proactive_triggers(
                    id, kind, title, scope, permission, frequency_seconds, resource_budget_json,
                    enabled, paused, project_id, metadata_json, created_at, updated_at
                ) VALUES (
                    :id, :kind, :title, :scope, :permission, :frequency_seconds, :resource_budget_json,
                    :enabled, :paused, :project_id, :metadata_json, :created_at, :updated_at
                )""",
                item,
            )
        return self.get_trigger(item["id"]) or item

    def get_trigger(self, trigger_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proactive_triggers WHERE id=?", (trigger_id,)).fetchone()
        return self._trigger_row(row) if row else None

    def list_triggers(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM proactive_triggers"
        if enabled_only:
            sql += " WHERE enabled=1 AND paused=0"
        sql += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [self._trigger_row(r) for r in rows]

    def set_enabled(self, trigger_id: str, enabled: bool) -> dict[str, Any]:
        current = self.get_trigger(trigger_id)
        if not current:
            raise KeyError(trigger_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE proactive_triggers SET enabled=?, updated_at=? WHERE id=?",
                (1 if enabled else 0, utc_now(), trigger_id),
            )
        return self.get_trigger(trigger_id) or current

    def set_paused(self, trigger_id: str, paused: bool) -> dict[str, Any]:
        current = self.get_trigger(trigger_id)
        if not current:
            raise KeyError(trigger_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE proactive_triggers SET paused=?, updated_at=? WHERE id=?",
                (1 if paused else 0, utc_now(), trigger_id),
            )
        return self.get_trigger(trigger_id) or current

    def consider_event(
        self,
        trigger_id: str,
        *,
        reason: str,
        payload: dict[str, Any] | None = None,
        authorize_mutate: bool = False,
    ) -> dict[str, Any]:
        """Emit at most one open suggestion per identical fingerprint.

        Read-only watchers never write externally unless permission + authorize_mutate.
        """
        trigger = self.get_trigger(trigger_id)
        if not trigger:
            raise KeyError(trigger_id)
        if not trigger.get("enabled") or trigger.get("paused"):
            return {
                "emitted": False,
                "reason": "trigger_disabled_or_paused",
                "action_kind": "none",
            }
        fingerprint = event_fingerprint(trigger["kind"], trigger.get("scope") or "", payload)
        permission = trigger.get("permission") or "suggest"
        action_kind = "suggest"
        if permission == "prepare":
            action_kind = "prepare"
        elif permission == "mutate_if_authorized":
            action_kind = "mutate" if authorize_mutate else "suggest"
        # Hard bound: source watchers default to suggest/prepare unless explicitly authorized.
        if trigger["kind"] == "source_changed" and action_kind == "mutate" and not authorize_mutate:
            action_kind = "suggest"

        suggestion = {
            "id": new_id("psug"),
            "trigger_id": trigger_id,
            "fingerprint": fingerprint,
            "reason": (reason or "").strip()[:1000] or trigger["title"],
            "action_kind": action_kind,
            "payload_json": json.dumps(payload or {}, ensure_ascii=False),
            "status": "open",
            "created_at": utc_now(),
        }
        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO proactive_suggestions(
                        id, trigger_id, fingerprint, reason, action_kind, payload_json, status, created_at
                    ) VALUES (
                        :id, :trigger_id, :fingerprint, :reason, :action_kind, :payload_json, :status, :created_at
                    )""",
                    suggestion,
                )
                emitted = True
                duplicate = False
            except sqlite3.IntegrityError:
                emitted = False
                duplicate = True
                row = conn.execute(
                    """SELECT * FROM proactive_suggestions
                       WHERE trigger_id=? AND fingerprint=?""",
                    (trigger_id, fingerprint),
                ).fetchone()
                suggestion = self._suggestion_row(row) if row else suggestion
        return {
            "emitted": emitted,
            "duplicate": duplicate,
            "action_kind": action_kind,
            "suggestion": suggestion if isinstance(suggestion, dict) and "payload" in suggestion else self._suggestion_public(suggestion),
            "would_mutate": action_kind == "mutate",
        }

    def list_suggestions(self, *, status: str | None = "open", limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT * FROM proactive_suggestions"
        params: list[Any] = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 200)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._suggestion_row(r) for r in rows]

    def dismiss_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE proactive_suggestions SET status='dismissed' WHERE id=?",
                (suggestion_id,),
            )
            row = conn.execute("SELECT * FROM proactive_suggestions WHERE id=?", (suggestion_id,)).fetchone()
        if not row:
            raise KeyError(suggestion_id)
        return self._suggestion_row(row)

    @staticmethod
    def _trigger_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        item["paused"] = bool(item.get("paused"))
        try:
            item["resource_budget"] = json.loads(item.pop("resource_budget_json", "{}") or "{}")
        except Exception:
            item["resource_budget"] = {}
        try:
            item["metadata"] = json.loads(item.pop("metadata_json", "{}") or "{}")
        except Exception:
            item["metadata"] = {}
        return item

    @staticmethod
    def _suggestion_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json", "{}") or "{}")
        except Exception:
            item["payload"] = {}
        return item

    @classmethod
    def _suggestion_public(cls, raw: dict[str, Any]) -> dict[str, Any]:
        if "payload" in raw and "payload_json" not in raw:
            return raw
        return cls._suggestion_row(raw)
