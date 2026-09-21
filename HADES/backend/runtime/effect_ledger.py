"""At-least-once effect ledger for HADES side effects.

Exactly-once external effects are not claimed. This ledger records intent before
execution and outcome after, so restart/resume can classify:

- SAFE_TO_RETRY
- REQUIRES_RECONCILIATION
- ALREADY_COMMITTED
- UNKNOWN_EXTERNAL_STATE

Persists to a small SQLite file under the platform data root.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

EffectStatus = Literal["prepared", "committed", "failed", "unknown_outcome"]
ReconcileClass = Literal[
    "SAFE_TO_RETRY",
    "REQUIRES_RECONCILIATION",
    "ALREADY_COMMITTED",
    "UNKNOWN_EXTERNAL_STATE",
]

# Effect classes that are generally unsafe to blindly re-run after unknown_outcome.
IRREVERSIBLE_ISH = frozenset(
    {
        "network_post",
        "network_write",
        "email_send",
        "payment",
        "subprocess_mutating",
        "fs_delete",
        "fs_write",
        "plugin_side_effect",
    }
)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def args_hash(tool: str, arguments: dict[str, Any] | None) -> str:
    payload = {"tool": tool, "arguments": arguments or {}}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class EffectRecord:
    effect_id: str
    task_id: str | None
    run_id: str | None
    tool: str
    args_hash: str
    effect_class: str
    status: EffectStatus
    created_at: str
    updated_at: str
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "tool": self.tool,
            "args_hash": self.args_hash,
            "effect_class": self.effect_class,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "detail": self.detail,
        }


class EffectLedger:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS effect_intents (
                    effect_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    run_id TEXT,
                    tool TEXT NOT NULL,
                    args_hash TEXT NOT NULL,
                    effect_class TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    detail_json TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_effect_task ON effect_intents(task_id, created_at)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_effect_hash ON effect_intents(tool, args_hash, status)"
            )
            db.commit()

    def prepare(
        self,
        *,
        tool: str,
        arguments: dict[str, Any] | None = None,
        effect_class: str = "plugin_side_effect",
        task_id: str | None = None,
        run_id: str | None = None,
        detail: dict[str, Any] | None = None,
        effect_id: str | None = None,
    ) -> EffectRecord:
        eid = effect_id or f"eff_{uuid4().hex[:16]}"
        now = _utc()
        record = EffectRecord(
            effect_id=eid,
            task_id=task_id,
            run_id=run_id,
            tool=tool,
            args_hash=args_hash(tool, arguments),
            effect_class=effect_class,
            status="prepared",
            created_at=now,
            updated_at=now,
            detail=dict(detail or {}),
        )
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO effect_intents(
                    effect_id, task_id, run_id, tool, args_hash, effect_class,
                    status, created_at, updated_at, detail_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record.effect_id,
                    record.task_id,
                    record.run_id,
                    record.tool,
                    record.args_hash,
                    record.effect_class,
                    record.status,
                    record.created_at,
                    record.updated_at,
                    json.dumps(record.detail, ensure_ascii=False),
                ),
            )
            db.commit()
        return record

    def _set_status(self, effect_id: str, status: EffectStatus, detail: dict[str, Any] | None = None) -> EffectRecord:
        now = _utc()
        with self._connect() as db:
            row = db.execute("SELECT * FROM effect_intents WHERE effect_id=?", (effect_id,)).fetchone()
            if not row:
                raise KeyError(effect_id)
            merged = json.loads(row["detail_json"] or "{}")
            if detail:
                merged.update(detail)
            db.execute(
                "UPDATE effect_intents SET status=?, updated_at=?, detail_json=? WHERE effect_id=?",
                (status, now, json.dumps(merged, ensure_ascii=False), effect_id),
            )
            db.commit()
            row = db.execute("SELECT * FROM effect_intents WHERE effect_id=?", (effect_id,)).fetchone()
        return self._row(row)

    def mark_committed(self, effect_id: str, detail: dict[str, Any] | None = None) -> EffectRecord:
        return self._set_status(effect_id, "committed", detail)

    def mark_failed(self, effect_id: str, detail: dict[str, Any] | None = None) -> EffectRecord:
        return self._set_status(effect_id, "failed", detail)

    def mark_unknown(self, effect_id: str, detail: dict[str, Any] | None = None) -> EffectRecord:
        return self._set_status(effect_id, "unknown_outcome", detail)

    def get(self, effect_id: str) -> EffectRecord | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM effect_intents WHERE effect_id=?", (effect_id,)).fetchone()
        return self._row(row) if row else None

    def list_for_task(self, task_id: str) -> list[EffectRecord]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM effect_intents WHERE task_id=? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def classify_on_restart(self, effect_id: str) -> dict[str, Any]:
        record = self.get(effect_id)
        if not record:
            return {"effect_id": effect_id, "class": "SAFE_TO_RETRY", "reason": "missing_record"}
        if record.status == "committed":
            return {"effect_id": effect_id, "class": "ALREADY_COMMITTED", "reason": "committed", "record": record.to_dict()}
        if record.status == "failed":
            return self._classify_failed(record)
        if record.status == "prepared":
            # Never observed an outcome — usually safe if effect is idempotent; else reconcile.
            if record.effect_class in IRREVERSIBLE_ISH:
                return {
                    "effect_id": effect_id,
                    "class": "REQUIRES_RECONCILIATION",
                    "reason": "prepared_without_outcome_irreversible_ish",
                    "record": record.to_dict(),
                }
            return {"effect_id": effect_id, "class": "SAFE_TO_RETRY", "reason": "prepared_idempotent_class", "record": record.to_dict()}
        # unknown_outcome
        return {
            "effect_id": effect_id,
            "class": "UNKNOWN_EXTERNAL_STATE",
            "reason": "unknown_outcome",
            "record": record.to_dict(),
        }

    @staticmethod
    def _classify_failed(record: EffectRecord) -> dict[str, Any]:
        """Classify a failed effect using an explicit, contradiction-aware contract.

        Contract (failed status only):
        - Proven pre-execution failure (effect_applied is False, and/or a safe
          failure_stage with no conflicting applied=True) → SAFE_TO_RETRY.
        - Possible or partial external effect (effect_applied is True, or an
          unsafe/partial failure_stage) → REQUIRES_RECONCILIATION.
        - Contradictory metadata where one field claims an effect may have run
          while another names a pre-execution stage → REQUIRES_RECONCILIATION
          (never SAFE_TO_RETRY solely because of the early-stage field).
        - Contradictory metadata where effect_applied is False but the stage
          claims a post-execution/partial outcome → UNKNOWN_EXTERNAL_STATE.
        - Missing / incomplete metadata → UNKNOWN_EXTERNAL_STATE.
        """
        detail = record.detail or {}
        stage = str(detail.get("failure_stage") or "").strip().lower()
        effect_applied = detail.get("effect_applied")
        safe_stages = frozenset({"before_execute", "validation", "policy"})
        unsafe_stages = frozenset({"after_execute", "partial_effect", "commit_unknown"})
        stage_safe = stage in safe_stages
        stage_unsafe = stage in unsafe_stages

        # Explicit contradictions: never trust the "safe stage" alone when
        # another field says an effect may already have run.
        if effect_applied is True and stage_safe:
            return {
                "effect_id": record.effect_id,
                "class": "REQUIRES_RECONCILIATION",
                "reason": "contradictory_metadata_applied_vs_early_stage",
                "record": record.to_dict(),
            }
        if effect_applied is False and stage_unsafe:
            return {
                "effect_id": record.effect_id,
                "class": "UNKNOWN_EXTERNAL_STATE",
                "reason": "contradictory_metadata_not_applied_vs_late_stage",
                "record": record.to_dict(),
            }

        # Possible / partial effect always requires reconciliation.
        if effect_applied is True or stage_unsafe or stage == "partial_effect":
            return {
                "effect_id": record.effect_id,
                "class": "REQUIRES_RECONCILIATION",
                "reason": "failed_after_possible_effect",
                "record": record.to_dict(),
            }

        # Proven failure before any external effect.
        if effect_applied is False or stage_safe:
            return {
                "effect_id": record.effect_id,
                "class": "SAFE_TO_RETRY",
                "reason": "failed_before_effect",
                "record": record.to_dict(),
            }

        return {
            "effect_id": record.effect_id,
            "class": "UNKNOWN_EXTERNAL_STATE",
            "reason": "failed_unknown_effect_state",
            "record": record.to_dict(),
        }

    @staticmethod
    def _row(row: sqlite3.Row) -> EffectRecord:
        return EffectRecord(
            effect_id=row["effect_id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            tool=row["tool"],
            args_hash=row["args_hash"],
            effect_class=row["effect_class"],
            status=row["status"],  # type: ignore[arg-type]
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            detail=json.loads(row["detail_json"] or "{}"),
        )
