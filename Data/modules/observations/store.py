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
                metadata_json TEXT NOT NULL DEFAULT '{}'
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
                error TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_effect_ledger_request "
            "ON effect_ledger(request_id, recorded_at)"
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
    ) -> tuple[ToolObservation, EffectRecord]:
        observation_id = str(uuid.uuid4())
        effect_id = str(uuid.uuid4())
        now = utc_now()
        effects = tuple(side_effects)
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
            output=output,
            error=error,
            duration_ms=duration_ms,
            effect_id=effect_id,
            metadata=metadata or {},
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
                    output_json, error, duration_ms, effect_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            conn.execute(
                """
                INSERT INTO effect_ledger(
                    effect_id, request_id, capability_id, side_effects_json, status,
                    recorded_at, provider_kind, provider_ref, approval_id, run_id, job_id,
                    observation_id, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
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
