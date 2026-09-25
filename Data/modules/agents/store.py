"""SQLite persistence for agent definitions, missions, and events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .fleet_types import (
    ACTIVE_MISSION_STATUSES,
    AgentDefinition,
    AgentDefinitionKind,
    AgentEvent,
    AgentHealth,
    AgentMission,
    MissionStatus,
    OrchestratorConfig,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class AgentFleetStore:
    """Owns agent_definitions / agent_missions / agent_events rows (migration v22)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        from Data.modules.common.sqlite_policy import open_sqlite_connection

        conn = open_sqlite_connection(self.db_path, set_wal=False)
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            conn.close()


    def initialize(self) -> None:
        """Ensure schema exists (migrations own canonical DDL; this is defensive)."""
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_definitions (
                    agent_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    archived INTEGER NOT NULL DEFAULT 0,
                    model_ref TEXT,
                    system_policy TEXT,
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    knowledge_sources_json TEXT NOT NULL DEFAULT '[]',
                    memory_policy TEXT NOT NULL DEFAULT 'default',
                    dataset_access TEXT NOT NULL DEFAULT 'none',
                    approval_mode TEXT NOT NULL DEFAULT 'inherit',
                    autonomy INTEGER NOT NULL DEFAULT 50,
                    max_concurrency INTEGER NOT NULL DEFAULT 1,
                    timeout_s INTEGER,
                    max_retries INTEGER NOT NULL DEFAULT 0,
                    token_budget INTEGER,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    version INTEGER NOT NULL DEFAULT 1,
                    orchestrator_json TEXT,
                    health TEXT NOT NULL DEFAULT 'unknown',
                    health_reason TEXT,
                    last_run_at TEXT,
                    last_mission_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_missions (
                    mission_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    request TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'med',
                    progress REAL NOT NULL DEFAULT 0,
                    parent_mission_id TEXT,
                    run_id TEXT,
                    job_ids_json TEXT NOT NULL DEFAULT '[]',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    trace_id TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(agent_id) REFERENCES agent_definitions(agent_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_events (
                    event_id TEXT PRIMARY KEY,
                    agent_id TEXT,
                    mission_id TEXT,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    level TEXT NOT NULL DEFAULT 'info',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_definitions_kind ON agent_definitions(kind, enabled)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_missions_status ON agent_missions(status, updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_missions_agent ON agent_missions(agent_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_events_created ON agent_events(created_at)"
            )

    def _row_to_definition(self, row: sqlite3.Row) -> AgentDefinition:
        orch_raw = _loads(row["orchestrator_json"], None)
        return AgentDefinition(
            agent_id=row["agent_id"],
            name=row["name"],
            kind=AgentDefinitionKind(row["kind"]),
            description=row["description"] or "",
            role=row["role"] or "",
            enabled=bool(row["enabled"]),
            archived=bool(row["archived"]),
            model_ref=row["model_ref"],
            system_policy=row["system_policy"],
            capabilities=list(_loads(row["capabilities_json"], [])),
            knowledge_sources=list(_loads(row["knowledge_sources_json"], [])),
            memory_policy=row["memory_policy"] or "default",
            dataset_access=row["dataset_access"] or "none",
            approval_mode=row["approval_mode"] or "inherit",
            autonomy=int(row["autonomy"] or 50),
            max_concurrency=int(row["max_concurrency"] or 1),
            timeout_s=row["timeout_s"],
            max_retries=int(row["max_retries"] or 0),
            token_budget=row["token_budget"],
            tags=list(_loads(row["tags_json"], [])),
            version=int(row["version"] or 1),
            orchestrator=OrchestratorConfig.from_dict(orch_raw) if orch_raw else None,
            health=AgentHealth(row["health"] or "unknown"),
            health_reason=row["health_reason"],
            last_run_at=row["last_run_at"],
            last_mission_id=row["last_mission_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=dict(_loads(row["metadata_json"], {})),
        )

    def _row_to_mission(self, row: sqlite3.Row) -> AgentMission:
        return AgentMission(
            mission_id=row["mission_id"],
            agent_id=row["agent_id"],
            title=row["title"],
            request=row["request"],
            status=MissionStatus(row["status"]),
            priority=row["priority"] or "med",
            progress=float(row["progress"] or 0),
            parent_mission_id=row["parent_mission_id"],
            run_id=row["run_id"],
            job_ids=list(_loads(row["job_ids_json"], [])),
            result=dict(_loads(row["result_json"], {})),
            error=row["error"],
            cancel_requested=bool(row["cancel_requested"]),
            trace_id=row["trace_id"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
            metadata=dict(_loads(row["metadata_json"], {})),
        )

    def create_definition(self, definition: AgentDefinition) -> AgentDefinition:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_definitions(
                    agent_id, name, kind, description, role, enabled, archived, model_ref,
                    system_policy, capabilities_json, knowledge_sources_json, memory_policy,
                    dataset_access, approval_mode, autonomy, max_concurrency, timeout_s,
                    max_retries, token_budget, tags_json, version, orchestrator_json,
                    health, health_reason, last_run_at, last_mission_id, created_at, updated_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    definition.agent_id,
                    definition.name,
                    definition.kind.value,
                    definition.description,
                    definition.role,
                    1 if definition.enabled else 0,
                    1 if definition.archived else 0,
                    definition.model_ref,
                    definition.system_policy,
                    json.dumps(definition.capabilities),
                    json.dumps(definition.knowledge_sources),
                    definition.memory_policy,
                    definition.dataset_access,
                    definition.approval_mode,
                    definition.autonomy,
                    definition.max_concurrency,
                    definition.timeout_s,
                    definition.max_retries,
                    definition.token_budget,
                    json.dumps(definition.tags),
                    definition.version,
                    json.dumps(definition.orchestrator.public_dict()) if definition.orchestrator else None,
                    definition.health.value,
                    definition.health_reason,
                    definition.last_run_at,
                    definition.last_mission_id,
                    definition.created_at,
                    definition.updated_at,
                    json.dumps(definition.metadata),
                ),
            )
        return definition

    def update_definition(self, definition: AgentDefinition) -> AgentDefinition:
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE agent_definitions SET
                    name=?, kind=?, description=?, role=?, enabled=?, archived=?, model_ref=?,
                    system_policy=?, capabilities_json=?, knowledge_sources_json=?, memory_policy=?,
                    dataset_access=?, approval_mode=?, autonomy=?, max_concurrency=?, timeout_s=?,
                    max_retries=?, token_budget=?, tags_json=?, version=?, orchestrator_json=?,
                    health=?, health_reason=?, last_run_at=?, last_mission_id=?, updated_at=?,
                    metadata_json=?
                WHERE agent_id=?
                """,
                (
                    definition.name,
                    definition.kind.value,
                    definition.description,
                    definition.role,
                    1 if definition.enabled else 0,
                    1 if definition.archived else 0,
                    definition.model_ref,
                    definition.system_policy,
                    json.dumps(definition.capabilities),
                    json.dumps(definition.knowledge_sources),
                    definition.memory_policy,
                    definition.dataset_access,
                    definition.approval_mode,
                    definition.autonomy,
                    definition.max_concurrency,
                    definition.timeout_s,
                    definition.max_retries,
                    definition.token_budget,
                    json.dumps(definition.tags),
                    definition.version,
                    json.dumps(definition.orchestrator.public_dict()) if definition.orchestrator else None,
                    definition.health.value,
                    definition.health_reason,
                    definition.last_run_at,
                    definition.last_mission_id,
                    definition.updated_at,
                    json.dumps(definition.metadata),
                    definition.agent_id,
                ),
            )
            if cur.rowcount == 0:
                raise KeyError(definition.agent_id)
        return definition

    def get_definition(self, agent_id: str) -> AgentDefinition | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_definitions WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        return self._row_to_definition(row) if row else None

    def list_definitions(
        self,
        *,
        include_archived: bool = False,
        kind: str | None = None,
        limit: int = 200,
    ) -> list[AgentDefinition]:
        clauses = ["1=1"]
        params: list[Any] = []
        if not include_archived:
            clauses.append("archived = 0")
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        params.append(max(1, min(limit, 500)))
        sql = (
            f"SELECT * FROM agent_definitions WHERE {' AND '.join(clauses)} "
            "ORDER BY updated_at DESC LIMIT ?"
        )
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_definition(r) for r in rows]

    def create_mission(self, mission: AgentMission) -> AgentMission:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_missions(
                    mission_id, agent_id, title, request, status, priority, progress,
                    parent_mission_id, run_id, job_ids_json, result_json, error,
                    cancel_requested, trace_id, created_at, started_at, updated_at,
                    finished_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mission.mission_id,
                    mission.agent_id,
                    mission.title,
                    mission.request,
                    mission.status.value,
                    mission.priority,
                    mission.progress,
                    mission.parent_mission_id,
                    mission.run_id,
                    json.dumps(mission.job_ids),
                    json.dumps(mission.result),
                    mission.error,
                    1 if mission.cancel_requested else 0,
                    mission.trace_id,
                    mission.created_at,
                    mission.started_at,
                    mission.updated_at,
                    mission.finished_at,
                    json.dumps(mission.metadata),
                ),
            )
        return mission

    def update_mission(self, mission: AgentMission) -> AgentMission:
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE agent_missions SET
                    status=?, priority=?, progress=?, parent_mission_id=?, run_id=?,
                    job_ids_json=?, result_json=?, error=?, cancel_requested=?,
                    started_at=?, updated_at=?, finished_at=?, metadata_json=?
                WHERE mission_id=?
                """,
                (
                    mission.status.value,
                    mission.priority,
                    mission.progress,
                    mission.parent_mission_id,
                    mission.run_id,
                    json.dumps(mission.job_ids),
                    json.dumps(mission.result),
                    mission.error,
                    1 if mission.cancel_requested else 0,
                    mission.started_at,
                    mission.updated_at,
                    mission.finished_at,
                    json.dumps(mission.metadata),
                    mission.mission_id,
                ),
            )
            if cur.rowcount == 0:
                raise KeyError(mission.mission_id)
        return mission

    def get_mission(self, mission_id: str) -> AgentMission | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_missions WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()
        return self._row_to_mission(row) if row else None

    def list_missions(
        self,
        *,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[AgentMission]:
        clauses = ["1=1"]
        params: list[Any] = []
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        params.append(max(1, min(limit, 500)))
        sql = (
            f"SELECT * FROM agent_missions WHERE {' AND '.join(clauses)} "
            "ORDER BY updated_at DESC LIMIT ?"
        )
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_mission(r) for r in rows]

    def count_active_for_agent(self, agent_id: str) -> int:
        placeholders = ",".join("?" for _ in ACTIVE_MISSION_STATUSES)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM agent_missions WHERE agent_id = ? AND status IN ({placeholders})",
                (agent_id, *sorted(ACTIVE_MISSION_STATUSES)),
            ).fetchone()
        return int(row["c"] if row else 0)

    def append_event(self, event: AgentEvent) -> AgentEvent:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_events(
                    event_id, agent_id, mission_id, category, message, level, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.agent_id,
                    event.mission_id,
                    event.category,
                    event.message,
                    event.level,
                    json.dumps(event.payload),
                    event.created_at,
                ),
            )
        return event

    def list_events(
        self,
        *,
        agent_id: str | None = None,
        mission_id: str | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> list[AgentEvent]:
        clauses = ["1=1"]
        params: list[Any] = []
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if mission_id:
            clauses.append("mission_id = ?")
            params.append(mission_id)
        if category:
            clauses.append("category = ?")
            params.append(category)
        params.append(max(1, min(limit, 500)))
        sql = (
            f"SELECT * FROM agent_events WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC LIMIT ?"
        )
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            AgentEvent(
                event_id=r["event_id"],
                agent_id=r["agent_id"],
                mission_id=r["mission_id"],
                category=r["category"],
                message=r["message"],
                level=r["level"] or "info",
                payload=dict(_loads(r["payload_json"], {})),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    @staticmethod
    def new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:16]}"
