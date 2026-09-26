from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import EffectRecord, ToolObservation


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ObservationStore:
    """Durable ToolObservations + Effect ledger in SQLite."""

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
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_observations (
                observation_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                status TEXT NOT NULL,
                side_effects_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                provider_kind TEXT,
                provider_ref TEXT,
                approval_id TEXT,
                run_id TEXT,
                job_id TEXT,
                output_json TEXT,
                error TEXT,
                duration_ms REAL,
                effect_id TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                idempotency_key TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_observations_capability "
            "ON tool_observations(capability_id, created_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS effect_ledger (
                effect_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                side_effects_json TEXT NOT NULL,
                status TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                provider_kind TEXT,
                provider_ref TEXT,
                approval_id TEXT,
                run_id TEXT,
                job_id TEXT,
                observation_id TEXT,
                error TEXT,
                idempotency_key TEXT,
                trace_id TEXT
            )
            """
        )
        # Durable kernel columns may be missing on older local schemas.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(effect_ledger)").fetchall()}
        if "idempotency_key" not in cols:
            conn.execute("ALTER TABLE effect_ledger ADD COLUMN idempotency_key TEXT")
        if "trace_id" not in cols:
            conn.execute("ALTER TABLE effect_ledger ADD COLUMN trace_id TEXT")
        obs_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(tool_observations)").fetchall()
        }
        if "idempotency_key" not in obs_cols:
            conn.execute("ALTER TABLE tool_observations ADD COLUMN idempotency_key TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_effect_ledger_request "
            "ON effect_ledger(request_id, recorded_at)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_effect_ledger_idempotency "
            "ON effect_ledger(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_observations_idempotency "
            "ON tool_observations(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )

    def record_execution(
        self,
        *,
        request_id: str,
        capability_id: str,
        status: str,
        side_effects: tuple[str, ...] | list[str],
        provider_kind: str | None = None,
        provider_ref: str | None = None,
        approval_id: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: float | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[ToolObservation, EffectRecord]:
        # Idempotent COMPLETED: return prior observation/effect without a second write.
        if idempotency_key and status == "COMPLETED":
            prior = self.get_completed_by_idempotency_key(idempotency_key)
            if prior is not None:
                observation, effect = prior
                return observation, effect

        observation_id = str(uuid.uuid4())
        effect_id = str(uuid.uuid4())
        now = utc_now()
        effects = tuple(side_effects)
        from Data.modules.common.secrets import redact_secrets
        from Data.modules.observability.redaction import redact_payload

        safe_output = redact_payload(output) if isinstance(output, dict) else output
        safe_error = redact_secrets(error) if isinstance(error, str) else error
        safe_meta = redact_payload(dict(metadata or {}))
        if idempotency_key:
            safe_meta = {**safe_meta, "idempotency_key": idempotency_key}
        if trace_id:
            safe_meta = {**safe_meta, "trace_id": trace_id}
        observation = ToolObservation(
            observation_id=observation_id,
            request_id=request_id,
            capability_id=capability_id,
            status=status,
            side_effects=effects,
            created_at=now,
            provider_kind=provider_kind,
            provider_ref=provider_ref,
            approval_id=approval_id,
            run_id=run_id,
            job_id=job_id,
            output=safe_output if isinstance(safe_output, dict) else output,
            error=safe_error,
            duration_ms=duration_ms,
            effect_id=effect_id,
            metadata=safe_meta,
        )
        effect = EffectRecord(
            effect_id=effect_id,
            request_id=request_id,
            capability_id=capability_id,
            side_effects=effects,
            status=status,
            recorded_at=now,
            provider_kind=provider_kind,
            provider_ref=provider_ref,
            approval_id=approval_id,
            run_id=run_id,
            job_id=job_id,
            observation_id=observation_id,
            error=error,
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO tool_observations(
                    observation_id, request_id, capability_id, status, side_effects_json,
                    created_at, provider_kind, provider_ref, approval_id, run_id, job_id,
                    output_json, error, duration_ms, effect_id, metadata_json, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.observation_id,
                    observation.request_id,
                    observation.capability_id,
                    observation.status,
                    json.dumps(list(observation.side_effects)),
                    observation.created_at,
                    observation.provider_kind,
                    observation.provider_ref,
                    observation.approval_id,
                    observation.run_id,
                    observation.job_id,
                    json.dumps(observation.output) if observation.output is not None else None,
                    observation.error,
                    observation.duration_ms,
                    observation.effect_id,
                    json.dumps(observation.metadata),
                    idempotency_key,
                ),
            )
            conn.execute(
                """
                INSERT INTO effect_ledger(
                    effect_id, request_id, capability_id, side_effects_json, status,
                    recorded_at, provider_kind, provider_ref, approval_id, run_id, job_id,
                    observation_id, error, idempotency_key, trace_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    effect.effect_id,
                    effect.request_id,
                    effect.capability_id,
                    json.dumps(list(effect.side_effects)),
                    effect.status,
                    effect.recorded_at,
                    effect.provider_kind,
                    effect.provider_ref,
                    effect.approval_id,
                    effect.run_id,
                    effect.job_id,
                    effect.observation_id,
                    effect.error,
                    idempotency_key,
                    trace_id,
                ),
            )
        return observation, effect

    def get_completed_by_idempotency_key(
        self, idempotency_key: str
    ) -> tuple[ToolObservation, EffectRecord] | None:
        """Return prior COMPLETED observation+effect for an idempotency key, if any."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT * FROM tool_observations
                WHERE idempotency_key = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (idempotency_key, "COMPLETED"),
            ).fetchone()
            if row is None:
                return None
            observation = self._obs_from_row(row)
            effect_row = None
            if observation.effect_id:
                effect_row = conn.execute(
                    "SELECT * FROM effect_ledger WHERE effect_id = ?",
                    (observation.effect_id,),
                ).fetchone()
            if effect_row is None:
                effect_row = conn.execute(
                    """
                    SELECT * FROM effect_ledger
                    WHERE idempotency_key = ? AND status = ?
                    ORDER BY recorded_at DESC LIMIT 1
                    """,
                    (idempotency_key, "COMPLETED"),
                ).fetchone()
        if effect_row is None:
            effect = EffectRecord(
                effect_id=observation.effect_id or observation.observation_id,
                request_id=observation.request_id,
                capability_id=observation.capability_id,
                side_effects=observation.side_effects,
                status=observation.status,
                recorded_at=observation.created_at,
                provider_kind=observation.provider_kind,
                provider_ref=observation.provider_ref,
                approval_id=observation.approval_id,
                run_id=observation.run_id,
                job_id=observation.job_id,
                observation_id=observation.observation_id,
                error=observation.error,
            )
        else:
            effect = self._effect_from_row(effect_row)
        return observation, effect

    def get_observation(self, observation_id: str) -> ToolObservation | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM tool_observations WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
        return self._obs_from_row(row) if row else None

    def list_observations(
        self,
        *,
        capability_id: str | None = None,
        limit: int = 100,
    ) -> list[ToolObservation]:
        clauses: list[str] = []
        params: list[Any] = []
        if capability_id:
            clauses.append("capability_id = ?")
            params.append(capability_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                f"SELECT * FROM tool_observations {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._obs_from_row(row) for row in rows]

    def list_effects(self, *, limit: int = 100) -> list[EffectRecord]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM effect_ledger ORDER BY recorded_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [self._effect_from_row(row) for row in rows]

    @staticmethod
    def _obs_from_row(row: sqlite3.Row) -> ToolObservation:
        return ToolObservation(
            observation_id=row["observation_id"],
            request_id=row["request_id"],
            capability_id=row["capability_id"],
            status=row["status"],
            side_effects=tuple(json.loads(row["side_effects_json"])),
            created_at=row["created_at"],
            provider_kind=row["provider_kind"],
            provider_ref=row["provider_ref"],
            approval_id=row["approval_id"],
            run_id=row["run_id"],
            job_id=row["job_id"],
            output=json.loads(row["output_json"]) if row["output_json"] else None,
            error=row["error"],
            duration_ms=row["duration_ms"],
            effect_id=row["effect_id"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _effect_from_row(row: sqlite3.Row) -> EffectRecord:
        return EffectRecord(
            effect_id=row["effect_id"],
            request_id=row["request_id"],
            capability_id=row["capability_id"],
            side_effects=tuple(json.loads(row["side_effects_json"])),
            status=row["status"],
            recorded_at=row["recorded_at"],
            provider_kind=row["provider_kind"],
            provider_ref=row["provider_ref"],
            approval_id=row["approval_id"],
            run_id=row["run_id"],
            job_id=row["job_id"],
            observation_id=row["observation_id"],
            error=row["error"],
        )
