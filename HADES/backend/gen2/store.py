"""Gen2 SQLite persistence (additive migrations on the shared HADES DB; latest v14)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def clamp_list_limit(limit: int, *, default: int = 50, maximum: int = 200) -> int:
    """SQLite list discipline: always bound page size (K8 large-corpus hygiene)."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _record_gen2_migration(db: sqlite3.Connection, version: int, now: str) -> None:
    """Record Gen2 migration progress without being masked by platform integer IDs.

    Shared ``schema_migrations`` remains for compatibility, but colliding platform
    versions (8/10/11) can claim those integers first. Gen2 therefore also writes
    a subsystem ledger and re-applies when its tables are still missing.
    """
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gen2_schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        "INSERT OR IGNORE INTO gen2_schema_migrations(version, applied_at) VALUES(?, ?)",
        (int(version), now),
    )
    db.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
        (int(version), now),
    )

class Gen2Store:
    """Owns Gen2 tables on the shared SQLite file used by Database/PlatformDatabase."""

    def __init__(self, path: str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 8000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self) -> None:
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )"""
            )
            applied = {
                int(row["version"])
                for row in db.execute("SELECT version FROM schema_migrations").fetchall()
            }
            if 7 not in applied:
                db.executescript(
                    """
                CREATE TABLE IF NOT EXISTS gen2_eval_runs (
                    id TEXT PRIMARY KEY,
                    suite TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'deterministic',
                    model_id TEXT,
                    status TEXT NOT NULL DEFAULT 'completed',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    scores_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_gen2_eval_runs_created ON gen2_eval_runs(created_at DESC);

                CREATE TABLE IF NOT EXISTS gen2_model_matrix (
                    model_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    score REAL NOT NULL,
                    samples INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(model_id, task_type, metric)
                );

                CREATE TABLE IF NOT EXISTS gen2_run_events (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    input_hash TEXT,
                    output_hash TEXT,
                    parent_event_id TEXT,
                    model_id TEXT,
                    component TEXT,
                    UNIQUE(run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_gen2_run_events_run ON gen2_run_events(run_id, sequence);

                CREATE TABLE IF NOT EXISTS gen2_context_packs (
                    id TEXT PRIMARY KEY,
                    run_id TEXT,
                    goal TEXT NOT NULL DEFAULT '',
                    tokenizer TEXT NOT NULL DEFAULT 'approx_chars_4',
                    max_tokens INTEGER NOT NULL,
                    used_tokens INTEGER NOT NULL,
                    kept_json TEXT NOT NULL DEFAULT '[]',
                    dropped_json TEXT NOT NULL DEFAULT '[]',
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gen2_missions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    ir_json TEXT NOT NULL DEFAULT '{}',
                    task_id TEXT,
                    acceptance_json TEXT NOT NULL DEFAULT '[]',
                    budgets_json TEXT NOT NULL DEFAULT '{}',
                    gates_json TEXT NOT NULL DEFAULT '[]',
                    verification_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_gen2_missions_status ON gen2_missions(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS gen2_committee_sessions (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT 'research',
                    status TEXT NOT NULL DEFAULT 'completed',
                    positions_json TEXT NOT NULL DEFAULT '[]',
                    consensus_json TEXT NOT NULL DEFAULT '{}',
                    run_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gen2_skill_candidates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    definition_json TEXT NOT NULL DEFAULT '{}',
                    benchmark_json TEXT NOT NULL DEFAULT '{}',
                    failure_modes_json TEXT NOT NULL DEFAULT '[]',
                    version INTEGER NOT NULL DEFAULT 1,
                    promoted_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gen2_capability_envelopes (
                    plugin_id TEXT PRIMARY KEY,
                    tier INTEGER NOT NULL DEFAULT 1,
                    envelope_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gen2_graph_edges (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    relation_kind TEXT NOT NULL DEFAULT 'related_to',
                    valid_from TEXT,
                    valid_until TEXT,
                    observed_at TEXT NOT NULL,
                    source_ref TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    provenance TEXT NOT NULL DEFAULT '',
                    supersedes TEXT,
                    contradicts TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_gen2_graph_edges_nodes ON gen2_graph_edges(source_id, target_id);
                CREATE INDEX IF NOT EXISTS idx_gen2_graph_edges_time ON gen2_graph_edges(observed_at);

                CREATE TABLE IF NOT EXISTS gen2_market_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    entities_json TEXT NOT NULL DEFAULT '[]',
                    affected_json TEXT NOT NULL DEFAULT '[]',
                    source_count INTEGER NOT NULL DEFAULT 1,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    novelty REAL NOT NULL DEFAULT 0.5,
                    first_seen TEXT NOT NULL,
                    likely_horizon TEXT NOT NULL DEFAULT 'unknown',
                    analogues_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_gen2_market_events_type ON gen2_market_events(event_type, first_seen DESC);

                CREATE TABLE IF NOT EXISTS gen2_compute_nodes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'local',
                    status TEXT NOT NULL DEFAULT 'online',
                    capabilities_json TEXT NOT NULL DEFAULT '{}',
                    load_json TEXT NOT NULL DEFAULT '{}',
                    last_heartbeat TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gen2_remote_jobs (
                    id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    mission_id TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
                )
                db.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(7, ?)",
                    (now,),
                )
            if 8 not in applied or not _table_exists(db, "gen2_mission_executions"):
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS gen2_mission_executions (
                        id TEXT PRIMARY KEY,
                        mission_id TEXT NOT NULL,
                        task_id TEXT,
                        status TEXT NOT NULL DEFAULT 'queued',
                        error TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_gen2_mission_executions_mission
                        ON gen2_mission_executions(mission_id, created_at DESC);
                    """
                )
                # Additive columns on missions (SQLite: ignore if already present).
                cols = {row[1] for row in db.execute("PRAGMA table_info(gen2_missions)").fetchall()}
                if "execution_id" not in cols:
                    db.execute("ALTER TABLE gen2_missions ADD COLUMN execution_id TEXT")
                if "executions_json" not in cols:
                    db.execute(
                        "ALTER TABLE gen2_missions ADD COLUMN executions_json TEXT NOT NULL DEFAULT '[]'"
                    )
                _record_gen2_migration(db, 8, now)
            if 9 not in applied:
                cols = {row[1] for row in db.execute("PRAGMA table_info(gen2_market_events)").fetchall()}
                if "content_hash" not in cols:
                    db.execute("ALTER TABLE gen2_market_events ADD COLUMN content_hash TEXT")
                db.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_gen2_market_events_hash "
                    "ON gen2_market_events(content_hash) WHERE content_hash IS NOT NULL"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_gen2_missions_task ON gen2_missions(task_id)"
                )
                db.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(9, ?)",
                    (now,),
                )
            if 10 not in applied or not _table_exists(db, "gen2_workflows"):
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS gen2_workflows (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'draft',
                        definition_json TEXT NOT NULL DEFAULT '{}',
                        metrics_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_gen2_workflows_status
                        ON gen2_workflows(status, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS gen2_workflow_revisions (
                        id TEXT PRIMARY KEY,
                        workflow_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        definition_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        note TEXT NOT NULL DEFAULT '',
                        UNIQUE(workflow_id, version)
                    );
                    CREATE INDEX IF NOT EXISTS idx_gen2_workflow_revisions_wf
                        ON gen2_workflow_revisions(workflow_id, version DESC);

                    CREATE TABLE IF NOT EXISTS gen2_workflow_runs (
                        id TEXT PRIMARY KEY,
                        workflow_id TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        mode TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'completed',
                        result_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_gen2_workflow_runs_wf
                        ON gen2_workflow_runs(workflow_id, created_at DESC);
                    """
                )
                _record_gen2_migration(db, 10, now)
            if 11 not in applied or not _table_exists(db, "gen2_jit_grants"):
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS gen2_jit_grants (
                        id TEXT PRIMARY KEY,
                        plugin_id TEXT NOT NULL,
                        profile_id TEXT NOT NULL,
                        capability TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'active',
                        reason TEXT,
                        granted_at TEXT NOT NULL,
                        expires_at TEXT,
                        revoked_at TEXT,
                        revoke_reason TEXT,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_gen2_jit_grants_plugin
                        ON gen2_jit_grants(plugin_id, status, created_at DESC);
                    CREATE TABLE IF NOT EXISTS gen2_plugin_integrity (
                        plugin_id TEXT PRIMARY KEY,
                        content_hash TEXT NOT NULL,
                        source_path TEXT,
                        scan_json TEXT NOT NULL DEFAULT '{}',
                        verified_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                _record_gen2_migration(db, 11, now)
            if 12 not in applied:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS gen2_mission_revisions (
                        id TEXT PRIMARY KEY,
                        mission_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        cause TEXT NOT NULL DEFAULT 'snapshot',
                        snapshot_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        note TEXT NOT NULL DEFAULT '',
                        UNIQUE(mission_id, version)
                    );
                    CREATE INDEX IF NOT EXISTS idx_gen2_mission_revisions_msn
                        ON gen2_mission_revisions(mission_id, version DESC);
                    """
                )
                db.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(12, ?)",
                    (now,),
                )
            if 13 not in applied:
                # Provenance-aware model matrix. Legacy rows are copied with
                # quality_layer='legacy_unprovenanced' and excluded from recommendations.
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS gen2_model_matrix_v2 (
                        model_id TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        metric TEXT NOT NULL,
                        quality_layer TEXT NOT NULL DEFAULT 'unknown',
                        suite TEXT NOT NULL DEFAULT '',
                        mode TEXT NOT NULL DEFAULT '',
                        config_hash TEXT NOT NULL DEFAULT '',
                        score REAL,
                        samples INTEGER NOT NULL DEFAULT 1,
                        reliable INTEGER NOT NULL DEFAULT 0,
                        provenance_json TEXT NOT NULL DEFAULT '{}',
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(model_id, task_type, metric, quality_layer, suite, mode, config_hash)
                    );
                    CREATE INDEX IF NOT EXISTS idx_gen2_model_matrix_v2_lookup
                        ON gen2_model_matrix_v2(task_type, metric, quality_layer, reliable);
                    """
                )
                # Preserve legacy history for inspection without promoting it.
                try:
                    legacy = db.execute("SELECT * FROM gen2_model_matrix").fetchall()
                except Exception:
                    legacy = []
                for row in legacy:
                    db.execute(
                        """INSERT OR IGNORE INTO gen2_model_matrix_v2(
                            model_id,task_type,metric,quality_layer,suite,mode,config_hash,
                            score,samples,reliable,provenance_json,updated_at
                           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            row["model_id"],
                            row["task_type"],
                            row["metric"],
                            "legacy_unprovenanced",
                            "",
                            "",
                            "",
                            row["score"],
                            row["samples"],
                            0,
                            '{"migrated_from":"gen2_model_matrix","promoted":false}',
                            row["updated_at"],
                        ),
                    )
                db.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(13, ?)",
                    (now,),
                )
            if 14 not in applied:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS gen2_human_usability_ratings (
                        id TEXT PRIMARY KEY,
                        eval_run_id TEXT,
                        task_id TEXT,
                        coding_job_id TEXT,
                        artifact_version TEXT NOT NULL DEFAULT '',
                        model_config_json TEXT NOT NULL DEFAULT '{}',
                        rating TEXT NOT NULL,
                        correction_notes TEXT NOT NULL DEFAULT '',
                        correction_seconds REAL,
                        primary_error TEXT NOT NULL DEFAULT '',
                        original_result_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_gen2_human_ratings_run
                        ON gen2_human_usability_ratings(eval_run_id, created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_gen2_human_ratings_task
                        ON gen2_human_usability_ratings(task_id, created_at DESC);
                    """
                )
                db.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(14, ?)",
                    (now,),
                )

    @staticmethod
    def _json_load(raw: str | None, fallback: Any) -> Any:
        try:
            return json.loads(raw or "")
        except Exception:
            return fallback

    @staticmethod
    def _json_dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    # --- eval ---
    def save_eval_run(
        self,
        *,
        suite: str,
        mode: str,
        model_id: str | None,
        summary: dict[str, Any],
        scores: list[dict[str, Any]],
        status: str = "completed",
    ) -> dict[str, Any]:
        run_id = new_id("eval")
        now = utc_now()
        quality_layer_summary = str(
            summary.get("quality_layer")
            or (scores[0].get("quality_layer") if scores else "")
            or "unknown"
        )
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_eval_runs(id,suite,mode,model_id,status,summary_json,scores_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (run_id, suite, mode, model_id, status, self._json_dump(summary), self._json_dump(scores), now),
            )
            for score in scores:
                model = str(score.get("model_id") or model_id or "local")
                task_type = str(score.get("task_type") or score.get("scenario_id") or "general")
                quality_layer = str(
                    score.get("quality_layer")
                    or summary.get("quality_layer")
                    or "unknown"
                )
                config_hash = str(
                    score.get("config_hash")
                    or summary.get("config_hash")
                    or score.get("model_config_hash")
                    or ""
                )
                # Smoke / synthetic / software suites never promote into routing recommendations.
                not_model_quality = bool(
                    score.get("not_model_quality")
                    or summary.get("not_model_quality")
                    or quality_layer in {"infrastructure_smoke", "software", "legacy_unprovenanced"}
                    or str(model).startswith("software:")
                    or mode in {"deterministic_software", "honesty", "holdout_honesty"}
                )
                reliable = 0 if not_model_quality else 1
                # Minimum samples for promotion handled at read time; store raw honestly.
                metrics = score.get("metrics") or {"pass": 1.0 if score.get("passed") else 0.0}
                for metric, value in metrics.items():
                    if metric in {"metric_reasons", "tokens_estimate"}:
                        continue
                    if value is None:
                        # Persist null-ish as omission from matrix (keep in scores_json only).
                        continue
                    try:
                        numeric = float(value)
                    except Exception:
                        continue
                    provenance = {
                        "suite": suite,
                        "mode": mode,
                        "quality_layer": quality_layer,
                        "not_model_quality": not_model_quality,
                        "eval_run_id": run_id,
                        "scenario_id": score.get("scenario_id"),
                        "metric_reasons": (metrics.get("metric_reasons") if isinstance(metrics, dict) else None),
                    }
                    db.execute(
                        """INSERT INTO gen2_model_matrix_v2(
                              model_id,task_type,metric,quality_layer,suite,mode,config_hash,
                              score,samples,reliable,provenance_json,updated_at
                           ) VALUES(?,?,?,?,?,?,?,?,1,?,?,?)
                           ON CONFLICT(model_id,task_type,metric,quality_layer,suite,mode,config_hash)
                           DO UPDATE SET
                             score=CASE
                               WHEN excluded.score IS NULL THEN gen2_model_matrix_v2.score
                               ELSE ((COALESCE(gen2_model_matrix_v2.score,0)*gen2_model_matrix_v2.samples)+excluded.score)
                                    /(gen2_model_matrix_v2.samples+1)
                             END,
                             samples=gen2_model_matrix_v2.samples+1,
                             reliable=MIN(gen2_model_matrix_v2.reliable, excluded.reliable),
                             provenance_json=excluded.provenance_json,
                             updated_at=excluded.updated_at""",
                        (
                            model,
                            task_type,
                            str(metric),
                            quality_layer,
                            suite,
                            mode,
                            config_hash,
                            numeric,
                            reliable,
                            self._json_dump(provenance),
                            now,
                        ),
                    )
                    # Keep legacy table for old readers, but mark smoke with a non-routable prefix
                    # when not_model_quality so old best_model_for software filter helps.
                    legacy_model = model if reliable else (
                        model if str(model).startswith("software:") else f"software:smoke:{model}"
                    )
                    db.execute(
                        """INSERT INTO gen2_model_matrix(model_id,task_type,metric,score,samples,updated_at)
                           VALUES(?,?,?,?,1,?)
                           ON CONFLICT(model_id,task_type,metric) DO UPDATE SET
                             score=((score*samples)+excluded.score)/(samples+1),
                             samples=samples+1,
                             updated_at=excluded.updated_at""",
                        (legacy_model, task_type, str(metric), numeric, now),
                    )
        return self.get_eval_run(run_id) or {"id": run_id, "quality_layer": quality_layer_summary}

    def get_eval_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_eval_runs WHERE id=?", (run_id,)).fetchone()
        return self._eval_row(row) if row else None

    def list_eval_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit)
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM gen2_eval_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._eval_row(row) for row in rows]

    def list_eval_runs_for_suite(
        self,
        *,
        suite: str,
        mode: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Additive helper: newest-first runs filtered by suite and optional mode."""
        limit = clamp_list_limit(limit)
        with self.connection() as db:
            if mode:
                rows = db.execute(
                    """SELECT * FROM gen2_eval_runs
                       WHERE suite=? AND mode=?
                       ORDER BY created_at DESC LIMIT ?""",
                    (suite, mode, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT * FROM gen2_eval_runs
                       WHERE suite=?
                       ORDER BY created_at DESC LIMIT ?""",
                    (suite, limit),
                ).fetchall()
        return [self._eval_row(row) for row in rows]

    def _eval_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "suite": row["suite"],
            "mode": row["mode"],
            "model_id": row["model_id"],
            "status": row["status"],
            "summary": self._json_load(row["summary_json"], {}),
            "scores": self._json_load(row["scores_json"], []),
            "created_at": row["created_at"],
        }

    def save_human_usability_rating(
        self,
        *,
        rating: str,
        eval_run_id: str | None = None,
        task_id: str | None = None,
        coding_job_id: str | None = None,
        artifact_version: str = "",
        model_config: dict[str, Any] | None = None,
        correction_notes: str = "",
        correction_seconds: float | None = None,
        primary_error: str = "",
        original_result: dict[str, Any] | None = None,
        timer_opt_in: bool = False,
    ) -> dict[str, Any]:
        """Compact human usability rating. Active correction time only when explicitly provided or timer opt-in."""
        allowed = {
            "directly_usable",
            "usable_after_small_correction",
            "needs_major_correction",
            "unusable",
        }
        rating_norm = (rating or "").strip().lower()
        if rating_norm not in allowed:
            raise ValueError(f"rating must be one of {sorted(allowed)}")
        if correction_seconds is not None and not timer_opt_in and correction_seconds < 0:
            raise ValueError("correction_seconds must be >= 0")
        # Never infer active work time from open windows — only store explicit values.
        stored_seconds = float(correction_seconds) if correction_seconds is not None else None
        if stored_seconds is not None and not timer_opt_in:
            # Explicit manual entry is allowed without timer; document source.
            pass
        rid = new_id("hrate")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_human_usability_ratings(
                    id, eval_run_id, task_id, coding_job_id, artifact_version,
                    model_config_json, rating, correction_notes, correction_seconds,
                    primary_error, original_result_json, created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rid,
                    eval_run_id,
                    task_id,
                    coding_job_id,
                    artifact_version or "",
                    self._json_dump(model_config or {}),
                    rating_norm,
                    correction_notes or "",
                    stored_seconds,
                    primary_error or "",
                    self._json_dump(original_result or {}),
                    now,
                ),
            )
        return self.get_human_usability_rating(rid) or {"id": rid, "rating": rating_norm}

    def get_human_usability_rating(self, rating_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM gen2_human_usability_ratings WHERE id=?",
                (rating_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "eval_run_id": row["eval_run_id"],
            "task_id": row["task_id"],
            "coding_job_id": row["coding_job_id"],
            "artifact_version": row["artifact_version"],
            "model_config": self._json_load(row["model_config_json"], {}),
            "rating": row["rating"],
            "correction_notes": row["correction_notes"],
            "correction_seconds": row["correction_seconds"],
            "primary_error": row["primary_error"],
            "original_result": self._json_load(row["original_result_json"], {}),
            "created_at": row["created_at"],
            "active_time_source": "explicit_or_opt_in_timer",
        }

    def list_human_usability_ratings(
        self,
        *,
        eval_run_id: str | None = None,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit)
        with self.connection() as db:
            if eval_run_id:
                rows = db.execute(
                    """SELECT * FROM gen2_human_usability_ratings
                       WHERE eval_run_id=? ORDER BY created_at DESC LIMIT ?""",
                    (eval_run_id, limit),
                ).fetchall()
            elif task_id:
                rows = db.execute(
                    """SELECT * FROM gen2_human_usability_ratings
                       WHERE task_id=? ORDER BY created_at DESC LIMIT ?""",
                    (task_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT * FROM gen2_human_usability_ratings
                       ORDER BY created_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        out = []
        for row in rows:
            out.append(
                {
                    "id": row["id"],
                    "eval_run_id": row["eval_run_id"],
                    "task_id": row["task_id"],
                    "coding_job_id": row["coding_job_id"],
                    "artifact_version": row["artifact_version"],
                    "rating": row["rating"],
                    "correction_seconds": row["correction_seconds"],
                    "primary_error": row["primary_error"],
                    "created_at": row["created_at"],
                }
            )
        return out

    def human_usability_trends(self, *, limit: int = 200) -> dict[str, Any]:
        rows = self.list_human_usability_ratings(limit=limit)
        counts: dict[str, int] = {}
        measured_seconds: list[float] = []
        for row in rows:
            r = str(row.get("rating") or "")
            counts[r] = counts.get(r, 0) + 1
            if row.get("correction_seconds") is not None:
                measured_seconds.append(float(row["correction_seconds"]))
        return {
            "samples": len(rows),
            "rating_counts": counts,
            "measured_correction_samples": len(measured_seconds),
            "mean_correction_seconds": (
                round(sum(measured_seconds) / len(measured_seconds), 2) if measured_seconds else None
            ),
            "note": (
                "Unmeasured human time remains unknown — never inferred from open windows. "
                "mean_correction_seconds only uses explicit/opt-in timer values."
            ),
        }


    def capability_matrix(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            try:
                rows = db.execute(
                    """SELECT * FROM gen2_model_matrix_v2
                       ORDER BY model_id, task_type, metric, quality_layer, suite"""
                ).fetchall()
                return [
                    {
                        "model_id": row["model_id"],
                        "task_type": row["task_type"],
                        "metric": row["metric"],
                        "score": row["score"],
                        "samples": row["samples"],
                        "updated_at": row["updated_at"],
                        "quality_layer": row["quality_layer"],
                        "suite": row["suite"],
                        "mode": row["mode"],
                        "config_hash": row["config_hash"],
                        "reliable": bool(row["reliable"]),
                        "provenance": self._json_load(row["provenance_json"], {}),
                    }
                    for row in rows
                ]
            except Exception:
                rows = db.execute(
                    "SELECT * FROM gen2_model_matrix ORDER BY model_id, task_type, metric"
                ).fetchall()
                return [
                    {
                        "model_id": row["model_id"],
                        "task_type": row["task_type"],
                        "metric": row["metric"],
                        "score": row["score"],
                        "samples": row["samples"],
                        "updated_at": row["updated_at"],
                        "quality_layer": "legacy_unprovenanced",
                        "reliable": False,
                    }
                    for row in rows
                ]

    def best_model_for(
        self,
        task_type: str,
        metric: str = "pass",
        *,
        min_samples: int = 3,
        quality_layers: list[str] | None = None,
        allow_unreliable: bool = False,
    ) -> dict[str, Any] | None:
        """Recommend from comparable quality runs only.

        Excludes infrastructure_smoke, software, and legacy_unprovenanced by default.
        A score never invents availability — callers still check the provider.
        """
        lower_better = {
            "latency_ms",
            "latency",
            "verification_failures",
            "error_rate",
            "tokens",
            "cost",
            "hallucination_proxy",
            "replan_count",
            "retries",
            "replanning_rate",
        }
        order = "ASC" if metric in lower_better else "DESC"
        allowed_layers = quality_layers or [
            "model_answer",
            "agent_task",
            "agent_task+model",
            "live_quality",
        ]
        placeholders = ",".join("?" for _ in allowed_layers)
        with self.connection() as db:
            try:
                row = db.execute(
                    f"""SELECT * FROM gen2_model_matrix_v2
                       WHERE task_type=? AND metric=?
                         AND reliable=1
                         AND samples>=?
                         AND quality_layer IN ({placeholders})
                         AND model_id NOT LIKE 'software:%'
                         AND score IS NOT NULL
                       ORDER BY score {order}, samples DESC LIMIT 1""",
                    (task_type, metric, int(min_samples), *allowed_layers),
                ).fetchone()
            except Exception:
                row = None
        if not row and allow_unreliable:
            with self.connection() as db:
                row = db.execute(
                    f"""SELECT * FROM gen2_model_matrix
                       WHERE task_type=? AND metric=?
                         AND model_id NOT LIKE 'software:%'
                       ORDER BY score {order}, samples DESC LIMIT 1""",
                    (task_type, metric),
                ).fetchone()
                if row:
                    return {
                        "model_id": row["model_id"],
                        "task_type": row["task_type"],
                        "metric": row["metric"],
                        "score": row["score"],
                        "samples": row["samples"],
                        "updated_at": row["updated_at"],
                        "source": "empirical_matrix_unreliable_legacy",
                        "sort": "lower_better" if metric in lower_better else "higher_better",
                        "software_only": str(row["model_id"]).startswith("software:"),
                        "reliable": False,
                        "note": "Legacy matrix row; not provenance-filtered.",
                    }
        if not row:
            return None
        return {
            "model_id": row["model_id"],
            "task_type": row["task_type"],
            "metric": row["metric"],
            "score": row["score"],
            "samples": row["samples"],
            "updated_at": row["updated_at"],
            "quality_layer": row["quality_layer"] if "quality_layer" in row.keys() else None,
            "suite": row["suite"] if "suite" in row.keys() else None,
            "mode": row["mode"] if "mode" in row.keys() else None,
            "config_hash": row["config_hash"] if "config_hash" in row.keys() else None,
            "reliable": bool(row["reliable"]) if "reliable" in row.keys() else True,
            "source": "empirical_matrix",
            "sort": "lower_better" if metric in lower_better else "higher_better",
            "software_only": str(row["model_id"]).startswith("software:"),
            "min_samples": int(min_samples),
            "note": "Recommendation from comparable quality-layer runs only; smoke excluded.",
        }

    def best_software_model_for(
        self,
        task_type: str,
        metric: str = "pass",
        *,
        min_samples: int = 1,
    ) -> dict[str, Any] | None:
        """Return labeled software-suite scores only — never live model quality.

        Used by ``recommend_model`` as an honest fallback when Eval Lab has run
        deterministic suites but no comparable live-quality matrix rows exist.
        """
        lower_better = {
            "latency_ms",
            "latency",
            "verification_failures",
            "error_rate",
            "tokens",
            "cost",
            "hallucination_proxy",
            "replan_count",
            "retries",
            "replanning_rate",
        }
        order = "ASC" if metric in lower_better else "DESC"
        with self.connection() as db:
            try:
                row = db.execute(
                    f"""SELECT * FROM gen2_model_matrix_v2
                       WHERE task_type=? AND metric=?
                         AND samples>=?
                         AND (
                           quality_layer='software'
                           OR model_id LIKE 'software:%'
                         )
                         AND score IS NOT NULL
                       ORDER BY score {order}, samples DESC LIMIT 1""",
                    (task_type, metric, int(min_samples)),
                ).fetchone()
            except Exception:
                row = db.execute(
                    f"""SELECT * FROM gen2_model_matrix
                       WHERE task_type=? AND metric=?
                         AND model_id LIKE 'software:%'
                       ORDER BY score {order}, samples DESC LIMIT 1""",
                    (task_type, metric),
                ).fetchone()
        if not row:
            return None
        return {
            "model_id": row["model_id"],
            "task_type": row["task_type"],
            "metric": row["metric"],
            "score": row["score"],
            "samples": row["samples"],
            "updated_at": row["updated_at"],
            "quality_layer": row["quality_layer"] if "quality_layer" in row.keys() else "software",
            "suite": row["suite"] if "suite" in row.keys() else None,
            "mode": row["mode"] if "mode" in row.keys() else None,
            "reliable": False,
            "source": "software_suite_fallback",
            "sort": "lower_better" if metric in lower_better else "higher_better",
            "software_only": True,
            "min_samples": int(min_samples),
            "note": "Only deterministic software-suite scores available; not live model quality.",
        }

    # --- flight recorder ---
    def append_run_event(
        self,
        *,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        sequence: int | None = None,
        input_hash: str | None = None,
        output_hash: str | None = None,
        parent_event_id: str | None = None,
        model_id: str | None = None,
        component: str | None = None,
        event_id: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        eid = event_id or new_id("re")
        ts = timestamp or utc_now()
        with self.connection() as db:
            if sequence is None:
                row = db.execute(
                    "SELECT COALESCE(MAX(sequence), 0) AS m FROM gen2_run_events WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                sequence = int(row["m"]) + 1
            db.execute(
                """INSERT INTO gen2_run_events
                   (id,run_id,sequence,event_type,timestamp,payload_json,input_hash,output_hash,parent_event_id,model_id,component)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    eid,
                    run_id,
                    sequence,
                    event_type,
                    ts,
                    self._json_dump(payload or {}),
                    input_hash,
                    output_hash,
                    parent_event_id,
                    model_id,
                    component,
                ),
            )
        return {
            "id": eid,
            "run_id": run_id,
            "sequence": sequence,
            "event_type": event_type,
            "timestamp": ts,
            "payload": payload or {},
            "input_hash": input_hash,
            "output_hash": output_hash,
            "parent_event_id": parent_event_id,
            "model_id": model_id,
            "component": component,
        }

    def list_run_events(self, run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT * FROM gen2_run_events
                   WHERE run_id=? AND sequence>?
                   ORDER BY sequence ASC""",
                (run_id, after_sequence),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "timestamp": row["timestamp"],
                "payload": self._json_load(row["payload_json"], {}),
                "input_hash": row["input_hash"],
                "output_hash": row["output_hash"],
                "parent_event_id": row["parent_event_id"],
                "model_id": row["model_id"],
                "component": row["component"],
            }
            for row in rows
        ]

    def save_context_pack(self, pack: dict[str, Any]) -> dict[str, Any]:
        pack_id = pack.get("id") or new_id("ctx")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_context_packs
                   (id,run_id,goal,tokenizer,max_tokens,used_tokens,kept_json,dropped_json,metrics_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    pack_id,
                    pack.get("run_id"),
                    pack.get("goal") or "",
                    pack.get("tokenizer") or "approx_chars_4",
                    int(pack.get("max_tokens") or 0),
                    int(pack.get("used_tokens") or 0),
                    self._json_dump(pack.get("kept") or []),
                    self._json_dump(pack.get("dropped") or []),
                    self._json_dump(pack.get("metrics") or {}),
                    now,
                ),
            )
        out = dict(pack)
        out["id"] = pack_id
        out["created_at"] = now
        return out

    def get_context_pack(self, pack_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_context_packs WHERE id=?", (pack_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "goal": row["goal"],
            "tokenizer": row["tokenizer"],
            "max_tokens": row["max_tokens"],
            "used_tokens": row["used_tokens"],
            "kept": self._json_load(row["kept_json"], []),
            "dropped": self._json_load(row["dropped_json"], []),
            "metrics": self._json_load(row["metrics_json"], {}),
            "created_at": row["created_at"],
        }

    # --- missions ---
    def create_mission(self, values: dict[str, Any]) -> dict[str, Any]:
        mission_id = new_id("msn")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_missions
                   (id,title,goal,status,ir_json,task_id,acceptance_json,budgets_json,gates_json,verification_json,error,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,NULL,?,?)""",
                (
                    mission_id,
                    values["title"],
                    values["goal"],
                    values.get("status") or "draft",
                    self._json_dump(values.get("ir") or {}),
                    values.get("task_id"),
                    self._json_dump(values.get("acceptance_criteria") or []),
                    self._json_dump(values.get("budgets") or {}),
                    self._json_dump(values.get("gates") or []),
                    self._json_dump(values.get("verification") or {}),
                    now,
                    now,
                ),
            )
        return self.get_mission(mission_id)  # type: ignore[return-value]

    def update_mission(self, mission_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "title",
            "goal",
            "status",
            "ir",
            "task_id",
            "execution_id",
            "executions",
            "acceptance_criteria",
            "budgets",
            "gates",
            "verification",
            "error",
        }
        mapping = {
            "ir": "ir_json",
            "acceptance_criteria": "acceptance_json",
            "budgets": "budgets_json",
            "gates": "gates_json",
            "verification": "verification_json",
            "executions": "executions_json",
        }
        sets: list[str] = []
        args: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            col = mapping.get(key, key)
            if col.endswith("_json"):
                value = self._json_dump(value)
            sets.append(f"{col}=?")
            args.append(value)
        if not sets:
            return self.get_mission(mission_id)
        sets.append("updated_at=?")
        args.append(utc_now())
        args.append(mission_id)
        with self.connection() as db:
            db.execute(f"UPDATE gen2_missions SET {', '.join(sets)} WHERE id=?", args)
        return self.get_mission(mission_id)

    def claim_mission_start(
        self,
        mission_id: str,
        *,
        expected_statuses: set[str],
        force_new: bool = False,
    ) -> dict[str, Any]:
        """Atomically claim a mission for starting (queued) or return reused/rejected."""
        now = utc_now()
        execution_id = new_id("mexec")
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM gen2_missions WHERE id=?", (mission_id,)).fetchone()
            if not row:
                db.rollback()
                raise ValueError("mission not found")
            current = self._mission_row(row)
            cur_status = str(current.get("status") or "")
            if cur_status in {"running", "dispatched"} and current.get("task_id") and not force_new:
                db.rollback()
                return {**current, "_start_outcome": "reused"}
            if cur_status == "queued" and current.get("execution_id") and not force_new:
                db.rollback()
                # Another starter claimed the mission; waiters must not create a second task.
                if current.get("task_id"):
                    return {**current, "_start_outcome": "reused"}
                return {**current, "_start_outcome": "in_progress"}
            allowed = set(expected_statuses)
            if force_new:
                allowed |= {
                    "failed",
                    "cancelled",
                    "completed",
                    "blocked",
                    "running",
                    "ready",
                    "queued",
                    "dispatched",
                }
            if cur_status not in allowed:
                db.rollback()
                return {
                    **current,
                    "_start_outcome": "rejected",
                    "_reject_reason": f"invalid_transition:{cur_status}->queued",
                }
            executions = list(current.get("executions") or [])
            executions.append(
                {
                    "id": execution_id,
                    "task_id": None,
                    "status": "queued",
                    "error": None,
                    "created_at": now,
                }
            )
            db.execute(
                """INSERT INTO gen2_mission_executions
                   (id, mission_id, task_id, status, error, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (execution_id, mission_id, None, "queued", None, now, now),
            )
            db.execute(
                """UPDATE gen2_missions
                   SET status=?, execution_id=?, executions_json=?, error=NULL, updated_at=?
                   WHERE id=?""",
                ("queued", execution_id, self._json_dump(executions), now, mission_id),
            )
            row2 = db.execute("SELECT * FROM gen2_missions WHERE id=?", (mission_id,)).fetchone()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return {**self._mission_row(row2), "_start_outcome": "claimed", "_execution_id": execution_id}

    def finalize_mission_execution(
        self,
        mission_id: str,
        *,
        execution_id: str,
        task_id: str | None,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_missions WHERE id=?", (mission_id,)).fetchone()
            if not row:
                raise ValueError("mission not found")
            current = self._mission_row(row)
            executions = list(current.get("executions") or [])
            for item in executions:
                if item.get("id") == execution_id:
                    item["task_id"] = task_id
                    item["status"] = status
                    item["error"] = error
                    item["updated_at"] = now
            db.execute(
                """UPDATE gen2_mission_executions
                   SET task_id=?, status=?, error=?, updated_at=? WHERE id=?""",
                (task_id, status, error, now, execution_id),
            )
            db.execute(
                """UPDATE gen2_missions
                   SET status=?, task_id=?, execution_id=?, executions_json=?, error=?, updated_at=?
                   WHERE id=?""",
                (
                    status,
                    task_id,
                    execution_id,
                    self._json_dump(executions),
                    error,
                    now,
                    mission_id,
                ),
            )
        return self.get_mission(mission_id)  # type: ignore[return-value]

    def start_mission_execution(
        self,
        mission_id: str,
        *,
        expected_statuses: set[str],
        task_id: str | None,
        status: str,
        error: str | None = None,
        force_new: bool = False,
    ) -> dict[str, Any]:
        """Compatibility helper: claim + finalize in one shot when task already exists."""
        claimed = self.claim_mission_start(
            mission_id, expected_statuses=expected_statuses, force_new=force_new
        )
        outcome = claimed.get("_start_outcome")
        if outcome in {"reused", "rejected"}:
            return claimed
        execution_id = str(claimed.get("_execution_id") or claimed.get("execution_id"))
        mission = self.finalize_mission_execution(
            mission_id,
            execution_id=execution_id,
            task_id=task_id,
            status=status,
            error=error,
        )
        return {**mission, "_start_outcome": "started"}

    def get_mission_by_task_id(self, task_id: str) -> dict[str, Any] | None:
        if not task_id:
            return None
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM gen2_missions WHERE task_id=? ORDER BY updated_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        return self._mission_row(row) if row else None

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_missions WHERE id=?", (mission_id,)).fetchone()
        return self._mission_row(row) if row else None

    def list_missions(self, limit: int = 50, *, status: str | None = None) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit)
        with self.connection() as db:
            if status:
                rows = db.execute(
                    "SELECT * FROM gen2_missions WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM gen2_missions ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._mission_row(row) for row in rows]

    def save_mission_revision(
        self,
        mission_id: str,
        snapshot: dict[str, Any],
        *,
        cause: str = "snapshot",
        note: str = "",
        version: int | None = None,
    ) -> dict[str, Any]:
        rev_id = new_id("mrev")
        now = utc_now()
        with self.connection() as db:
            if version is None:
                row = db.execute(
                    "SELECT COALESCE(MAX(version), 0) AS m FROM gen2_mission_revisions WHERE mission_id=?",
                    (mission_id,),
                ).fetchone()
                version = int(row["m"]) + 1
            db.execute(
                """INSERT INTO gen2_mission_revisions
                   (id,mission_id,version,cause,snapshot_json,created_at,note)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    rev_id,
                    mission_id,
                    int(version),
                    (cause or "snapshot")[:64],
                    self._json_dump(snapshot),
                    now,
                    (note or "")[:2000],
                ),
            )
        return {
            "id": rev_id,
            "mission_id": mission_id,
            "version": int(version),
            "cause": (cause or "snapshot")[:64],
            "snapshot": snapshot,
            "created_at": now,
            "note": (note or "")[:2000],
        }

    def list_mission_revisions(self, mission_id: str, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit)
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM gen2_mission_revisions WHERE mission_id=? "
                "ORDER BY version DESC LIMIT ?",
                (mission_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "mission_id": row["mission_id"],
                "version": row["version"],
                "cause": row["cause"],
                "snapshot": self._json_load(row["snapshot_json"], {}),
                "created_at": row["created_at"],
                "note": row["note"],
            }
            for row in rows
        ]

    def get_mission_revision(self, mission_id: str, version: int) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM gen2_mission_revisions WHERE mission_id=? AND version=?",
                (mission_id, int(version)),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "mission_id": row["mission_id"],
            "version": row["version"],
            "cause": row["cause"],
            "snapshot": self._json_load(row["snapshot_json"], {}),
            "created_at": row["created_at"],
            "note": row["note"],
        }

    def _mission_row(self, row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        return {
            "id": row["id"],
            "title": row["title"],
            "goal": row["goal"],
            "status": row["status"],
            "ir": self._json_load(row["ir_json"], {}),
            "task_id": row["task_id"],
            "execution_id": row["execution_id"] if "execution_id" in keys else None,
            "executions": self._json_load(row["executions_json"], []) if "executions_json" in keys else [],
            "acceptance_criteria": self._json_load(row["acceptance_json"], []),
            "budgets": self._json_load(row["budgets_json"], {}),
            "gates": self._json_load(row["gates_json"], []),
            "verification": self._json_load(row["verification_json"], {}),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # --- committee ---
    def save_committee(self, values: dict[str, Any]) -> dict[str, Any]:
        session_id = new_id("cms")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_committee_sessions
                   (id,topic,domain,status,positions_json,consensus_json,run_id,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    session_id,
                    values["topic"],
                    values.get("domain") or "research",
                    values.get("status") or "completed",
                    self._json_dump(values.get("positions") or []),
                    self._json_dump(values.get("consensus") or {}),
                    values.get("run_id"),
                    now,
                ),
            )
        return {
            "id": session_id,
            "topic": values["topic"],
            "domain": values.get("domain") or "research",
            "status": values.get("status") or "completed",
            "positions": values.get("positions") or [],
            "consensus": values.get("consensus") or {},
            "run_id": values.get("run_id"),
            "created_at": now,
        }

    def list_committees(self, limit: int = 30) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit, default=30)
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM gen2_committee_sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "topic": row["topic"],
                "domain": row["domain"],
                "status": row["status"],
                "positions": self._json_load(row["positions_json"], []),
                "consensus": self._json_load(row["consensus_json"], {}),
                "run_id": row["run_id"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_committee(self, session_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM gen2_committee_sessions WHERE id=?", (session_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "topic": row["topic"],
            "domain": row["domain"],
            "status": row["status"],
            "positions": self._json_load(row["positions_json"], []),
            "consensus": self._json_load(row["consensus_json"], {}),
            "run_id": row["run_id"],
            "created_at": row["created_at"],
        }

    # --- agent factory ---
    def create_skill_candidate(self, values: dict[str, Any]) -> dict[str, Any]:
        skill_id = new_id("skl")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_skill_candidates
                   (id,name,status,definition_json,benchmark_json,failure_modes_json,version,promoted_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,1,NULL,?,?)""",
                (
                    skill_id,
                    values["name"],
                    values.get("status") or "candidate",
                    self._json_dump(values.get("definition") or {}),
                    self._json_dump(values.get("benchmark") or {}),
                    self._json_dump(values.get("failure_modes") or []),
                    now,
                    now,
                ),
            )
        return self.get_skill(skill_id)  # type: ignore[return-value]

    def update_skill(self, skill_id: str, **fields: Any) -> dict[str, Any] | None:
        mapping = {
            "definition": "definition_json",
            "benchmark": "benchmark_json",
            "failure_modes": "failure_modes_json",
        }
        sets: list[str] = []
        args: list[Any] = []
        for key, value in fields.items():
            if key in {"name", "status", "version", "promoted_at"}:
                sets.append(f"{key}=?")
                args.append(value)
            elif key in mapping:
                sets.append(f"{mapping[key]}=?")
                args.append(self._json_dump(value))
        if not sets:
            return self.get_skill(skill_id)
        sets.append("updated_at=?")
        args.append(utc_now())
        args.append(skill_id)
        with self.connection() as db:
            db.execute(f"UPDATE gen2_skill_candidates SET {', '.join(sets)} WHERE id=?", args)
        return self.get_skill(skill_id)

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_skill_candidates WHERE id=?", (skill_id,)).fetchone()
        return self._skill_row(row) if row else None

    def list_skills(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit)
        with self.connection() as db:
            if status:
                rows = db.execute(
                    "SELECT * FROM gen2_skill_candidates WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM gen2_skill_candidates ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._skill_row(row) for row in rows]

    def _skill_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "definition": self._json_load(row["definition_json"], {}),
            "benchmark": self._json_load(row["benchmark_json"], {}),
            "failure_modes": self._json_load(row["failure_modes_json"], []),
            "version": row["version"],
            "promoted_at": row["promoted_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # --- sandbox ---
    def upsert_envelope(self, plugin_id: str, tier: int, envelope: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_capability_envelopes(plugin_id,tier,envelope_json,updated_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(plugin_id) DO UPDATE SET tier=excluded.tier, envelope_json=excluded.envelope_json, updated_at=excluded.updated_at""",
                (plugin_id, int(tier), self._json_dump(envelope), now),
            )
        return {"plugin_id": plugin_id, "tier": int(tier), "envelope": envelope, "updated_at": now}

    def get_envelope(self, plugin_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM gen2_capability_envelopes WHERE plugin_id=?", (plugin_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "plugin_id": row["plugin_id"],
            "tier": row["tier"],
            "envelope": self._json_load(row["envelope_json"], {}),
            "updated_at": row["updated_at"],
        }

    def list_envelopes(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM gen2_capability_envelopes ORDER BY plugin_id").fetchall()
        return [
            {
                "plugin_id": row["plugin_id"],
                "tier": row["tier"],
                "envelope": self._json_load(row["envelope_json"], {}),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def create_jit_grant(self, values: dict[str, Any]) -> dict[str, Any]:
        grant_id = new_id("jit")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_jit_grants(
                    id,plugin_id,profile_id,capability,status,reason,granted_at,expires_at,
                    revoked_at,revoke_reason,payload_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    grant_id,
                    values["plugin_id"],
                    values["profile_id"],
                    values["capability"],
                    values.get("status") or "active",
                    values.get("reason"),
                    values.get("granted_at") or now,
                    values.get("expires_at"),
                    values.get("revoked_at"),
                    values.get("revoke_reason"),
                    self._json_dump(values.get("payload") or values),
                    now,
                    now,
                ),
            )
        return self.get_jit_grant(grant_id)  # type: ignore[return-value]

    def get_jit_grant(self, grant_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_jit_grants WHERE id=?", (grant_id,)).fetchone()
        return self._jit_row(row) if row else None

    def list_jit_grants(
        self,
        *,
        plugin_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit)
        clauses: list[str] = []
        args: list[Any] = []
        if plugin_id:
            clauses.append("plugin_id=?")
            args.append(plugin_id)
        if status:
            clauses.append("status=?")
            args.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(limit)
        with self.connection() as db:
            rows = db.execute(
                f"SELECT * FROM gen2_jit_grants {where} ORDER BY created_at DESC LIMIT ?",
                args,
            ).fetchall()
        return [self._jit_row(row) for row in rows]

    def revoke_jit_grant(self, grant_id: str, *, reason: str = "") -> dict[str, Any] | None:
        now = utc_now()
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_jit_grants WHERE id=?", (grant_id,)).fetchone()
            if not row:
                return None
            db.execute(
                """UPDATE gen2_jit_grants
                   SET status='revoked', revoked_at=?, revoke_reason=?, updated_at=?
                   WHERE id=?""",
                (now, (reason or "")[:500], now, grant_id),
            )
        return self.get_jit_grant(grant_id)

    def _jit_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "plugin_id": row["plugin_id"],
            "profile_id": row["profile_id"],
            "capability": row["capability"],
            "status": row["status"],
            "reason": row["reason"],
            "granted_at": row["granted_at"],
            "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"],
            "revoke_reason": row["revoke_reason"],
            "payload": self._json_load(row["payload_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def upsert_plugin_integrity(
        self,
        plugin_id: str,
        *,
        content_hash: str,
        source_path: str | None = None,
        scan: dict[str, Any] | None = None,
        verified_at: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_plugin_integrity(
                    plugin_id,content_hash,source_path,scan_json,verified_at,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(plugin_id) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    source_path=excluded.source_path,
                    scan_json=excluded.scan_json,
                    verified_at=COALESCE(excluded.verified_at, gen2_plugin_integrity.verified_at),
                    updated_at=excluded.updated_at""",
                (
                    plugin_id,
                    content_hash,
                    source_path,
                    self._json_dump(scan or {}),
                    verified_at,
                    now,
                    now,
                ),
            )
        return self.get_plugin_integrity(plugin_id)  # type: ignore[return-value]

    def get_plugin_integrity(self, plugin_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM gen2_plugin_integrity WHERE plugin_id=?", (plugin_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "plugin_id": row["plugin_id"],
            "content_hash": row["content_hash"],
            "source_path": row["source_path"],
            "scan": self._json_load(row["scan_json"], {}),
            "verified_at": row["verified_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # --- temporal graph ---
    def add_graph_edge(self, values: dict[str, Any]) -> dict[str, Any]:
        edge_id = new_id("ged")
        now = utc_now()
        observed = values.get("observed_at") or now
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_graph_edges
                   (id,source_id,target_id,relation,relation_kind,valid_from,valid_until,observed_at,
                    source_ref,confidence,provenance,supersedes,contradicts,metadata_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    edge_id,
                    values["source_id"],
                    values["target_id"],
                    values.get("relation") or values.get("relation_kind") or "related_to",
                    values.get("relation_kind") or "related_to",
                    values.get("valid_from"),
                    values.get("valid_until"),
                    observed,
                    values.get("source_ref") or "",
                    float(values.get("confidence") or 0.5),
                    values.get("provenance") or "",
                    values.get("supersedes"),
                    values.get("contradicts"),
                    self._json_dump(values.get("metadata") or {}),
                    now,
                ),
            )
        return self.get_graph_edge(edge_id)  # type: ignore[return-value]

    def get_graph_edge(self, edge_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_graph_edges WHERE id=?", (edge_id,)).fetchone()
        return self._edge_row(row) if row else None

    def list_graph_edges(
        self,
        *,
        as_of: str | None = None,
        source_id: str | None = None,
        target_id: str | None = None,
        entity_id: str | None = None,
        known_as_of: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit, default=200, maximum=500)
        clauses = ["1=1"]
        args: list[Any] = []
        if entity_id:
            clauses.append("(source_id=? OR target_id=?)")
            args.extend([entity_id, entity_id])
        if source_id:
            clauses.append("source_id=?")
            args.append(source_id)
        if target_id:
            clauses.append("target_id=?")
            args.append(target_id)
        if as_of:
            # Valid-time: belief holds at T.
            clauses.append("(valid_from IS NULL OR valid_from<=?)")
            args.append(as_of)
            clauses.append("(valid_until IS NULL OR valid_until>?)")
            args.append(as_of)
        if known_as_of:
            # Observed-time: known by T (no future knowledge).
            clauses.append("observed_at<=?")
            args.append(known_as_of)
        args.append(limit)
        sql = f"SELECT * FROM gen2_graph_edges WHERE {' AND '.join(clauses)} ORDER BY observed_at DESC LIMIT ?"
        with self.connection() as db:
            rows = db.execute(sql, args).fetchall()
        return [self._edge_row(row) for row in rows]

    def _edge_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "source_id": row["source_id"],
            "target_id": row["target_id"],
            "relation": row["relation"],
            "relation_kind": row["relation_kind"],
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "observed_at": row["observed_at"],
            "source_ref": row["source_ref"],
            "confidence": row["confidence"],
            "provenance": row["provenance"],
            "supersedes": row["supersedes"],
            "contradicts": row["contradicts"],
            "metadata": self._json_load(row["metadata_json"], {}),
            "created_at": row["created_at"],
        }

    # --- finance ---
    def save_market_event(self, values: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        first_seen = values.get("first_seen") or now
        content_hash = values.get("content_hash")
        if not content_hash:
            title = str(values.get("title") or "").strip().lower()
            summary = str(values.get("summary") or "").strip().lower()[:200]
            content_hash = __import__("hashlib").sha256(f"{title}|{summary}".encode("utf-8")).hexdigest()[:16]
        with self.connection() as db:
            existing = None
            if content_hash:
                existing = db.execute(
                    "SELECT * FROM gen2_market_events WHERE content_hash=?",
                    (content_hash,),
                ).fetchone()
            if existing:
                source_count = int(existing["source_count"] or 1) + int(values.get("source_count") or 1)
                evidence = self._json_load(existing["evidence_json"], [])
                extra = values.get("supporting_evidence") or []
                if isinstance(extra, list):
                    evidence = list(evidence) + list(extra)
                entities = self._json_load(existing["entities_json"], [])
                for ent in values.get("entities") or []:
                    if ent not in entities:
                        entities.append(ent)
                conf = max(float(existing["confidence"] or 0), float(values.get("confidence") or 0.5))
                summary = values.get("summary") or ""
                if len(summary) <= len(str(existing["summary"] or "")):
                    summary = existing["summary"]
                event_id = existing["id"]
                db.execute(
                    """UPDATE gen2_market_events
                       SET source_count=?, evidence_json=?, entities_json=?, affected_json=?,
                           confidence=?, summary=?
                       WHERE id=?""",
                    (
                        source_count,
                        self._json_dump(evidence),
                        self._json_dump(entities),
                        self._json_dump(values.get("affected_entities") or entities),
                        conf,
                        summary,
                        event_id,
                    ),
                )
            else:
                event_id = new_id("mev")
                db.execute(
                    """INSERT INTO gen2_market_events
                       (id,event_type,title,summary,entities_json,affected_json,source_count,confidence,novelty,
                        first_seen,likely_horizon,analogues_json,evidence_json,metadata_json,created_at,content_hash)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        event_id,
                        values["event_type"],
                        values["title"],
                        values.get("summary") or "",
                        self._json_dump(values.get("entities") or []),
                        self._json_dump(values.get("affected_entities") or []),
                        int(values.get("source_count") or 1),
                        float(values.get("confidence") or 0.5),
                        float(values.get("novelty") or 0.5),
                        first_seen,
                        values.get("likely_horizon") or "unknown",
                        self._json_dump(values.get("historical_analogues") or []),
                        self._json_dump(values.get("supporting_evidence") or []),
                        self._json_dump(values.get("metadata") or {}),
                        now,
                        content_hash,
                    ),
                )
        return self.get_market_event(event_id)  # type: ignore[return-value]

    def get_market_event(self, event_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_market_events WHERE id=?", (event_id,)).fetchone()
        return self._market_row(row) if row else None

    def list_market_events(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit)
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM gen2_market_events ORDER BY first_seen DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._market_row(row) for row in rows]

    def _market_row(self, row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        return {
            "id": row["id"],
            "event_type": row["event_type"],
            "title": row["title"],
            "summary": row["summary"],
            "entities": self._json_load(row["entities_json"], []),
            "affected_entities": self._json_load(row["affected_json"], []),
            "source_count": row["source_count"],
            "confidence": row["confidence"],
            "novelty": row["novelty"],
            "first_seen": row["first_seen"],
            "likely_horizon": row["likely_horizon"],
            "historical_analogues": self._json_load(row["analogues_json"], []),
            "supporting_evidence": self._json_load(row["evidence_json"], []),
            "metadata": self._json_load(row["metadata_json"], {}),
            "content_hash": row["content_hash"] if "content_hash" in keys else None,
            "created_at": row["created_at"],
        }

    # --- compute ---
    def upsert_node(self, values: dict[str, Any]) -> dict[str, Any]:
        node_id = values.get("id") or new_id("node")
        now = utc_now()
        with self.connection() as db:
            existing = db.execute("SELECT id FROM gen2_compute_nodes WHERE id=?", (node_id,)).fetchone()
            if existing:
                db.execute(
                    """UPDATE gen2_compute_nodes
                       SET name=?, role=?, status=?, capabilities_json=?, load_json=?, last_heartbeat=?, updated_at=?
                       WHERE id=?""",
                    (
                        values.get("name") or node_id,
                        values.get("role") or "local",
                        values.get("status") or "online",
                        self._json_dump(values.get("capabilities") or {}),
                        self._json_dump(values.get("load") or {}),
                        values.get("last_heartbeat") or now,
                        now,
                        node_id,
                    ),
                )
            else:
                db.execute(
                    """INSERT INTO gen2_compute_nodes
                       (id,name,role,status,capabilities_json,load_json,last_heartbeat,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        node_id,
                        values.get("name") or node_id,
                        values.get("role") or "local",
                        values.get("status") or "online",
                        self._json_dump(values.get("capabilities") or {}),
                        self._json_dump(values.get("load") or {}),
                        values.get("last_heartbeat") or now,
                        now,
                        now,
                    ),
                )
        return self.get_node(node_id)  # type: ignore[return-value]

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_compute_nodes WHERE id=?", (node_id,)).fetchone()
        return self._node_row(row) if row else None

    def list_nodes(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM gen2_compute_nodes ORDER BY name").fetchall()
        return [self._node_row(row) for row in rows]

    def _node_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "role": row["role"],
            "status": row["status"],
            "capabilities": self._json_load(row["capabilities_json"], {}),
            "load": self._json_load(row["load_json"], {}),
            "last_heartbeat": row["last_heartbeat"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_remote_job(self, values: dict[str, Any]) -> dict[str, Any]:
        job_id = new_id("rjob")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_remote_jobs
                   (id,node_id,mission_id,status,payload_json,result_json,error,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,NULL,?,?)""",
                (
                    job_id,
                    values["node_id"],
                    values.get("mission_id"),
                    values.get("status") or "queued",
                    self._json_dump(values.get("payload") or {}),
                    self._json_dump(values.get("result") or {}),
                    now,
                    now,
                ),
            )
        return self.get_remote_job(job_id)  # type: ignore[return-value]

    def update_remote_job(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        sets: list[str] = []
        args: list[Any] = []
        for key in ("status", "error", "mission_id", "node_id"):
            if key in fields:
                sets.append(f"{key}=?")
                args.append(fields[key])
        if "payload" in fields:
            sets.append("payload_json=?")
            args.append(self._json_dump(fields["payload"]))
        if "result" in fields:
            sets.append("result_json=?")
            args.append(self._json_dump(fields["result"]))
        if not sets:
            return self.get_remote_job(job_id)
        sets.append("updated_at=?")
        args.append(utc_now())
        args.append(job_id)
        with self.connection() as db:
            db.execute(f"UPDATE gen2_remote_jobs SET {', '.join(sets)} WHERE id=?", args)
        return self.get_remote_job(job_id)

    def get_remote_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_remote_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "node_id": row["node_id"],
            "mission_id": row["mission_id"],
            "status": row["status"],
            "payload": self._json_load(row["payload_json"], {}),
            "result": self._json_load(row["result_json"], {}),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_remote_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit)
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM gen2_remote_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "node_id": row["node_id"],
                "mission_id": row["mission_id"],
                "status": row["status"],
                "payload": self._json_load(row["payload_json"], {}),
                "result": self._json_load(row["result_json"], {}),
                "error": row["error"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    # --- workflows (v10) ---
    def create_workflow(self, values: dict[str, Any]) -> dict[str, Any]:
        workflow_id = str(values.get("id") or new_id("wf"))
        now = utc_now()
        definition = dict(values.get("definition") or {})
        definition.setdefault("id", workflow_id)
        definition.setdefault("name", values.get("name") or "untitled")
        definition.setdefault("version", int(values.get("version") or definition.get("version") or 1))
        definition.setdefault("status", values.get("status") or "draft")
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_workflows
                   (id,name,status,definition_json,metrics_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    workflow_id,
                    values.get("name") or definition.get("name") or "untitled",
                    values.get("status") or definition.get("status") or "draft",
                    self._json_dump(definition),
                    self._json_dump(values.get("metrics") or definition.get("metrics") or {}),
                    now,
                    now,
                ),
            )
            db.execute(
                """INSERT INTO gen2_workflow_revisions
                   (id,workflow_id,version,definition_json,created_at,note)
                   VALUES(?,?,?,?,?,?)""",
                (
                    new_id("wfr"),
                    workflow_id,
                    int(definition.get("version") or 1),
                    self._json_dump(definition),
                    now,
                    str(values.get("note") or "create"),
                ),
            )
        return self.get_workflow(workflow_id)  # type: ignore[return-value]

    def update_workflow(self, workflow_id: str, **fields: Any) -> dict[str, Any] | None:
        current = self.get_workflow(workflow_id)
        if not current:
            return None
        mapping = {"definition": "definition_json", "metrics": "metrics_json"}
        sets: list[str] = []
        args: list[Any] = []
        for key, value in fields.items():
            if key in {"name", "status"}:
                sets.append(f"{key}=?")
                args.append(value)
            elif key in mapping:
                sets.append(f"{mapping[key]}=?")
                args.append(self._json_dump(value))
        if not sets:
            return current
        sets.append("updated_at=?")
        args.append(utc_now())
        args.append(workflow_id)
        with self.connection() as db:
            db.execute(f"UPDATE gen2_workflows SET {', '.join(sets)} WHERE id=?", args)
        return self.get_workflow(workflow_id)

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_workflows WHERE id=?", (workflow_id,)).fetchone()
        return self._workflow_row(row) if row else None

    def list_workflows(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit)
        with self.connection() as db:
            if status:
                rows = db.execute(
                    "SELECT * FROM gen2_workflows WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM gen2_workflows WHERE status != 'archived' "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._workflow_row(row) for row in rows]

    def archive_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        return self.update_workflow(workflow_id, status="archived")

    def save_workflow_revision(
        self,
        workflow_id: str,
        definition: dict[str, Any],
        *,
        note: str = "",
        version: int | None = None,
    ) -> dict[str, Any]:
        rev_id = new_id("wfr")
        now = utc_now()
        ver = int(version if version is not None else (definition.get("version") or 1))
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_workflow_revisions
                   (id,workflow_id,version,definition_json,created_at,note)
                   VALUES(?,?,?,?,?,?)""",
                (rev_id, workflow_id, ver, self._json_dump(definition), now, note or ""),
            )
        return {
            "id": rev_id,
            "workflow_id": workflow_id,
            "version": ver,
            "definition": definition,
            "created_at": now,
            "note": note or "",
        }

    def list_workflow_revisions(self, workflow_id: str, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit)
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM gen2_workflow_revisions WHERE workflow_id=? "
                "ORDER BY version DESC LIMIT ?",
                (workflow_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "workflow_id": row["workflow_id"],
                "version": row["version"],
                "definition": self._json_load(row["definition_json"], {}),
                "created_at": row["created_at"],
                "note": row["note"],
            }
            for row in rows
        ]

    def get_workflow_revision(self, workflow_id: str, version: int) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM gen2_workflow_revisions WHERE workflow_id=? AND version=?",
                (workflow_id, int(version)),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "workflow_id": row["workflow_id"],
            "version": row["version"],
            "definition": self._json_load(row["definition_json"], {}),
            "created_at": row["created_at"],
            "note": row["note"],
        }

    def create_workflow_run(
        self,
        *,
        workflow_id: str,
        version: int,
        mode: str,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = new_id("wrun")
        now = utc_now()
        with self.connection() as db:
            db.execute(
                """INSERT INTO gen2_workflow_runs
                   (id,workflow_id,version,mode,status,result_json,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    run_id,
                    workflow_id,
                    int(version),
                    mode,
                    status,
                    self._json_dump(result),
                    now,
                ),
            )
        return {
            "id": run_id,
            "workflow_id": workflow_id,
            "version": int(version),
            "mode": mode,
            "status": status,
            "result": result,
            "created_at": now,
        }

    def list_workflow_runs(self, workflow_id: str, limit: int = 50) -> list[dict[str, Any]]:
        limit = clamp_list_limit(limit)
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM gen2_workflow_runs WHERE workflow_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (workflow_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "workflow_id": row["workflow_id"],
                "version": row["version"],
                "mode": row["mode"],
                "status": row["status"],
                "result": self._json_load(row["result_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_workflow_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM gen2_workflow_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "workflow_id": row["workflow_id"],
            "version": row["version"],
            "mode": row["mode"],
            "status": row["status"],
            "result": self._json_load(row["result_json"], {}),
            "created_at": row["created_at"],
        }

    def update_workflow_run(self, run_id: str, **fields: Any) -> dict[str, Any] | None:
        sets: list[str] = []
        args: list[Any] = []
        for key, value in fields.items():
            if key in {"status", "mode"}:
                sets.append(f"{key}=?")
                args.append(value)
            elif key == "result":
                sets.append("result_json=?")
                args.append(self._json_dump(value))
        if not sets:
            return self.get_workflow_run(run_id)
        args.append(run_id)
        with self.connection() as db:
            db.execute(f"UPDATE gen2_workflow_runs SET {', '.join(sets)} WHERE id=?", args)
        return self.get_workflow_run(run_id)

    def _workflow_row(self, row: sqlite3.Row) -> dict[str, Any]:
        definition = self._json_load(row["definition_json"], {})
        metrics = self._json_load(row["metrics_json"], {})
        return {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "definition": definition,
            "metrics": metrics,
            "version": int((definition or {}).get("version") or 1),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
