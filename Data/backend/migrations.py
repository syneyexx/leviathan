"""Schema migration foundation for LEVIATHAN SQLite stores."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _m1_baseline_marker(conn: sqlite3.Connection) -> None:
    """Version 1 marks the pre-migration schema as acknowledged.

    Conversations/knowledge/runs tables may already exist from CREATE TABLE IF NOT EXISTS.
    This migration is intentionally a no-op body so existing DBs can adopt versioning safely.
    """
    conn.execute("SELECT 1")


def _m2_artifacts_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            run_id TEXT,
            job_id TEXT,
            artifact_type TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            content_hash TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            producer TEXT NOT NULL,
            verification_status TEXT NOT NULL DEFAULT 'unverified',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )


def _m3_knowledge_v2(conn: sqlite3.Connection) -> None:
    """Add Knowledge V2 columns/tables. Safe on existing Step-1 knowledge_documents."""

    def columns(table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    existing = columns("knowledge_documents")
    for name, ddl in {
        "status": "TEXT NOT NULL DEFAULT 'READY'",
        "content_hash": "TEXT",
        "original_path": "TEXT",
        "source_mtime": "TEXT",
        "size_bytes": "INTEGER",
        "parser": "TEXT NOT NULL DEFAULT 'plain_text'",
        "parser_version": "TEXT NOT NULL DEFAULT '1.0.0'",
        "ingest_version": "INTEGER NOT NULL DEFAULT 1",
        "trust_metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        "error": "TEXT",
    }.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE knowledge_documents ADD COLUMN {name} {ddl}")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            token_estimate INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(document_id, chunk_index),
            FOREIGN KEY(document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document ON knowledge_chunks(document_id, chunk_index)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_ingest_files (
            path TEXT PRIMARY KEY,
            size_bytes INTEGER NOT NULL,
            mtime TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            document_id TEXT,
            status TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            ingest_version INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunk_fts
            USING fts5(chunk_id UNINDEXED, document_id UNINDEXED, title, content)
            """
        )
    except sqlite3.OperationalError:
        pass


def _m4_approvals_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approvals (
            approval_id TEXT PRIMARY KEY,
            capability_id TEXT NOT NULL,
            side_effects_json TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            reason TEXT,
            run_id TEXT,
            decided_by TEXT,
            decided_at TEXT,
            expires_at TEXT,
            single_use INTEGER NOT NULL DEFAULT 1,
            arguments_digest TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_approvals_capability_status "
        "ON approvals(capability_id, status)"
    )


def _m5_jobs_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            capability_id TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            state TEXT NOT NULL,
            run_id TEXT,
            approval_id TEXT,
            requested_by TEXT NOT NULL,
            result_json TEXT,
            error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, created_at)")


def _m6_observations_and_effects(conn: sqlite3.Connection) -> None:
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


def _m7_evidence_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            claim TEXT NOT NULL,
            created_at TEXT NOT NULL,
            verified_at TEXT,
            observation_id TEXT,
            artifact_id TEXT,
            run_id TEXT,
            job_id TEXT,
            content_hash TEXT,
            path TEXT,
            error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_status ON evidence(status, created_at)"
    )


