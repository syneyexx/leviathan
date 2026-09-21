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
