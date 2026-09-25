"""SQLite persistence for research projects, sources, evidence, claims, reports."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import (
    AnalysisMode,
    BrainStatus,
    ClaimStatus,
    CoverageSummary,
    ParseStatus,
    ResearchBudget,
    ResearchClaim,
    ResearchConflict,
    ResearchEvidence,
    ResearchEvent,
    ResearchExecutionMode,
    ResearchPhase,
    ResearchPlan,
    ResearchProject,
    ResearchReport,
    ResearchRun,
    ResearchSource,
    ResearchStatus,
    ResearchDepth,
    ResearchWorker,
    SourceType,
    WorkerStatus,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class ResearchStore:
    """Durable research workspace backed by research_* tables (migration v14)."""

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
        from Data.modules.common.sqlite_policy import ensure_wal

        with self.connect() as conn:
            ensure_wal(conn)
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        # Mirror migrations so unit tests can use an isolated DB.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_projects (
                project_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                topic TEXT NOT NULL,
                objective TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                depth TEXT NOT NULL DEFAULT 'standard',
                allow_web INTEGER NOT NULL DEFAULT 0,
                respect_robots_txt INTEGER NOT NULL DEFAULT 1,
                model_profile_json TEXT NOT NULL DEFAULT '{}',
                budget_json TEXT NOT NULL DEFAULT '{}',
                plan_json TEXT NOT NULL DEFAULT '{}',
                coverage_json TEXT NOT NULL DEFAULT '{}',
                local_scopes_json TEXT NOT NULL DEFAULT '[]',
                seed_sources_json TEXT NOT NULL DEFAULT '[]',
                current_round INTEGER NOT NULL DEFAULT 0,
                total_rounds INTEGER NOT NULL DEFAULT 1,
                error TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                worker_pid INTEGER,
                trace_id TEXT,
                report_version INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS research_events (
                event_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_research_events_project
                ON research_events(project_id, created_at);
            CREATE TABLE IF NOT EXISTS research_sources (
                source_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                original_uri TEXT,
                canonical_uri TEXT,
                title TEXT,
                author TEXT,
                published_at TEXT,
                fetched_at TEXT,
                content_hash TEXT,
                mime_type TEXT,
                snapshot_path TEXT,
                parse_status TEXT,
                parser TEXT,
                provenance_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS research_evidence (
                evidence_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                chunk_id TEXT,
                span_text TEXT NOT NULL,
                location_json TEXT NOT NULL DEFAULT '{}',
                retrieval_method TEXT,
                associated_claim_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES research_sources(source_id)
            );
            CREATE TABLE IF NOT EXISTS research_claims (
                claim_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                proposition TEXT NOT NULL,
                raw_wording TEXT,
                status TEXT NOT NULL,
                supporting_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                contradicting_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                source_diversity INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS research_conflicts (
                conflict_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                claim_id TEXT,
                summary TEXT NOT NULL,
                supporting_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                contradicting_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                analysis_json TEXT NOT NULL DEFAULT '{}',
                unresolved_questions_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS research_reports (
                report_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                title TEXT NOT NULL,
                body_markdown TEXT NOT NULL,
                body_html TEXT,
                evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                source_ids_json TEXT NOT NULL DEFAULT '[]',
                model_profile_json TEXT NOT NULL DEFAULT '{}',
                generation_trace_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(project_id, version),
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS research_runs (
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                status TEXT NOT NULL,
                execution_mode TEXT NOT NULL DEFAULT 'normal',
                workers INTEGER NOT NULL DEFAULT 1,
                rounds_per_worker INTEGER NOT NULL DEFAULT 1,
                phase TEXT NOT NULL DEFAULT 'idle',
                completed_worker_rounds INTEGER NOT NULL DEFAULT 0,
                total_worker_rounds INTEGER NOT NULL DEFAULT 0,
                progress_pct REAL NOT NULL DEFAULT 0,
                analysis_mode TEXT NOT NULL DEFAULT 'deterministic_fallback',
                error TEXT,
                started_at TEXT,
                finished_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_research_runs_project
                ON research_runs(project_id, created_at);
            CREATE TABLE IF NOT EXISTS research_workers (
                worker_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                worker_index INTEGER NOT NULL,
                status TEXT NOT NULL,
                phase TEXT NOT NULL DEFAULT '',
                current_round INTEGER NOT NULL DEFAULT 0,
                total_rounds INTEGER NOT NULL DEFAULT 1,
                completed_rounds INTEGER NOT NULL DEFAULT 0,
                current_query TEXT,
                current_task TEXT,
                sources_added INTEGER NOT NULL DEFAULT 0,
                evidence_added INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                heartbeat_at TEXT,
                finished_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
                FOREIGN KEY(run_id) REFERENCES research_runs(run_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_research_workers_run
                ON research_workers(run_id, worker_index);
            CREATE INDEX IF NOT EXISTS idx_research_workers_project
                ON research_workers(project_id, updated_at);
            """
        )
        self._ensure_columns(
            conn,
            "research_projects",
            {
                "execution_mode": "TEXT NOT NULL DEFAULT 'normal'",
                "phase": "TEXT NOT NULL DEFAULT 'idle'",
                "progress_pct": "REAL NOT NULL DEFAULT 0",
                "analysis_mode": "TEXT NOT NULL DEFAULT 'deterministic_fallback'",
                "active_run_id": "TEXT",
                "completed_worker_rounds": "INTEGER NOT NULL DEFAULT 0",
                "total_worker_rounds": "INTEGER NOT NULL DEFAULT 0",
                "connected_datasets_json": "TEXT NOT NULL DEFAULT '[]'",
                "kernel_job_id": "TEXT",
                "wait_reason": "TEXT",
            },
        )
        self._ensure_columns(
            conn,
            "research_sources",
            {
                "brain_status": "TEXT NOT NULL DEFAULT 'not_applicable'",
                "brain_document_id": "TEXT",
                "brain_error": "TEXT",
            },
        )

    def _ensure_columns(
        self,
        conn: sqlite3.Connection,
        table: str,
        columns: dict[str, str],
    ) -> None:
        existing = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    # --- projects -----------------------------------------------------------

    def create_project(
        self,
        *,
        title: str,
        topic: str,
        objective: str = "",
        depth: ResearchDepth = ResearchDepth.STANDARD,
        allow_web: bool = False,
        respect_robots_txt: bool = True,
        model_profile: dict[str, Any] | None = None,
        budget: ResearchBudget | None = None,
        local_scopes: list[str] | None = None,
        seed_sources: list[str] | None = None,
        connected_datasets: list[dict[str, Any]] | None = None,
        execution_mode: ResearchExecutionMode = ResearchExecutionMode.CUSTOM,
        project_id: str | None = None,
        trace_id: str | None = None,
    ) -> ResearchProject:
        now = utc_now()
        from .budgets import budget_for_depth, clamp_budget

        bud = clamp_budget(budget or budget_for_depth(depth))
        project = ResearchProject(
            project_id=project_id or str(uuid.uuid4()),
            title=title.strip() or topic.strip()[:80] or "Untitled research",
            topic=topic.strip(),
            objective=objective.strip(),
            status=ResearchStatus.DRAFT,
            depth=depth,
            allow_web=bool(allow_web),
            respect_robots_txt=bool(respect_robots_txt),
            model_profile=dict(model_profile or {}),
            budget=bud,
            local_scopes=list(local_scopes or []),
            seed_sources=list(seed_sources or []),
            connected_datasets=list(connected_datasets or []),
            total_rounds=bud.rounds,
            execution_mode=execution_mode,
            total_worker_rounds=bud.research_workers * bud.rounds,
            trace_id=trace_id or str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            self._insert_project(conn, project)
        return project

    def _insert_project(self, conn: sqlite3.Connection, project: ResearchProject) -> None:
        conn.execute(
            """
            INSERT INTO research_projects(
                project_id, title, topic, objective, status, depth, allow_web,
                respect_robots_txt, model_profile_json, budget_json, plan_json,
                coverage_json, local_scopes_json, seed_sources_json, current_round,
                total_rounds, error, cancel_requested, worker_pid, trace_id,
                report_version, created_at, updated_at, started_at, finished_at,
                execution_mode, phase, progress_pct, analysis_mode, active_run_id,
                completed_worker_rounds, total_worker_rounds, connected_datasets_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                project.project_id,
                project.title,
                project.topic,
                project.objective,
                project.status.value,
                project.depth.value,
                1 if project.allow_web else 0,
                1 if project.respect_robots_txt else 0,
                _json_dumps(project.model_profile),
                _json_dumps(project.budget.public_dict()),
                _json_dumps(project.plan.public_dict() if project.plan else {}),
                _json_dumps(project.coverage.public_dict() if project.coverage else {}),
                _json_dumps(project.local_scopes),
                _json_dumps(project.seed_sources),
                project.current_round,
                project.total_rounds,
                project.error,
                1 if project.cancel_requested else 0,
                project.worker_pid,
                project.trace_id,
                project.report_version,
                project.created_at,
                project.updated_at,
                project.started_at,
                project.finished_at,
                project.execution_mode.value,
                project.phase.value,
                float(project.progress_pct),
                project.analysis_mode.value,
                project.active_run_id,
                project.completed_worker_rounds,
                project.total_worker_rounds,
                _json_dumps(project.connected_datasets),
            ),
        )

    def save_project(self, project: ResearchProject) -> ResearchProject:
        project.updated_at = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                UPDATE research_projects SET
                    title=?, topic=?, objective=?, status=?, depth=?, allow_web=?,
                    respect_robots_txt=?, model_profile_json=?, budget_json=?, plan_json=?,
                    coverage_json=?, local_scopes_json=?, seed_sources_json=?,
                    current_round=?, total_rounds=?, error=?, cancel_requested=?,
                    worker_pid=?, trace_id=?, report_version=?, updated_at=?,
                    started_at=?, finished_at=?,
                    execution_mode=?, phase=?, progress_pct=?, analysis_mode=?,
                    active_run_id=?, completed_worker_rounds=?, total_worker_rounds=?,
                    connected_datasets_json=?, kernel_job_id=?, wait_reason=?
                WHERE project_id=?
                """,
                (
                    project.title,
                    project.topic,
                    project.objective,
                    project.status.value,
                    project.depth.value,
                    1 if project.allow_web else 0,
                    1 if project.respect_robots_txt else 0,
                    _json_dumps(project.model_profile),
                    _json_dumps(project.budget.public_dict()),
                    _json_dumps(project.plan.public_dict() if project.plan else {}),
                    _json_dumps(project.coverage.public_dict() if project.coverage else {}),
                    _json_dumps(project.local_scopes),
                    _json_dumps(project.seed_sources),
                    project.current_round,
                    project.total_rounds,
                    project.error,
                    1 if project.cancel_requested else 0,
                    project.worker_pid,
                    project.trace_id,
                    project.report_version,
                    project.updated_at,
                    project.started_at,
                    project.finished_at,
                    project.execution_mode.value,
                    project.phase.value,
                    float(project.progress_pct),
                    project.analysis_mode.value,
                    project.active_run_id,
                    project.completed_worker_rounds,
                    project.total_worker_rounds,
                    _json_dumps(project.connected_datasets),
                    project.kernel_job_id,
                    project.wait_reason,
                    project.project_id,
                ),
            )
        return project

    def claim_queued_execution(
        self,
        project_id: str,
        *,
        worker_pid: int,
        kernel_job_id: str | None = None,
    ) -> bool:
        """Durable CAS: QUEUED → RESEARCHING for worker-owned execution.

        Returns True only for the winner. Prevents duplicate ResearchRun creation
        when two physical workers race the same project.
        """
        now = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            cur = conn.execute(
                """
                UPDATE research_projects
                SET status = ?,
                    phase = ?,
                    worker_pid = ?,
                    kernel_job_id = COALESCE(?, kernel_job_id),
                    wait_reason = NULL,
                    progress_pct = CASE
                        WHEN progress_pct < 5.0 THEN 5.0
                        ELSE progress_pct
                    END,
                    started_at = COALESCE(started_at, ?),
                    finished_at = NULL,
                    error = NULL,
                    updated_at = ?
                WHERE project_id = ?
                  AND status = ?
                """,
                (
                    ResearchStatus.RESEARCHING.value,
                    ResearchPhase.PLANNING.value,
                    int(worker_pid),
                    kernel_job_id,
                    now,
                    now,
                    project_id,
                    ResearchStatus.QUEUED.value,
                ),
            )
            return int(cur.rowcount or 0) > 0

    def get_project(self, project_id: str) -> ResearchProject | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM research_projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if row is None:
                return None
            project = self._project_from_row(row)
            self._attach_counts(conn, project)
            project.workers = [
                w.public_dict() for w in self._list_workers_conn(conn, project_id)
            ]
            return project

    def list_projects(self, *, limit: int = 100) -> list[ResearchProject]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM research_projects ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
            projects = [self._project_from_row(row) for row in rows]
            for project in projects:
                self._attach_counts(conn, project)
                project.workers = [
                    w.public_dict() for w in self._list_workers_conn(conn, project.project_id)
                ]
            return projects

    def _attach_counts(self, conn: sqlite3.Connection, project: ResearchProject) -> None:
        pid = project.project_id
        project.source_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM research_sources WHERE project_id = ?", (pid,)
            ).fetchone()[0]
        )
        project.evidence_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM research_evidence WHERE project_id = ?", (pid,)
            ).fetchone()[0]
        )
        project.claim_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM research_claims WHERE project_id = ?", (pid,)
            ).fetchone()[0]
        )
        project.conflict_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM research_conflicts WHERE project_id = ?", (pid,)
            ).fetchone()[0]
        )

    def _row_get(self, row: sqlite3.Row, key: str, default: Any = None) -> Any:
        try:
            return row[key]
        except (IndexError, KeyError):
            return default

    def _project_from_row(self, row: sqlite3.Row) -> ResearchProject:
        plan_raw = _json_loads(row["plan_json"], {})
        coverage_raw = _json_loads(row["coverage_json"], {})
        mode_raw = self._row_get(row, "execution_mode", "normal") or "normal"
        phase_raw = self._row_get(row, "phase", "idle") or "idle"
        analysis_raw = (
            self._row_get(row, "analysis_mode", "deterministic_fallback")
            or "deterministic_fallback"
        )
        try:
            execution_mode = ResearchExecutionMode(str(mode_raw))
        except ValueError:
            execution_mode = ResearchExecutionMode.NORMAL
        try:
            phase = ResearchPhase(str(phase_raw))
        except ValueError:
            phase = ResearchPhase.IDLE
        try:
            analysis_mode = AnalysisMode(str(analysis_raw))
        except ValueError:
            analysis_mode = AnalysisMode.DETERMINISTIC_FALLBACK
        return ResearchProject(
            project_id=row["project_id"],
            title=row["title"],
            topic=row["topic"],
            objective=row["objective"] or "",
            status=ResearchStatus(row["status"]),
            depth=ResearchDepth(row["depth"]),
            allow_web=bool(row["allow_web"]),
            respect_robots_txt=bool(row["respect_robots_txt"]),
            model_profile=_json_loads(row["model_profile_json"], {}),
            budget=ResearchBudget.from_dict(_json_loads(row["budget_json"], {})),
            plan=ResearchPlan.from_dict(plan_raw) if plan_raw else None,
            coverage=CoverageSummary.from_dict(coverage_raw) if coverage_raw else None,
            local_scopes=list(_json_loads(row["local_scopes_json"], [])),
            seed_sources=list(_json_loads(row["seed_sources_json"], [])),
            connected_datasets=list(
                _json_loads(self._row_get(row, "connected_datasets_json", "[]"), [])
            ),
            current_round=int(row["current_round"] or 0),
            total_rounds=int(row["total_rounds"] or 1),
            error=row["error"],
            cancel_requested=bool(row["cancel_requested"]),
            worker_pid=row["worker_pid"],
            trace_id=row["trace_id"],
            report_version=int(row["report_version"] or 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            execution_mode=execution_mode,
            phase=phase,
            progress_pct=float(self._row_get(row, "progress_pct", 0) or 0),
            analysis_mode=analysis_mode,
            active_run_id=self._row_get(row, "active_run_id"),
            completed_worker_rounds=int(
                self._row_get(row, "completed_worker_rounds", 0) or 0
            ),
            total_worker_rounds=int(self._row_get(row, "total_worker_rounds", 0) or 0),
            kernel_job_id=self._row_get(row, "kernel_job_id"),
            wait_reason=self._row_get(row, "wait_reason"),
        )

    def request_cancel(self, project_id: str) -> ResearchProject:
        project = self.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        project.cancel_requested = True
        if project.status in {
            ResearchStatus.QUEUED,
            ResearchStatus.RESEARCHING,
            ResearchStatus.SYNTHESIZING,
        }:
            project.status = ResearchStatus.CANCELLING
        return self.save_project(project)

    def is_cancel_requested(self, project_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM research_projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return bool(row and row["cancel_requested"])

    # --- events -------------------------------------------------------------

    def add_event(
        self,
        project_id: str,
        event_type: str,
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> ResearchEvent:
        event = ResearchEvent(
            event_id=str(uuid.uuid4()),
            project_id=project_id,
            event_type=event_type,
            message=message,
            payload=dict(payload or {}),
            created_at=utc_now(),
        )
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO research_events(
                    event_id, project_id, event_type, message, payload_json, created_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    event.event_id,
                    event.project_id,
                    event.event_type,
                    event.message,
                    _json_dumps(event.payload),
                    event.created_at,
                ),
            )
        return event

    def list_events(self, project_id: str, *, limit: int = 200) -> list[ResearchEvent]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM research_events
                WHERE project_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (project_id, max(1, min(limit, 2000))),
            ).fetchall()
        return [
            ResearchEvent(
                event_id=row["event_id"],
                project_id=row["project_id"],
                event_type=row["event_type"],
                message=row["message"] or "",
                payload=_json_loads(row["payload_json"], {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # --- sources ------------------------------------------------------------

    def upsert_source(self, source: ResearchSource) -> ResearchSource:
        with self.connect() as conn:
            self._ensure_schema(conn)
            existing = None
            if source.content_hash:
                existing = conn.execute(
                    """
                    SELECT source_id FROM research_sources
                    WHERE project_id = ? AND content_hash = ?
                    LIMIT 1
                    """,
                    (source.project_id, source.content_hash),
                ).fetchone()
            if existing:
                # Return existing rather than duplicate unchanged content.
                row = conn.execute(
                    "SELECT * FROM research_sources WHERE source_id = ?",
                    (existing["source_id"],),
                ).fetchone()
                return self._source_from_row(row)
            conn.execute(
                """
                INSERT INTO research_sources(
                    source_id, project_id, source_type, original_uri, canonical_uri,
                    title, author, published_at, fetched_at, content_hash, mime_type,
                    snapshot_path, parse_status, parser, provenance_json, metadata_json,
                    created_at, brain_status, brain_document_id, brain_error
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    source.source_id,
                    source.project_id,
                    source.source_type.value,
                    source.original_uri,
                    source.canonical_uri,
                    source.title,
                    source.author,
                    source.published_at,
                    source.fetched_at,
                    source.content_hash,
                    source.mime_type,
                    source.snapshot_path,
                    source.parse_status.value,
                    source.parser,
                    _json_dumps(source.provenance),
                    _json_dumps(source.metadata),
                    source.created_at,
                    source.brain_status.value,
                    source.brain_document_id,
                    source.brain_error,
                ),
            )
        return source

    def save_source(self, source: ResearchSource) -> ResearchSource:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                UPDATE research_sources SET
                    source_type=?, original_uri=?, canonical_uri=?, title=?, author=?,
                    published_at=?, fetched_at=?, content_hash=?, mime_type=?,
                    snapshot_path=?, parse_status=?, parser=?, provenance_json=?,
                    metadata_json=?, brain_status=?, brain_document_id=?, brain_error=?
                WHERE source_id=?
                """,
                (
                    source.source_type.value,
                    source.original_uri,
                    source.canonical_uri,
                    source.title,
                    source.author,
                    source.published_at,
                    source.fetched_at,
                    source.content_hash,
                    source.mime_type,
                    source.snapshot_path,
                    source.parse_status.value,
                    source.parser,
                    _json_dumps(source.provenance),
                    _json_dumps(source.metadata),
                    source.brain_status.value,
                    source.brain_document_id,
                    source.brain_error,
                    source.source_id,
                ),
            )
        return source

    def get_source(self, source_id: str) -> ResearchSource | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM research_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        return self._source_from_row(row) if row else None

    def list_sources(self, project_id: str, *, limit: int = 200) -> list[ResearchSource]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM research_sources
                WHERE project_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (project_id, max(1, min(limit, 2000))),
            ).fetchall()
        return [self._source_from_row(row) for row in rows]

    def _source_from_row(self, row: sqlite3.Row) -> ResearchSource:
        brain_raw = self._row_get(row, "brain_status", "not_applicable") or "not_applicable"
        try:
            brain_status = BrainStatus(str(brain_raw))
        except ValueError:
            brain_status = BrainStatus.NOT_APPLICABLE
        return ResearchSource(
            source_id=row["source_id"],
            project_id=row["project_id"],
            source_type=SourceType(row["source_type"]),
            original_uri=row["original_uri"],
            canonical_uri=row["canonical_uri"],
            title=row["title"],
            author=row["author"],
            published_at=row["published_at"],
            fetched_at=row["fetched_at"],
            content_hash=row["content_hash"],
            mime_type=row["mime_type"],
            snapshot_path=row["snapshot_path"],
            parse_status=ParseStatus(row["parse_status"] or ParseStatus.PENDING.value),
            parser=row["parser"],
            brain_status=brain_status,
            brain_document_id=self._row_get(row, "brain_document_id"),
            brain_error=self._row_get(row, "brain_error"),
            provenance=_json_loads(row["provenance_json"], {}),
            metadata=_json_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    # --- evidence -----------------------------------------------------------

    def add_evidence(self, evidence: ResearchEvidence) -> ResearchEvidence:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO research_evidence(
                    evidence_id, project_id, source_id, chunk_id, span_text,
                    location_json, retrieval_method, associated_claim_ids_json,
                    created_at, metadata_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    evidence.evidence_id,
                    evidence.project_id,
                    evidence.source_id,
                    evidence.chunk_id,
                    evidence.span_text,
                    _json_dumps(evidence.location),
                    evidence.retrieval_method,
                    _json_dumps(evidence.associated_claim_ids),
                    evidence.created_at,
                    _json_dumps(evidence.metadata),
                ),
            )
        return evidence

    def get_evidence(self, evidence_id: str) -> ResearchEvidence | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM research_evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        return self._evidence_from_row(row) if row else None

    def list_evidence(self, project_id: str, *, limit: int = 500) -> list[ResearchEvidence]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM research_evidence
                WHERE project_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (project_id, max(1, min(limit, 5000))),
            ).fetchall()
        return [self._evidence_from_row(row) for row in rows]

    def update_evidence_claims(self, evidence_id: str, claim_ids: list[str]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE research_evidence
                SET associated_claim_ids_json = ?
                WHERE evidence_id = ?
                """,
                (_json_dumps(claim_ids), evidence_id),
            )

    def _evidence_from_row(self, row: sqlite3.Row) -> ResearchEvidence:
        return ResearchEvidence(
            evidence_id=row["evidence_id"],
            project_id=row["project_id"],
            source_id=row["source_id"],
            chunk_id=row["chunk_id"],
            span_text=row["span_text"],
            location=_json_loads(row["location_json"], {}),
            retrieval_method=row["retrieval_method"],
            associated_claim_ids=list(_json_loads(row["associated_claim_ids_json"], [])),
            created_at=row["created_at"],
            metadata=_json_loads(row["metadata_json"], {}),
        )

    # --- claims / conflicts -------------------------------------------------

    def upsert_claim(self, claim: ResearchClaim) -> ResearchClaim:
        with self.connect() as conn:
            self._ensure_schema(conn)
            existing = conn.execute(
                "SELECT claim_id FROM research_claims WHERE claim_id = ?",
                (claim.claim_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE research_claims SET
                        proposition=?, raw_wording=?, status=?,
                        supporting_evidence_ids_json=?, contradicting_evidence_ids_json=?,
                        source_diversity=?, updated_at=?, metadata_json=?
                    WHERE claim_id=?
                    """,
                    (
                        claim.proposition,
                        claim.raw_wording,
                        claim.status.value,
                        _json_dumps(claim.supporting_evidence_ids),
                        _json_dumps(claim.contradicting_evidence_ids),
                        claim.source_diversity,
                        claim.updated_at,
                        _json_dumps(claim.metadata),
                        claim.claim_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO research_claims(
                        claim_id, project_id, proposition, raw_wording, status,
                        supporting_evidence_ids_json, contradicting_evidence_ids_json,
                        source_diversity, created_at, updated_at, metadata_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        claim.claim_id,
                        claim.project_id,
                        claim.proposition,
                        claim.raw_wording,
                        claim.status.value,
                        _json_dumps(claim.supporting_evidence_ids),
                        _json_dumps(claim.contradicting_evidence_ids),
                        claim.source_diversity,
                        claim.created_at,
                        claim.updated_at,
                        _json_dumps(claim.metadata),
                    ),
                )
        return claim

    def list_claims(self, project_id: str, *, limit: int = 500) -> list[ResearchClaim]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM research_claims
                WHERE project_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (project_id, max(1, min(limit, 5000))),
            ).fetchall()
        return [self._claim_from_row(row) for row in rows]

    def _claim_from_row(self, row: sqlite3.Row) -> ResearchClaim:
        return ResearchClaim(
            claim_id=row["claim_id"],
            project_id=row["project_id"],
            proposition=row["proposition"],
            raw_wording=row["raw_wording"],
            status=ClaimStatus(row["status"]),
            supporting_evidence_ids=list(_json_loads(row["supporting_evidence_ids_json"], [])),
            contradicting_evidence_ids=list(
                _json_loads(row["contradicting_evidence_ids_json"], [])
            ),
            source_diversity=int(row["source_diversity"] or 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=_json_loads(row["metadata_json"], {}),
        )

    def add_conflict(self, conflict: ResearchConflict) -> ResearchConflict:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO research_conflicts(
                    conflict_id, project_id, claim_id, summary,
                    supporting_evidence_ids_json, contradicting_evidence_ids_json,
                    analysis_json, unresolved_questions_json, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    conflict.conflict_id,
                    conflict.project_id,
                    conflict.claim_id,
                    conflict.summary,
                    _json_dumps(conflict.supporting_evidence_ids),
                    _json_dumps(conflict.contradicting_evidence_ids),
                    _json_dumps(conflict.analysis),
                    _json_dumps(conflict.unresolved_questions),
                    conflict.created_at,
                ),
            )
        return conflict

    def list_conflicts(self, project_id: str, *, limit: int = 200) -> list[ResearchConflict]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM research_conflicts
                WHERE project_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (project_id, max(1, min(limit, 2000))),
            ).fetchall()
        return [
            ResearchConflict(
                conflict_id=row["conflict_id"],
                project_id=row["project_id"],
                claim_id=row["claim_id"],
                summary=row["summary"],
                supporting_evidence_ids=list(
                    _json_loads(row["supporting_evidence_ids_json"], [])
                ),
                contradicting_evidence_ids=list(
                    _json_loads(row["contradicting_evidence_ids_json"], [])
                ),
                analysis=_json_loads(row["analysis_json"], {}),
                unresolved_questions=list(_json_loads(row["unresolved_questions_json"], [])),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # --- reports ------------------------------------------------------------

    def add_report(self, report: ResearchReport) -> ResearchReport:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO research_reports(
                    report_id, project_id, version, title, body_markdown, body_html,
                    evidence_ids_json, source_ids_json, model_profile_json,
                    generation_trace_json, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    report.report_id,
                    report.project_id,
                    report.version,
                    report.title,
                    report.body_markdown,
                    report.body_html,
                    _json_dumps(report.evidence_ids),
                    _json_dumps(report.source_ids),
                    _json_dumps(report.model_profile),
                    _json_dumps(report.generation_trace),
                    report.created_at,
                ),
            )
            conn.execute(
                """
                UPDATE research_projects
                SET report_version = ?, updated_at = ?
                WHERE project_id = ?
                """,
                (report.version, utc_now(), report.project_id),
            )
        return report

    def get_latest_report(self, project_id: str) -> ResearchReport | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT * FROM research_reports
                WHERE project_id = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        return self._report_from_row(row) if row else None

    def list_reports(self, project_id: str) -> list[ResearchReport]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM research_reports
                WHERE project_id = ?
                ORDER BY version ASC
                """,
                (project_id,),
            ).fetchall()
        return [self._report_from_row(row) for row in rows]

    def _report_from_row(self, row: sqlite3.Row) -> ResearchReport:
        return ResearchReport(
            report_id=row["report_id"],
            project_id=row["project_id"],
            version=int(row["version"]),
            title=row["title"],
            body_markdown=row["body_markdown"],
            body_html=row["body_html"],
            evidence_ids=list(_json_loads(row["evidence_ids_json"], [])),
            source_ids=list(_json_loads(row["source_ids_json"], [])),
            model_profile=_json_loads(row["model_profile_json"], {}),
            generation_trace=_json_loads(row["generation_trace_json"], {}),
            created_at=row["created_at"],
        )

    # --- runs / workers -----------------------------------------------------

    def create_run(self, run: ResearchRun) -> ResearchRun:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO research_runs(
                    run_id, project_id, status, execution_mode, workers, rounds_per_worker,
                    phase, completed_worker_rounds, total_worker_rounds, progress_pct,
                    analysis_mode, error, started_at, finished_at, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run.run_id,
                    run.project_id,
                    run.status.value,
                    run.execution_mode.value,
                    run.workers,
                    run.rounds_per_worker,
                    run.phase.value,
                    run.completed_worker_rounds,
                    run.total_worker_rounds,
                    float(run.progress_pct),
                    run.analysis_mode.value,
                    run.error,
                    run.started_at,
                    run.finished_at,
                    run.created_at,
                    run.updated_at,
                ),
            )
        return run

    def save_run(self, run: ResearchRun) -> ResearchRun:
        run.updated_at = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                UPDATE research_runs SET
                    status=?, execution_mode=?, workers=?, rounds_per_worker=?,
                    phase=?, completed_worker_rounds=?, total_worker_rounds=?,
                    progress_pct=?, analysis_mode=?, error=?, started_at=?,
                    finished_at=?, updated_at=?
                WHERE run_id=?
                """,
                (
                    run.status.value,
                    run.execution_mode.value,
                    run.workers,
                    run.rounds_per_worker,
                    run.phase.value,
                    run.completed_worker_rounds,
                    run.total_worker_rounds,
                    float(run.progress_pct),
                    run.analysis_mode.value,
                    run.error,
                    run.started_at,
                    run.finished_at,
                    run.updated_at,
                    run.run_id,
                ),
            )
        return run

    def get_run(self, run_id: str) -> ResearchRun | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM research_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return self._run_from_row(row) if row else None

    def get_latest_run(self, project_id: str) -> ResearchRun | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT * FROM research_runs
                WHERE project_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        return self._run_from_row(row) if row else None

    def _run_from_row(self, row: sqlite3.Row) -> ResearchRun:
        return ResearchRun(
            run_id=row["run_id"],
            project_id=row["project_id"],
            status=ResearchStatus(row["status"]),
            execution_mode=ResearchExecutionMode(row["execution_mode"]),
            workers=int(row["workers"]),
            rounds_per_worker=int(row["rounds_per_worker"]),
            phase=ResearchPhase(row["phase"] or ResearchPhase.IDLE.value),
            completed_worker_rounds=int(row["completed_worker_rounds"] or 0),
            total_worker_rounds=int(row["total_worker_rounds"] or 0),
            progress_pct=float(row["progress_pct"] or 0),
            analysis_mode=AnalysisMode(
                row["analysis_mode"] or AnalysisMode.DETERMINISTIC_FALLBACK.value
            ),
            error=row["error"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert_worker(self, worker: ResearchWorker) -> ResearchWorker:
        worker.updated_at = utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            existing = conn.execute(
                "SELECT worker_id FROM research_workers WHERE worker_id = ?",
                (worker.worker_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE research_workers SET
                        status=?, phase=?, current_round=?, total_rounds=?,
                        completed_rounds=?, current_query=?, current_task=?,
                        sources_added=?, evidence_added=?, started_at=?,
                        heartbeat_at=?, finished_at=?, last_error=?, updated_at=?
                    WHERE worker_id=?
                    """,
                    (
                        worker.status.value,
                        worker.phase,
                        worker.current_round,
                        worker.total_rounds,
                        worker.completed_rounds,
                        worker.current_query,
                        worker.current_task,
                        worker.sources_added,
                        worker.evidence_added,
                        worker.started_at,
                        worker.heartbeat_at,
                        worker.finished_at,
                        worker.last_error,
                        worker.updated_at,
                        worker.worker_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO research_workers(
                        worker_id, project_id, run_id, worker_index, status, phase,
                        current_round, total_rounds, completed_rounds, current_query,
                        current_task, sources_added, evidence_added, started_at,
                        heartbeat_at, finished_at, last_error, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        worker.worker_id,
                        worker.project_id,
                        worker.run_id,
                        worker.worker_index,
                        worker.status.value,
                        worker.phase,
                        worker.current_round,
                        worker.total_rounds,
                        worker.completed_rounds,
                        worker.current_query,
                        worker.current_task,
                        worker.sources_added,
                        worker.evidence_added,
                        worker.started_at,
                        worker.heartbeat_at,
                        worker.finished_at,
                        worker.last_error,
                        worker.created_at,
                        worker.updated_at,
                    ),
                )
        return worker

    def list_workers(
        self,
        project_id: str,
        *,
        run_id: str | None = None,
    ) -> list[ResearchWorker]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            return self._list_workers_conn(conn, project_id, run_id=run_id)

    def _list_workers_conn(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        *,
        run_id: str | None = None,
    ) -> list[ResearchWorker]:
        if run_id:
            rows = conn.execute(
                """
                SELECT * FROM research_workers
                WHERE project_id = ? AND run_id = ?
                ORDER BY worker_index ASC
                """,
                (project_id, run_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM research_workers
                WHERE project_id = ?
                ORDER BY updated_at DESC, worker_index ASC
                """,
                (project_id,),
            ).fetchall()
        return [self._worker_from_row(row) for row in rows]

    def _worker_from_row(self, row: sqlite3.Row) -> ResearchWorker:
        return ResearchWorker(
            worker_id=row["worker_id"],
            project_id=row["project_id"],
            run_id=row["run_id"],
            worker_index=int(row["worker_index"]),
            status=WorkerStatus(row["status"]),
            phase=row["phase"] or "",
            current_round=int(row["current_round"] or 0),
            total_rounds=int(row["total_rounds"] or 1),
            completed_rounds=int(row["completed_rounds"] or 0),
            current_query=row["current_query"],
            current_task=row["current_task"],
            sources_added=int(row["sources_added"] or 0),
            evidence_added=int(row["evidence_added"] or 0),
            started_at=row["started_at"],
            heartbeat_at=row["heartbeat_at"],
            finished_at=row["finished_at"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