def _m8_memory_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_entries (
            memory_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source TEXT NOT NULL,
            trust TEXT NOT NULL,
            run_id TEXT,
            conversation_id TEXT,
            tags_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_entries(status, updated_at)"
    )
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
            USING fts5(memory_id UNINDEXED, content, tags)
            """
        )
    except sqlite3.OperationalError:
        pass


def _m9_workflows_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflows (
            workflow_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            state TEXT NOT NULL,
            steps_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            current_step INTEGER NOT NULL DEFAULT 0,
            run_id TEXT,
            step_results_json TEXT NOT NULL DEFAULT '[]',
            error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )


def _m10_schedules_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schedules (
            schedule_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            target_ref TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            next_run_at TEXT NOT NULL,
            last_run_at TEXT,
            target_payload_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedules_next ON schedules(status, next_run_at)"
    )


def _m11_verification_reports(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS verification_reports (
            report_id TEXT PRIMARY KEY,
            outcome TEXT NOT NULL,
            created_at TEXT NOT NULL,
            run_id TEXT,
            job_id TEXT,
            requirements_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_verification_reports_created "
        "ON verification_reports(created_at)"
    )


def _m12_neuro_memory_snapshots(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS neuro_memory_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            tier INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_neuro_snapshots_tier "
        "ON neuro_memory_snapshots(tier, created_at)"
    )


def _m13_model_control_plane(conn: sqlite3.Connection) -> None:
    """Central Model Control Plane tables (same LEVIATHAN database)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_providers (
            provider_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            provider_type TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            api_key_ciphertext TEXT,
            auto_connect INTEGER NOT NULL DEFAULT 1,
            timeout_seconds REAL NOT NULL DEFAULT 30,
            refresh_interval_seconds REAL NOT NULL DEFAULT 60,
            health TEXT NOT NULL DEFAULT 'unknown',
            last_successful_at TEXT,
            last_error TEXT,
            last_latency_ms REAL,
            last_check_at TEXT,
            capabilities_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_registry (
            model_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            runtime_id TEXT,
            source TEXT NOT NULL,
            object_type TEXT,
            architecture TEXT,
            family TEXT,
            parameter_count INTEGER,
            quantization TEXT,
            format TEXT,
            disk_size_bytes INTEGER,
            context_window INTEGER,
            max_output_tokens INTEGER,
            capabilities_json TEXT NOT NULL DEFAULT '{}',
            lifecycle_state TEXT NOT NULL DEFAULT 'unknown',
            health TEXT NOT NULL DEFAULT 'unknown',
            active INTEGER NOT NULL DEFAULT 0,
            loaded INTEGER,
            local_path TEXT,
            endpoint TEXT,
            last_discovered_at TEXT,
            last_used_at TEXT,
            tags_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_model_registry_provider "
        "ON model_registry(provider_id, lifecycle_state)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_profiles (
            model_id TEXT PRIMARY KEY,
            temperature REAL NOT NULL,
            top_p REAL NOT NULL,
            top_k INTEGER NOT NULL,
            max_tokens INTEGER NOT NULL,
            repeat_penalty REAL NOT NULL,
            seed INTEGER NOT NULL,
            system_prompt TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_control_state (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_capability_results (
            model_id TEXT NOT NULL,
            capability TEXT NOT NULL,
            declared TEXT NOT NULL,
            verified TEXT NOT NULL,
            last_tested_at TEXT,
            detail TEXT,
            PRIMARY KEY(model_id, capability)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_downloads (
            download_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            source TEXT NOT NULL,
            repository_id TEXT,
            revision TEXT,
            destination TEXT,
            bytes_downloaded INTEGER,
            total_bytes INTEGER,
            speed_bps REAL,
            eta_seconds REAL,
            error TEXT,
            model_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )


def _m14_datasets_training_research(conn: sqlite3.Connection) -> None:
    """Datasets, training jobs, and research workspace persistence."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS datasets (
            dataset_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            status TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            original_filename TEXT,
            original_uri TEXT,
            license TEXT,
            schema_version INTEGER NOT NULL DEFAULT 1,
            content_hash TEXT,
            byte_size INTEGER,
            row_count INTEGER,
            detected_format TEXT,
            format_confidence REAL,
            provenance_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            raw_path TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_versions (
            version_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            version_label TEXT NOT NULL,
            parent_version_id TEXT,
            status TEXT NOT NULL,
            kind TEXT NOT NULL,
            schema_json TEXT NOT NULL DEFAULT '{}',
            row_count INTEGER,
            byte_size INTEGER,
            content_hash TEXT,
            storage_path TEXT,
            split_json TEXT NOT NULL DEFAULT '{}',
            transform_lineage_json TEXT NOT NULL DEFAULT '[]',
            token_stats_json TEXT NOT NULL DEFAULT '{}',
            validation_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(dataset_id) REFERENCES datasets(dataset_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dataset_versions_dataset "
        "ON dataset_versions(dataset_id, created_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_files (
            file_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            version_id TEXT,
            role TEXT NOT NULL,
            path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            byte_size INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(dataset_id) REFERENCES datasets(dataset_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_jobs (
            job_id TEXT PRIMARY KEY,
            dataset_id TEXT,
            version_id TEXT,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            phase TEXT,
            progress REAL,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            worker_pid INTEGER,
            checkpoint_json TEXT NOT NULL DEFAULT '{}',
            config_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            log_path TEXT,
            trace_id TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dataset_jobs_status ON dataset_jobs(status, created_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_indexes (
            index_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            status TEXT NOT NULL,
            chunk_count INTEGER,
            embedding_model TEXT,
            index_version INTEGER NOT NULL DEFAULT 1,
            knowledge_scope TEXT,
            storage_path TEXT,
            provenance_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(dataset_id) REFERENCES datasets(dataset_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS training_jobs (
            job_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            phase TEXT,
            method TEXT NOT NULL,
            base_model_ref TEXT NOT NULL,
            dataset_version_id TEXT,
            output_dir TEXT,
            config_json TEXT NOT NULL DEFAULT '{}',
            planner_json TEXT NOT NULL DEFAULT '{}',
            preflight_json TEXT NOT NULL DEFAULT '{}',
            progress REAL,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            worker_pid INTEGER,
            checkpoint_json TEXT NOT NULL DEFAULT '{}',
            metrics_summary_json TEXT NOT NULL DEFAULT '{}',
            evaluation_json TEXT NOT NULL DEFAULT '{}',
            artifact_id TEXT,
            error TEXT,
            log_path TEXT,
            trace_id TEXT,
            seed INTEGER,
            config_hash TEXT,
            environment_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            started_at TEXT,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_jobs_status ON training_jobs(status, created_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS training_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            step INTEGER,
            epoch REAL,
            metric_name TEXT NOT NULL,
            metric_value REAL NOT NULL,
            recorded_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(job_id) REFERENCES training_jobs(job_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_metrics_job ON training_metrics(job_id, recorded_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS training_checkpoints (
            checkpoint_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            step INTEGER,
            epoch REAL,
            path TEXT NOT NULL,
            content_hash TEXT,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(job_id) REFERENCES training_jobs(job_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS training_artifacts (
            artifact_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            path TEXT NOT NULL,
            base_model_ref TEXT,
            dataset_version_id TEXT,
            method TEXT,
            config_hash TEXT,
            content_hash TEXT,
            model_card_path TEXT,
            evaluation_json TEXT NOT NULL DEFAULT '{}',
            compatibility_json TEXT NOT NULL DEFAULT '{}',
            registered_model_id TEXT,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(job_id) REFERENCES training_jobs(job_id)
        )
        """
    )
    conn.execute(
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
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_events (
            event_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_events_project "
        "ON research_events(project_id, created_at)"
    )
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        """
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
        )
        """
    )


def _m15_coding_agent(conn: sqlite3.Connection) -> None:
    """Coding Agent control-plane sessions, turns, steps, and patches."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coding_sessions (
            session_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            mission TEXT NOT NULL,
            status TEXT NOT NULL,
            workspace_root TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            user_goal TEXT NOT NULL DEFAULT '',
            conversation_id TEXT,
            run_id TEXT,
            model_id TEXT,
            error TEXT,
            verification_id TEXT,
            feature_truth_json TEXT NOT NULL DEFAULT '{}',
            neuro_json TEXT NOT NULL DEFAULT '{}',
            pending_capability_json TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            worker_pid INTEGER,
            round_count INTEGER NOT NULL DEFAULT 0,
            read_paths_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coding_sessions_status "
        "ON coding_sessions(status, updated_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coding_turns (
            turn_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            content_raw TEXT,
            created_at TEXT NOT NULL,
            neuro_assessment_json TEXT,
            token_estimate INTEGER,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coding_turns_session "
        "ON coding_turns(session_id, seq)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coding_steps (
            step_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            turn_id TEXT,
            seq INTEGER NOT NULL,
            kind TEXT NOT NULL,
            capability_id TEXT,
            arguments_json TEXT NOT NULL DEFAULT '{}',
            approval_id TEXT,
            status TEXT NOT NULL,
            observation_id TEXT,
            effect_id TEXT,
            artifact_id TEXT,
            output_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            requested_by TEXT NOT NULL DEFAULT 'agent:coding',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coding_steps_session "
        "ON coding_steps(session_id, seq)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coding_patches (
            patch_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            artifact_id TEXT,
            path TEXT NOT NULL,
            diff_unified TEXT NOT NULL,
            hash_before TEXT,
            hash_after TEXT,
            applied INTEGER NOT NULL DEFAULT 0,
            approval_id TEXT,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coding_patches_session "
        "ON coding_patches(session_id, created_at)"
    )


def _m16_market_sim(conn: sqlite3.Connection) -> None:
    """Market simulation: data sources, strategies, runs, fills, deliberation."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_sources (
            source_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            kind TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            content_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            bar_count INTEGER NOT NULL DEFAULT 0,
            start_ts TEXT,
            end_ts TEXT,
            byte_size INTEGER NOT NULL DEFAULT 0,
            validation_error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_data_sources_status "
        "ON market_data_sources(status, updated_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_strategies (
            strategy_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            tags_json TEXT NOT NULL DEFAULT '[]',
            current_version INTEGER NOT NULL DEFAULT 1,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_strategy_versions (
            version_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            parameters_json TEXT NOT NULL DEFAULT '{}',
            entry_rules_json TEXT NOT NULL DEFAULT '{}',
            exit_rules_json TEXT NOT NULL DEFAULT '{}',
            risk_rules_json TEXT NOT NULL DEFAULT '{}',
            required_timeframes_json TEXT NOT NULL DEFAULT '[]',
            brain_dependencies_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            changelog TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(strategy_id, version),
            FOREIGN KEY(strategy_id) REFERENCES market_strategies(strategy_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_sim_runs (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            source_id TEXT NOT NULL,
            strategy_id TEXT,
            strategy_version INTEGER,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            start_ts TEXT NOT NULL,
            end_ts TEXT NOT NULL,
            data_hash TEXT NOT NULL,
            seed INTEGER NOT NULL DEFAULT 42,
            speed REAL NOT NULL DEFAULT 1.0,
            initial_cash REAL NOT NULL DEFAULT 100000,
            fee_bps REAL NOT NULL DEFAULT 5.0,
            slippage_bps REAL NOT NULL DEFAULT 2.0,
            max_position_pct REAL NOT NULL DEFAULT 25.0,
            max_drawdown_pct REAL NOT NULL DEFAULT 20.0,
            per_trade_risk_pct REAL NOT NULL DEFAULT 1.0,
            agents_json TEXT NOT NULL DEFAULT '[]',
            deliberation_every_n INTEGER NOT NULL DEFAULT 5,
            clock_ts TEXT,
            bar_index INTEGER NOT NULL DEFAULT 0,
            bar_count INTEGER NOT NULL DEFAULT 0,
            cash REAL NOT NULL DEFAULT 100000,
            equity REAL NOT NULL DEFAULT 100000,
            position_qty REAL NOT NULL DEFAULT 0,
            realized_pnl REAL NOT NULL DEFAULT 0,
            unrealized_pnl REAL NOT NULL DEFAULT 0,
            causality_violations INTEGER NOT NULL DEFAULT 0,
            brain_hits INTEGER NOT NULL DEFAULT 0,
            brain_misses INTEGER NOT NULL DEFAULT 0,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            worker_pid INTEGER,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_sim_runs_status "
        "ON market_sim_runs(status, updated_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_sim_fills (
            fill_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            bar_index INTEGER NOT NULL,
            ts TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            fee REAL NOT NULL DEFAULT 0,
            slippage REAL NOT NULL DEFAULT 0,
            agent_id TEXT,
            rationale TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES market_sim_runs(run_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_sim_fills_run "
        "ON market_sim_fills(run_id, bar_index)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_sim_messages (
            message_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            bar_index INTEGER NOT NULL,
            ts TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            role TEXT NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            proposal_json TEXT NOT NULL DEFAULT '{}',
            confidence REAL NOT NULL DEFAULT 0,
            brain_refs_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES market_sim_runs(run_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_sim_messages_run "
        "ON market_sim_messages(run_id, bar_index)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_sim_equity (
            point_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            bar_index INTEGER NOT NULL,
            ts TEXT NOT NULL,
            equity REAL NOT NULL,
            cash REAL NOT NULL,
            position_qty REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES market_sim_runs(run_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_sim_equity_run "
        "ON market_sim_equity(run_id, bar_index)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_sim_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            bar_index INTEGER,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES market_sim_runs(run_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_sim_events_run "
        "ON market_sim_events(run_id, created_at)"
    )


def _m17_mcp_bridge(conn: sqlite3.Connection) -> None:
    """Universal MCP bridge tables — servers, tools cache, call history."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mcp_servers (
            server_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_key TEXT NOT NULL,
            owner_module_id TEXT,
            transport TEXT NOT NULL,
            command TEXT,
            args_json TEXT NOT NULL DEFAULT '[]',
            url TEXT,
            cwd TEXT,
            env_public_json TEXT NOT NULL DEFAULT '{}',
            secret_refs_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 0,
            trust TEXT NOT NULL DEFAULT 'untrusted',
            requested_isolation TEXT NOT NULL DEFAULT 'subprocess',
            effective_isolation TEXT NOT NULL DEFAULT 'subprocess',
            timeout_seconds REAL NOT NULL DEFAULT 30,
            max_concurrent_calls INTEGER NOT NULL DEFAULT 4,
            eager_connect INTEGER NOT NULL DEFAULT 0,
            expand_tools INTEGER NOT NULL DEFAULT 1,
            semantic_effects_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            current_state TEXT NOT NULL DEFAULT 'DISCONNECTED',
            last_connected_at TEXT,
            last_seen_at TEXT,
            last_error_code TEXT,
            last_error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_kind, source_key)
        );

        CREATE TABLE IF NOT EXISTS mcp_tools (
            capability_id TEXT PRIMARY KEY,
            server_id TEXT NOT NULL,
            external_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            input_schema_json TEXT NOT NULL DEFAULT '{}',
            schema_hash TEXT NOT NULL,
            semantic_effects_json TEXT NOT NULL DEFAULT '[]',
            availability TEXT NOT NULL DEFAULT 'unavailable',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            server_version TEXT,
            protocol_version TEXT,
            UNIQUE(server_id, external_name),
            FOREIGN KEY(server_id) REFERENCES mcp_servers(server_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_mcp_tools_server
            ON mcp_tools(server_id, external_name);

        CREATE TABLE IF NOT EXISTS mcp_tool_calls (
            call_id TEXT PRIMARY KEY,
            trace_id TEXT,
            server_id TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            external_tool_name TEXT NOT NULL,
            requester TEXT NOT NULL,
            status TEXT NOT NULL,
            duration_ms REAL,
            approval_id TEXT,
            arguments_summary TEXT,
            result_summary TEXT,
            error_code TEXT,
            error_message TEXT,
            schema_hash TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_started
            ON mcp_tool_calls(started_at DESC);
        """
    )


def _m18_rag_v3(conn: sqlite3.Connection) -> None:
    """Knowledge RAG V3: chunk provenance columns, embeddings, atlas, why, deep recall."""

    def columns(table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            token_estimate INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(document_id, chunk_index)
        )
        """
    )
    chunk_cols = columns("knowledge_chunks")
    for name, ddl in {
        "start_offset": "INTEGER NOT NULL DEFAULT 0",
        "end_offset": "INTEGER NOT NULL DEFAULT 0",
        "confidence": "REAL NOT NULL DEFAULT 1.0",
        "uncertainty_notes": "TEXT NOT NULL DEFAULT ''",
        "source_type": "TEXT NOT NULL DEFAULT 'document'",
        "provenance_json": "TEXT NOT NULL DEFAULT '{}'",
    }.items():
        if name not in chunk_cols:
            conn.execute(f"ALTER TABLE knowledge_chunks ADD COLUMN {name} {ddl}")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_chunk_embeddings (
            chunk_id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            embedding BLOB NOT NULL,
            content_hash TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS directional_relation_atoms (
            atom_id TEXT PRIMARY KEY,
            subject_ref TEXT NOT NULL,
            object_ref TEXT NOT NULL,
            relation_class TEXT NOT NULL,
            comparison_vector_json TEXT NOT NULL DEFAULT '[]',
            supporting_evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            document_id TEXT,
            chunk_id TEXT,
            confidence REAL NOT NULL DEFAULT 0.5,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_relation_atoms_subject "
        "ON directional_relation_atoms(subject_ref, relation_class)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS atlas_records (
            atlas_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT '',
            scale TEXT NOT NULL,
            entities_json TEXT NOT NULL DEFAULT '[]',
            projects_json TEXT NOT NULL DEFAULT '[]',
            relation_types_json TEXT NOT NULL DEFAULT '[]',
            unresolved_questions_json TEXT NOT NULL DEFAULT '[]',
            contradictions_json TEXT NOT NULL DEFAULT '[]',
            confidence REAL NOT NULL DEFAULT 0.5,
            evidence_record_refs_json TEXT NOT NULL DEFAULT '[]',
            parent_atlas_id TEXT,
            child_atlas_ids_json TEXT NOT NULL DEFAULT '[]',
            last_revised_at TEXT NOT NULL,
            revision_reason TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_atlas_scale ON atlas_records(scale, last_revised_at)"
    )
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS atlas_fts
            USING fts5(atlas_id UNINDEXED, title, summary, entities, projects)
            """
        )
    except sqlite3.OperationalError:
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS why_records (
            why_id TEXT PRIMARY KEY,
            observation TEXT NOT NULL,
            bucket TEXT NOT NULL,
            parent_ref TEXT,
            child_ref TEXT,
            comparison TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            residue TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.5,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_why_bucket ON why_records(bucket, created_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS deep_recall_logs (
            recall_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            request_json TEXT NOT NULL,
            result_json TEXT NOT NULL,
            context_cost INTEGER NOT NULL,
            stopped_reason TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS residual_receipts (
            receipt_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            mode TEXT NOT NULL,
            applied INTEGER NOT NULL,
            implemented INTEGER NOT NULL,
            degraded_to_chat_completions INTEGER NOT NULL,
            reason TEXT NOT NULL,
            hook_json TEXT NOT NULL DEFAULT '{}',
            detail TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "memory_entries" in tables:
        mem_cols = columns("memory_entries")
        if "priority" not in mem_cols:
            conn.execute(
                "ALTER TABLE memory_entries ADD COLUMN priority REAL NOT NULL DEFAULT 0.5"
            )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )


MIGRATIONS: Sequence[Migration] = (
    Migration(version=1, name="baseline_schema_versioning", apply=_m1_baseline_marker),
    Migration(version=2, name="artifacts_table", apply=_m2_artifacts_table),
    Migration(version=3, name="knowledge_v2", apply=_m3_knowledge_v2),
    Migration(version=4, name="approvals_table", apply=_m4_approvals_table),
    Migration(version=5, name="jobs_table", apply=_m5_jobs_table),
    Migration(version=6, name="observations_and_effects", apply=_m6_observations_and_effects),
    Migration(version=7, name="evidence_table", apply=_m7_evidence_table),
    Migration(version=8, name="memory_table", apply=_m8_memory_table),
    Migration(version=9, name="workflows_table", apply=_m9_workflows_table),
    Migration(version=10, name="schedules_table", apply=_m10_schedules_table),
    Migration(version=11, name="verification_reports", apply=_m11_verification_reports),
    Migration(version=12, name="neuro_memory_snapshots", apply=_m12_neuro_memory_snapshots),
    Migration(version=13, name="model_control_plane", apply=_m13_model_control_plane),
    Migration(version=14, name="datasets_training_research", apply=_m14_datasets_training_research),
    Migration(version=15, name="coding_agent", apply=_m15_coding_agent),
    Migration(version=16, name="market_sim", apply=_m16_market_sim),
    Migration(version=17, name="mcp_bridge", apply=_m17_mcp_bridge),
    Migration(version=18, name="rag_v3", apply=_m18_rag_v3),
)


class MigrationRunner:
    def __init__(self, path: Path, migrations: Sequence[Migration] = MIGRATIONS) -> None:
        self.path = path
        self.migrations = sorted(migrations, key=lambda item: item.version)
        self._validate_sequence()

    def _validate_sequence(self) -> None:
        expected = 1
        seen: set[int] = set()
        for migration in self.migrations:
            if migration.version in seen:
                raise MigrationError(f"Duplicate migration version: {migration.version}")
            if migration.version != expected:
                raise MigrationError(
                    f"Migration versions must be contiguous starting at 1; expected {expected}, got {migration.version}"
                )
            seen.add(migration.version)
            expected += 1

    def ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )

    def current_version(self, conn: sqlite3.Connection) -> int:
        self.ensure_table(conn)
        row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
        return int(row[0] if not isinstance(row, sqlite3.Row) else row["v"])

    def apply_all(self) -> list[int]:
        applied: list[int] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            self.ensure_table(conn)
            current = self.current_version(conn)
            for migration in self.migrations:
                if migration.version <= current:
                    continue
                migration.apply(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, datetime('now'))",
                    (migration.version, migration.name),
                )
                applied.append(migration.version)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return applied
