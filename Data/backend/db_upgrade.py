"""Domain-aware migration streams + legacy single-DB → 3-DB cutover orchestrator.

Preserves historical migrations 1..LEGACY_HEAD in ``Data.backend.migrations``.
Each canonical DB has an independent ``schema_migrations`` ledger starting at
domain version 1 (baseline materialized from legacy head schema).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Sequence

from Data.backend.migrations import MIGRATIONS, Migration, MigrationError, MigrationRunner
from Data.backend.table_ownership import (
    PER_DATABASE_INFRASTRUCTURE,
    cutover_copy_tables_for,
    ownership_for,
    require_ownership,
    tables_for,
)
from Data.modules.common.database_domains import DatabaseDomain, DatabasePaths
from Data.modules.common.sqlite_policy import ensure_wal, open_sqlite_connection

LEGACY_HEAD_VERSION = max(m.version for m in MIGRATIONS)

DOMAIN_BASELINE_VERSION = 1
DOMAIN_BASELINE_NAME = f"domain_baseline_from_legacy_v{LEGACY_HEAD_VERSION}"

CUTOVER_STATE_TABLE = "db_cutover_state"
CUTOVER_RECEIPT_TABLE = "db_cutover_table_receipts"


class InstallMode(str, Enum):
    FRESH = "FRESH"
    LEGACY_SINGLE = "LEGACY_SINGLE"
    THREE_DB = "THREE_DB"
    AMBIGUOUS = "AMBIGUOUS"


class CutoverPhase(str, Enum):
    DETECTED = "DETECTED"
    LEGACY_UPGRADED = "LEGACY_UPGRADED"
    TARGETS_CREATED = "TARGETS_CREATED"
    COPYING = "COPYING"
    VERIFIED = "VERIFIED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


@dataclass
class DomainMigration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection, DatabaseDomain], None]


def _dm2_market_paper_deployments(conn: sqlite3.Connection, domain: DatabaseDomain) -> None:
    """MARKET domain v2 — durable PaperDeployment table (A3/A4)."""
    if domain is not DatabaseDomain.MARKET:
        return
    from Data.backend.migrations import _m57_market_paper_deployments

    _m57_market_paper_deployments(conn)

def _dm3_market_qualification_authority(conn: sqlite3.Connection, domain: DatabaseDomain) -> None:
    """MARKET domain v3 — QualificationAuthority persistence (Wave 2–3)."""
    if domain is not DatabaseDomain.MARKET:
        return

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_qualification_policies (
            policy_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            policy_hash TEXT NOT NULL UNIQUE,
            policy_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_market_qualification_policies_hash "
        "ON market_qualification_policies(policy_hash)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_market_qualification_policies_name_ver "
        "ON market_qualification_policies(name, version)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_qualification_runs (
            qualification_id TEXT PRIMARY KEY,
            policy_id TEXT NOT NULL,
            experiment_id TEXT,
            learning_run_id TEXT,
            candidate_id TEXT,
            trial_family_id TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            strategy_version INTEGER NOT NULL,
            strategy_hash TEXT NOT NULL,
            source_id TEXT NOT NULL,
            dataset_id TEXT,
            dataset_version_id TEXT,
            dataset_hash TEXT NOT NULL,
            git_sha TEXT NOT NULL,
            code_version TEXT NOT NULL,
            seed INTEGER NOT NULL,
            status TEXT NOT NULL,
            current_gate TEXT,
            decision TEXT,
            blockers_json TEXT NOT NULL DEFAULT '[]',
            warnings_json TEXT NOT NULL DEFAULT '[]',
            provenance_hash TEXT NOT NULL,
            sealed_attempt_id TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_qualification_runs_strategy "
        "ON market_qualification_runs(strategy_id, strategy_version)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_qualification_runs_family "
        "ON market_qualification_runs(trial_family_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_qualification_runs_status "
        "ON market_qualification_runs(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_qualification_runs_experiment "
        "ON market_qualification_runs(experiment_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_qualification_runs_learning "
        "ON market_qualification_runs(learning_run_id)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_qualification_gate_results (
            gate_result_id TEXT PRIMARY KEY,
            qualification_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            state TEXT NOT NULL,
            passed INTEGER NOT NULL,
            methodology TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            blockers_json TEXT NOT NULL,
            warnings_json TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            output_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(qualification_id, gate_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_qualification_gate_results_qid "
        "ON market_qualification_gate_results(qualification_id)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_wfa_folds (
            fold_id TEXT PRIMARY KEY,
            qualification_id TEXT NOT NULL,
            fold_index INTEGER NOT NULL,
            train_start_ts TEXT NOT NULL,
            train_end_ts TEXT NOT NULL,
            validation_start_ts TEXT,
            validation_end_ts TEXT,
            test_start_ts TEXT NOT NULL,
            test_end_ts TEXT NOT NULL,
            purge_bars INTEGER NOT NULL DEFAULT 0,
            embargo_bars INTEGER NOT NULL DEFAULT 0,
            train_run_id TEXT,
            test_run_id TEXT,
            strategy_id TEXT NOT NULL,
            strategy_version INTEGER NOT NULL,
            frozen_params_json TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(qualification_id, fold_index)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_dataset_certifications (
            certification_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            dataset_version_id TEXT NOT NULL,
            dataset_hash TEXT NOT NULL,
            data_type TEXT NOT NULL,
            certification_state TEXT NOT NULL,
            pit_state TEXT NOT NULL,
            survivorship_state TEXT NOT NULL,
            revision_state TEXT NOT NULL,
            corporate_action_state TEXT NOT NULL,
            source_id TEXT NOT NULL,
            license_state TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            certification_hash TEXT NOT NULL UNIQUE,
            certified_at TEXT NOT NULL,
            certified_by TEXT NOT NULL,
            superseded_by TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_dataset_certifications_dataset "
        "ON market_dataset_certifications(dataset_id, dataset_version_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_dataset_certifications_hash "
        "ON market_dataset_certifications(dataset_hash)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_dataset_certifications_state "
        "ON market_dataset_certifications(certification_state)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_strategy_behavior_fingerprints (
            fingerprint_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            strategy_version INTEGER NOT NULL,
            dataset_version_id TEXT NOT NULL,
            signal_hash TEXT NOT NULL,
            position_hash TEXT NOT NULL,
            trade_timing_hash TEXT NOT NULL,
            return_series_hash TEXT NOT NULL,
            feature_set_hash TEXT NOT NULL,
            regime_response_hash TEXT,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(strategy_id, strategy_version, dataset_version_id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_strategy_risk_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            portfolio_id TEXT NOT NULL,
            as_of TEXT NOT NULL,
            strategy_ids_json TEXT NOT NULL,
            sample_count INTEGER NOT NULL,
            covariance_json TEXT NOT NULL,
            correlation_json TEXT NOT NULL,
            risk_contribution_json TEXT NOT NULL,
            methodology TEXT NOT NULL,
            state TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_strategy_risk_snapshots_portfolio "
        "ON market_strategy_risk_snapshots(portfolio_id, as_of)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_execution_calibrations (
            calibration_id TEXT PRIMARY KEY,
            execution_model_id TEXT NOT NULL,
            execution_model_version TEXT NOT NULL,
            source_deployment_ids_json TEXT NOT NULL,
            symbol TEXT,
            provider_id TEXT,
            order_type TEXT,
            size_bucket TEXT,
            regime TEXT,
            sample_count INTEGER NOT NULL,
            parameters_json TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            state TEXT NOT NULL,
            confidence_json TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_execution_calibrations_model "
        "ON market_execution_calibrations(execution_model_id, execution_model_version)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_execution_calibrations_symbol "
        "ON market_execution_calibrations(symbol, provider_id)"
    )

    # Wave 13 table included early so lifecycle can bind to qualification runs.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_strategy_lifecycle (
            strategy_id TEXT NOT NULL,
            strategy_version INTEGER NOT NULL,
            state TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            history_json TEXT NOT NULL DEFAULT '[]',
            notes_json TEXT NOT NULL DEFAULT '[]',
            qualification_id TEXT,
            paper_deployment_id TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(strategy_id, strategy_version)
        )
        """
    )

def _dm4_external_capability_fabric(conn: sqlite3.Connection, domain: DatabaseDomain) -> None:
    """CONTROL domain v4 — external capability fabric tables."""
    if domain is not DatabaseDomain.CONTROL:
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS external_modules (
            module_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            adapter TEXT NOT NULL,
            source_json TEXT NOT NULL DEFAULT '{}',
            desired_state TEXT NOT NULL DEFAULT 'STOPPED',
            runtime_state TEXT NOT NULL DEFAULT 'DISCOVERED',
            active_version_id TEXT,
            last_error TEXT,
            last_used_at TEXT,
            capability_count INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS external_module_versions (
            version_id TEXT PRIMARY KEY,
            module_id TEXT NOT NULL,
            source_ref TEXT,
            resolved_commit TEXT,
            content_hash TEXT,
            install_root TEXT NOT NULL,
            install_strategy_json TEXT NOT NULL DEFAULT '[]',
            dependency_versions_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'INSTALLED',
            installed_at TEXT NOT NULL,
            activated_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(module_id) REFERENCES external_modules(module_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_ext_versions_module
            ON external_module_versions(module_id, installed_at DESC);

        CREATE TABLE IF NOT EXISTS external_process_records (
            module_id TEXT PRIMARY KEY,
            pid INTEGER,
            fingerprint TEXT,
            command_json TEXT NOT NULL DEFAULT '[]',
            cwd TEXT,
            started_at TEXT,
            exit_code INTEGER,
            restart_count INTEGER NOT NULL DEFAULT 0,
            health TEXT NOT NULL DEFAULT 'UNKNOWN',
            stdout_artifact TEXT,
            stderr_artifact TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(module_id) REFERENCES external_modules(module_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS external_skills (
            skill_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            source_repo TEXT,
            source_path TEXT,
            source_ref TEXT,
            version TEXT,
            content_hash TEXT NOT NULL,
            instruction_artifact TEXT,
            resource_refs_json TEXT NOT NULL DEFAULT '[]',
            script_refs_json TEXT NOT NULL DEFAULT '[]',
            required_capabilities_json TEXT NOT NULL DEFAULT '[]',
            trigger_description TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            catalog_only INTEGER NOT NULL DEFAULT 0,
            module_id TEXT,
            imported_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_ext_skills_name ON external_skills(name);
        CREATE INDEX IF NOT EXISTS idx_ext_skills_enabled ON external_skills(enabled, catalog_only);

        CREATE TABLE IF NOT EXISTS external_skill_catalogs (
            catalog_id TEXT PRIMARY KEY,
            module_id TEXT NOT NULL,
            source TEXT NOT NULL,
            entry_count INTEGER NOT NULL DEFAULT 0,
            last_refreshed_at TEXT,
            index_artifact TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(module_id) REFERENCES external_modules(module_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS external_plugin_bindings (
            plugin_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT '0.0.0',
            bindings_json TEXT NOT NULL DEFAULT '[]',
            endpoint TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS external_log_windows (
            module_id TEXT PRIMARY KEY,
            lines_json TEXT NOT NULL DEFAULT '[]',
            byte_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        """
    )

DOMAIN_MIGRATIONS: tuple[DomainMigration, ...] = (
    DomainMigration(
        version=2,
        name="market_paper_deployments",
        apply=_dm2_market_paper_deployments,
    ),
    DomainMigration(
        version=3,
        name="market_qualification_authority",
        apply=_dm3_market_qualification_authority,
    ),
    DomainMigration(
        version=4,
        name="external_capability_fabric",
        apply=_dm4_external_capability_fabric,
    ),
)


@dataclass
class UpgradeReport:
    mode: InstallMode
    phase: CutoverPhase
    legacy_path: str | None
    legacy_schema_version: int | None
    applied_legacy: list[int] = field(default_factory=list)
    domain_versions: dict[str, int] = field(default_factory=dict)
    tables_copied: dict[str, dict[str, int]] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    resumed: bool = False
    completed: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "phase": self.phase.value,
            "legacyPath": self.legacy_path,
            "legacySchemaVersion": self.legacy_schema_version,
            "appliedLegacy": list(self.applied_legacy),
            "domainVersions": dict(self.domain_versions),
            "tablesCopied": dict(self.tables_copied),
            "verification": dict(self.verification),
            "errors": list(self.errors),
            "resumed": self.resumed,
            "completed": self.completed,
            "legacyPreserved": True,
            "legacyIsProductAuthority": False,
        }


class DatabaseUpgradeError(RuntimeError):
    """Fail-closed upgrade / cutover error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def detect_install_mode(paths: DatabasePaths) -> InstallMode:
    control_exists = paths.control.is_file()
    knowledge_exists = paths.knowledge.is_file()
    market_exists = paths.market.is_file()
    legacy_exists = bool(paths.legacy and paths.legacy.is_file())

    canonical_count = sum([control_exists, knowledge_exists, market_exists])
    if canonical_count == 3:
        return InstallMode.THREE_DB
    if canonical_count == 0 and legacy_exists:
        return InstallMode.LEGACY_SINGLE
    if canonical_count == 0 and not legacy_exists:
        return InstallMode.FRESH
    # Partial three-DB set: import-time / supervisor may create CONTROL alone
    # before siblings exist. Empty partials are safe to complete; non-empty
    # conflicting layouts stay fail-closed.
    if 0 < canonical_count < 3:
        existing = [p for p in (paths.control, paths.knowledge, paths.market) if p.is_file()]
        if all(_is_empty_or_infrastructure_only(p) for p in existing):
            if legacy_exists:
                return InstallMode.LEGACY_SINGLE
            return InstallMode.FRESH
        return InstallMode.AMBIGUOUS
    if legacy_exists and canonical_count == 3:
        return InstallMode.THREE_DB
    return InstallMode.AMBIGUOUS


def _is_empty_or_infrastructure_only(path: Path) -> bool:
    """True when a DB file has no durable product rows (safe to re-baseline)."""
    if not path.is_file():
        return True
    try:
        if path.stat().st_size == 0:
            return True
    except OSError:
        return True
    conn = _connect(path)
    try:
        ignore = set(PER_DATABASE_INFRASTRUCTURE) | {
            CUTOVER_STATE_TABLE,
            CUTOVER_RECEIPT_TABLE,
            "sqlite_sequence",
        }
        for name in sorted(_table_names(conn)):
            if name in ignore or name.startswith("sqlite_"):
                continue
            try:
                if _row_count(conn, name) > 0:
                    return False
            except sqlite3.Error:
                return False
        return True
    finally:
        conn.close()


def repair_incompatible_runs_schema(conn: sqlite3.Connection) -> bool:
    """Replace cutover stub ``runs``/``run_events`` with the canonical RunStore schema.

    Returns True when a repair was applied. Empty stub tables are dropped; any
    stub rows are preserved under ``*_upgrade_stub_backup`` names.
    """
    tables = _table_names(conn)
    if "runs" not in tables:
        return False
    run_cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "run_id" in run_cols:
        return False

    def _retire(table: str) -> None:
        if table not in _table_names(conn):
            return
        count = _row_count(conn, table)
        if count > 0:
            backup = f"{table}_upgrade_stub_backup"
            # Avoid colliding with a prior backup from a previous repair attempt.
            if backup in _table_names(conn):
                conn.execute(f'DROP TABLE IF EXISTS "{backup}"')
            conn.execute(f'ALTER TABLE "{table}" RENAME TO "{backup}"')
        else:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')

    _retire("run_events")
    _retire("runs")
    # Recreate canonical schema (also defined in _ensure_runtime_bootstrap_schema).
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            conversation_id TEXT,
            parent_run_id TEXT,
            user_request TEXT NOT NULL,
            state TEXT NOT NULL,
            intent TEXT,
            complexity TEXT,
            selected_model TEXT,
            output TEXT,
            error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_runs_conversation
            ON runs(conversation_id, created_at);
        CREATE TABLE IF NOT EXISTS run_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_run_events_run
            ON run_events(run_id, created_at);
        """
    )
    return True


def repair_incompatible_quality_schema(conn: sqlite3.Connection) -> bool:
    """Replace cutover stub quality_* tables with QualityContractStore schema."""
    tables = _table_names(conn)
    if "quality_contracts" not in tables:
        return False
    cols = {row[1] for row in conn.execute("PRAGMA table_info(quality_contracts)").fetchall()}
    if "run_id" in cols and "version" in cols:
        return False

    def _retire(table: str) -> None:
        if table not in _table_names(conn):
            return
        count = _row_count(conn, table)
        if count > 0:
            backup = f"{table}_upgrade_stub_backup"
            if backup in _table_names(conn):
                conn.execute(f'DROP TABLE IF EXISTS "{backup}"')
            conn.execute(f'ALTER TABLE "{table}" RENAME TO "{backup}"')
        else:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')

    for name in ("quality_acceptances", "quality_verdicts", "quality_contracts"):
        _retire(name)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS quality_contracts (
            contract_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            run_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (contract_id, version)
        );
        CREATE INDEX IF NOT EXISTS idx_quality_contracts_run
            ON quality_contracts(run_id);
        CREATE TABLE IF NOT EXISTS quality_verdicts (
            verdict_id TEXT PRIMARY KEY,
            contract_id TEXT NOT NULL,
            contract_version INTEGER NOT NULL,
            criterion_id TEXT NOT NULL,
            artifact_revision TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_quality_verdicts_contract
            ON quality_verdicts(contract_id, contract_version, artifact_revision);
        CREATE TABLE IF NOT EXISTS quality_acceptances (
            acceptance_id TEXT PRIMARY KEY,
            contract_id TEXT NOT NULL,
            contract_version INTEGER NOT NULL,
            artifact_revision TEXT NOT NULL,
            outcome TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_quality_acceptances_contract
            ON quality_acceptances(contract_id, contract_version);
        """
    )
    return True


def _retire_stub_table(conn: sqlite3.Connection, table: str) -> None:
    if table not in _table_names(conn):
        return
    count = _row_count(conn, table)
    if count > 0:
        backup = f"{table}_upgrade_stub_backup"
        if backup in _table_names(conn):
            conn.execute(f'DROP TABLE IF EXISTS "{backup}"')
        conn.execute(f'ALTER TABLE "{table}" RENAME TO "{backup}"')
    else:
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')


# Fingerprints used by _wave3_table_is_stub (documentation / test helpers).
WAVE3_PRODUCT_TABLES: tuple[str, ...] = (
    "provider_stream_events",
    "intelligence_assimilation_receipts",
    "knowledge_commit_receipts",
    "source_ingestion_commit_records",
    "dataset_commit_index_rows",
    "market_sim_commit_batches",
)


def _wave3_table_is_stub(conn: sqlite3.Connection, table: str) -> bool:
    """True when table exists but matches the incompatible bootstrap stub shape."""
    if table not in _table_names(conn):
        return False
    cols = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    if table == "provider_stream_events":
        return "stream_id" in cols or ("job_id" not in cols and "sequence" not in cols)
    if table == "intelligence_assimilation_receipts":
        return "subject_id" in cols or "kind" not in cols
    if table == "knowledge_commit_receipts":
        return "receipt_id" in cols or "artifact_id" not in cols
    if table == "source_ingestion_commit_records":
        return "container_id" in cols or "source_id" not in cols
    if table == "dataset_commit_index_rows":
        # Stub: row_id PK alone + created_at, missing commit_id/applied_at.
        return "commit_id" not in cols or "applied_at" not in cols
    if table == "market_sim_commit_batches":
        return "batch_id" in cols or "kind" not in cols
    return False


_WAVE3_CANONICAL_DDL: dict[str, str] = {
    "provider_stream_events": """
        CREATE TABLE IF NOT EXISTS provider_stream_events (
            job_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            correlation_id TEXT,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (job_id, sequence)
        );
        CREATE INDEX IF NOT EXISTS idx_provider_stream_job
            ON provider_stream_events(job_id, sequence);
    """,
    "intelligence_assimilation_receipts": """
        CREATE TABLE IF NOT EXISTS intelligence_assimilation_receipts (
            receipt_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ok INTEGER NOT NULL,
            success_count INTEGER NOT NULL,
            failure_count INTEGER NOT NULL,
            skipped_count INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        );
    """,
    "knowledge_commit_receipts": """
        CREATE TABLE IF NOT EXISTS knowledge_commit_receipts (
            commit_id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL,
            idempotency_key TEXT,
            receipt_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_commit_idempotency
            ON knowledge_commit_receipts(idempotency_key)
            WHERE idempotency_key IS NOT NULL;
    """,
    "source_ingestion_commit_records": """
        CREATE TABLE IF NOT EXISTS source_ingestion_commit_records (
            source_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            commit_id TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (source_id, record_id)
        );
    """,
    "dataset_commit_index_rows": """
        CREATE TABLE IF NOT EXISTS dataset_commit_index_rows (
            dataset_id TEXT NOT NULL,
            row_id TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            commit_id TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (dataset_id, row_id)
        );
    """,
    "market_sim_commit_batches": """
        CREATE TABLE IF NOT EXISTS market_sim_commit_batches (
            run_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            commit_id TEXT NOT NULL,
            sequence_number INTEGER NOT NULL DEFAULT 0,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (run_id, record_id, kind)
        );
    """,
}

# Public alias — stores/handlers/bootstrap must reuse this single source.
WAVE3_CANONICAL_DDL: dict[str, str] = _WAVE3_CANONICAL_DDL


def wave3_canonical_ddl(table: str) -> str:
    """Return canonical DDL script for one WAVE3 product table."""
    try:
        return _WAVE3_CANONICAL_DDL[table]
    except KeyError as exc:
        raise KeyError(f"Unknown WAVE3 table: {table!r}") from exc


def apply_wave3_canonical_ddl(
    conn: sqlite3.Connection,
    *tables: str,
) -> None:
    """Execute canonical DDL for the given WAVE3 tables (default: all six)."""
    targets = tables or WAVE3_PRODUCT_TABLES
    for table in targets:
        conn.executescript(_WAVE3_CANONICAL_DDL[table])


def repair_incompatible_wave3_product_schemas(conn: sqlite3.Connection) -> list[str]:
    """Replace SCHEMA-001..006 bootstrap stubs with canonical store schemas.

    Bounded migration compatibility only — not a permanent parallel schema engine.
    Returns names of tables that were repaired.
    """
    repaired: list[str] = []
    for table, ddl in _WAVE3_CANONICAL_DDL.items():
        if not _wave3_table_is_stub(conn, table):
            continue
        _retire_stub_table(conn, table)
        conn.executescript(ddl)
        repaired.append(table)
    return repaired


def repair_domain_wave3_schemas(paths: DatabasePaths) -> dict[str, list[str]]:
    """Apply WAVE3 stub repairs on each canonical domain DB that owns the tables."""
    out: dict[str, list[str]] = {}
    for domain, path in paths:
        if not path.is_file():
            continue
        conn = _connect(path)
        try:
            owned = {t for t in _WAVE3_CANONICAL_DDL if ownership_for(t) is domain}
            repaired: list[str] = []
            for table in owned:
                if not _wave3_table_is_stub(conn, table):
                    continue
                _retire_stub_table(conn, table)
                conn.executescript(_WAVE3_CANONICAL_DDL[table])
                repaired.append(table)
            if repaired:
                conn.commit()
            out[domain.value] = repaired
        finally:
            conn.close()
    return out


def _connect(path: Path, *, set_wal: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_sqlite_connection(path, set_wal=set_wal)
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(r[0] if not isinstance(r, sqlite3.Row) else r["name"]) for r in rows}


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f'SELECT COUNT(*) AS c FROM "{table}"').fetchone()
    return int(row[0] if not isinstance(row, sqlite3.Row) else row["c"])


# Misplaced-table reconciliation actions (UNKNOWN => BLOCK, never MIGRATE).
MISPLACED_SKIP_EMPTY = "SKIP_EMPTY"
MISPLACED_MIGRATE = "MIGRATE"
MISPLACED_EQUIVALENT_RETIRE = "EQUIVALENT_RETIRE"
MISPLACED_BLOCK_UNKNOWN = "BLOCK_UNKNOWN"
MISPLACED_BLOCK_UNREADABLE = "BLOCK_UNREADABLE"
MISPLACED_BLOCK_MISSING_TARGET = "BLOCK_MISSING_TARGET"
MISPLACED_BLOCK_SCHEMA_MISMATCH = "BLOCK_SCHEMA_MISMATCH"
MISPLACED_BLOCK_CONFLICT = "BLOCK_CONFLICT"
MISPLACED_BLOCK_OPERATOR_REVIEW = "BLOCK_OPERATOR_REVIEW"

_MISPLACED_BLOCK_ACTIONS = frozenset(
    {
        MISPLACED_BLOCK_UNKNOWN,
        MISPLACED_BLOCK_UNREADABLE,
        MISPLACED_BLOCK_MISSING_TARGET,
        MISPLACED_BLOCK_SCHEMA_MISMATCH,
        MISPLACED_BLOCK_CONFLICT,
        MISPLACED_BLOCK_OPERATOR_REVIEW,
    }
)

MISPLACED_JOURNAL_TABLE = "misplaced_reconcile_journal"


@dataclass
class MisplacedTableFinding:
    table: str
    found_in: DatabaseDomain
    owned_by: DatabaseDomain
    row_count: int
    target_row_count: int | None
    action: str
    detail: str = ""


@dataclass
class MisplacedReconcileReport:
    findings: list[MisplacedTableFinding] = field(default_factory=list)
    migrated: list[str] = field(default_factory=list)
    retired_equivalent: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    receipt_path: str | None = None
    completed: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "findings": [
                {
                    "table": f.table,
                    "found_in": f.found_in.value,
                    "owned_by": f.owned_by.value,
                    "row_count": f.row_count,
                    "target_row_count": f.target_row_count,
                    "action": f.action,
                    "detail": f.detail,
                }
                for f in self.findings
            ],
            "migrated": list(self.migrated),
            "retired_equivalent": list(self.retired_equivalent),
            "blocked": list(self.blocked),
            "skipped": list(self.skipped),
            "errors": list(self.errors),
            "completed": self.completed,
            "receipt_path": self.receipt_path,
        }


def _ensure_misplaced_journal(control_conn: sqlite3.Connection) -> None:
    control_conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MISPLACED_JOURNAL_TABLE} (
            table_name TEXT NOT NULL,
            source_domain TEXT NOT NULL,
            target_domain TEXT NOT NULL,
            phase TEXT NOT NULL,
            source_count INTEGER,
            target_count INTEGER,
            checksum TEXT,
            detail TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (table_name, source_domain, target_domain)
        )
        """
    )


def _journal_misplaced(
    control_path: Path,
    *,
    table: str,
    source_domain: DatabaseDomain,
    target_domain: DatabaseDomain,
    phase: str,
    source_count: int | None = None,
    target_count: int | None = None,
    checksum: str | None = None,
    detail: str = "",
) -> None:
    conn = _connect(control_path)
    try:
        _ensure_misplaced_journal(conn)
        conn.execute(
            f"""
            INSERT INTO {MISPLACED_JOURNAL_TABLE}(
                table_name, source_domain, target_domain, phase,
                source_count, target_count, checksum, detail, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(table_name, source_domain, target_domain) DO UPDATE SET
                phase=excluded.phase,
                source_count=excluded.source_count,
                target_count=excluded.target_count,
                checksum=excluded.checksum,
                detail=excluded.detail,
                updated_at=excluded.updated_at
            """,
            (
                table,
                source_domain.value,
                target_domain.value,
                phase,
                source_count,
                target_count,
                checksum,
                detail,
                utc_now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _pragma_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(r[1]) for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def detect_misplaced_product_tables(paths: DatabasePaths) -> list[MisplacedTableFinding]:
    """Detect canonical product tables materialised in the wrong domain DB.

    Invariant: UNKNOWN / ERROR / CONFLICT => BLOCK. Never MIGRATE on uncertainty.
    """
    from Data.backend.table_ownership import is_fts_shadow_table

    findings: list[MisplacedTableFinding] = []
    for found_domain, found_path in paths.all_canonical():
        if not found_path.is_file():
            continue
        conn = _connect(found_path)
        try:
            for name in sorted(_table_names(conn)):
                if is_fts_shadow_table(name):
                    continue
                owned = ownership_for(name)
                if owned is None or owned is found_domain:
                    continue
                try:
                    row_count = _row_count(conn, name)
                except sqlite3.Error as exc:
                    findings.append(
                        MisplacedTableFinding(
                            table=name,
                            found_in=found_domain,
                            owned_by=owned,
                            row_count=-1,
                            target_row_count=None,
                            action=MISPLACED_BLOCK_UNKNOWN,
                            detail=f"source_unreadable:{type(exc).__name__}",
                        )
                    )
                    continue

                target_path = paths.path_for(owned)
                if not target_path.is_file():
                    findings.append(
                        MisplacedTableFinding(
                            table=name,
                            found_in=found_domain,
                            owned_by=owned,
                            row_count=row_count,
                            target_row_count=None,
                            action=MISPLACED_BLOCK_MISSING_TARGET,
                            detail="canonical_target_db_missing",
                        )
                    )
                    continue

                target_count: int | None
                tconn = _connect(target_path)
                try:
                    if name in _table_names(tconn):
                        try:
                            target_count = _row_count(tconn, name)
                        except sqlite3.Error as exc:
                            findings.append(
                                MisplacedTableFinding(
                                    table=name,
                                    found_in=found_domain,
                                    owned_by=owned,
                                    row_count=row_count,
                                    target_row_count=-1,
                                    action=MISPLACED_BLOCK_UNREADABLE,
                                    detail=f"target_unreadable:{type(exc).__name__}",
                                )
                            )
                            continue
                    else:
                        target_count = 0
                finally:
                    tconn.close()

                if row_count < 0:
                    action, detail = MISPLACED_BLOCK_UNKNOWN, "source_count_unknown"
                elif row_count == 0:
                    action, detail = MISPLACED_SKIP_EMPTY, "source_empty"
                elif target_count is None:
                    action, detail = MISPLACED_BLOCK_MISSING_TARGET, "target_count_unavailable"
                elif target_count < 0:
                    action, detail = MISPLACED_BLOCK_UNREADABLE, "target_count_unknown"
                elif target_count > 0:
                    # Defer equivalence vs conflict classification to reconcile
                    # (needs open connections + checksums).
                    action, detail = MISPLACED_BLOCK_OPERATOR_REVIEW, "target_nonempty_pending_classify"
                else:
                    action, detail = MISPLACED_MIGRATE, "target_empty_or_absent_table"

                findings.append(
                    MisplacedTableFinding(
                        table=name,
                        found_in=found_domain,
                        owned_by=owned,
                        row_count=row_count,
                        target_row_count=target_count,
                        action=action,
                        detail=detail,
                    )
                )
        finally:
            conn.close()
    return findings


def _ensure_canonical_destination_table(dst_conn: sqlite3.Connection, table: str) -> bool:
    """Ensure destination table exists from canonical DDL — never promote source stub DDL.

    Returns True when the destination table exists and is usable.
    """
    if table in _table_names(dst_conn):
        if table in _WAVE3_CANONICAL_DDL and _wave3_table_is_stub(dst_conn, table):
            _retire_stub_table(dst_conn, table)
            dst_conn.executescript(_WAVE3_CANONICAL_DDL[table])
        return table in _table_names(dst_conn)
    ddl = _WAVE3_CANONICAL_DDL.get(table)
    if ddl:
        dst_conn.executescript(ddl)
        return table in _table_names(dst_conn)
    return False


def _compatible_columns(src_conn: sqlite3.Connection, dst_conn: sqlite3.Connection, table: str) -> list[str]:
    src_cols = _pragma_columns(src_conn, table)
    dst_cols = _pragma_columns(dst_conn, table)
    if not src_cols or not dst_cols:
        return []
    dst_set = set(dst_cols)
    return [c for c in src_cols if c in dst_set]


def _classify_nonempty_overlap(
    src_conn: sqlite3.Connection,
    dst_conn: sqlite3.Connection,
    table: str,
) -> tuple[str, str]:
    """Return (action, detail) when both source and target have rows."""
    try:
        src_count = _row_count(src_conn, table)
        dst_count = _row_count(dst_conn, table)
        src_hash = _content_checksum(src_conn, table)
        dst_hash = _content_checksum(dst_conn, table)
    except sqlite3.Error as exc:
        return MISPLACED_BLOCK_UNREADABLE, f"overlap_unreadable:{type(exc).__name__}"
    if src_hash == "unavailable" or dst_hash == "unavailable":
        return MISPLACED_BLOCK_UNKNOWN, "checksum_unavailable"
    if src_count == dst_count and src_hash == dst_hash:
        return MISPLACED_EQUIVALENT_RETIRE, "verified_equivalent"
    return (
        MISPLACED_BLOCK_OPERATOR_REVIEW,
        f"conflict_src={src_count}:{src_hash[:12]} dst={dst_count}:{dst_hash[:12]}",
    )


def _copy_misplaced_verified(
    src_conn: sqlite3.Connection,
    dst_conn: sqlite3.Connection,
    table: str,
) -> dict[str, Any]:
    """Copy source -> destination with explicit columns; verify before return.

    Does NOT drop the source. Uses plain INSERT (not OR IGNORE) so conflicts surface.
    """
    if not _ensure_canonical_destination_table(dst_conn, table):
        raise DatabaseUpgradeError(
            f"no canonical schema authority for misplaced table {table}; refusing source DDL promotion"
        )
    cols = _compatible_columns(src_conn, dst_conn, table)
    if not cols:
        raise DatabaseUpgradeError(f"schema mismatch for {table}: no compatible columns")
    src_only = set(_pragma_columns(src_conn, table)) - set(cols)
    if src_only:
        # Required columns missing on destination → block rather than silent drop.
        dst_required = {
            str(r[1])
            for r in dst_conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            if int(r[3] or 0) == 1 and r[4] is None and int(r[5] or 0) == 0
        }
        missing_required = dst_required - set(cols)
        if missing_required:
            raise DatabaseUpgradeError(
                f"schema mismatch for {table}: destination NOT NULL cols missing from source: "
                f"{sorted(missing_required)}"
            )
    col_list = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    rows = src_conn.execute(f'SELECT {col_list} FROM "{table}"').fetchall()
    before = _row_count(dst_conn, table)
    try:
        dst_conn.executemany(
            f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})',
            [tuple(row) for row in rows],
        )
    except sqlite3.IntegrityError as exc:
        raise DatabaseUpgradeError(
            f"PK/unique conflict copying {table}: {exc}; operator review required"
        ) from exc
    after = _row_count(dst_conn, table)
    if after - before != len(rows):
        raise DatabaseUpgradeError(
            f"row copy incomplete for {table}: attempted={len(rows)} applied={after - before}"
        )
    # Source still present — verify destination gained exact payload vs source projection.
    src_count = _row_count(src_conn, table)
    if after < src_count and before == 0:
        raise DatabaseUpgradeError(
            f"count mismatch for {table}: source={src_count} target={after}"
        )
    return {
        "table": table,
        "columns": cols,
        "sourceCount": src_count,
        "targetCount": after,
        "copied": len(rows),
        "checksum": _content_checksum(dst_conn, table),
    }


def reconcile_misplaced_product_tables(
    paths: DatabasePaths,
    *,
    apply: bool = True,
    receipt_dir: Path | None = None,
) -> MisplacedReconcileReport:
    """No-loss misplaced-table reconciliation.

    - UNKNOWN / unreadable / schema mismatch / conflict => BLOCK (never DROP)
    - MIGRATE only after verified copy into canonical destination schema
    - Source DROP only after verification + durable journal phase COPIED_VERIFIED
    """
    report = MisplacedReconcileReport()
    findings = detect_misplaced_product_tables(paths)
    report.findings = findings

    for finding in findings:
        if finding.action == MISPLACED_SKIP_EMPTY:
            report.skipped.append(finding.table)
            # Empty wrong-domain tables may be dropped safely when applying.
            if apply:
                src = paths.path_for(finding.found_in)
                try:
                    sconn = _connect(src)
                    try:
                        sconn.execute(f'DROP TABLE IF EXISTS "{finding.table}"')
                        sconn.commit()
                    finally:
                        sconn.close()
                except sqlite3.Error as exc:
                    report.errors.append(f"{finding.table}: empty_drop_failed:{exc}")
                    report.blocked.append(finding.table)
            continue

        if finding.action in _MISPLACED_BLOCK_ACTIONS and finding.action != MISPLACED_BLOCK_OPERATOR_REVIEW:
            report.blocked.append(finding.table)
            report.errors.append(f"{finding.table}:{finding.action}:{finding.detail}")
            continue

        src = paths.path_for(finding.found_in)
        dst = paths.path_for(finding.owned_by)
        if not apply:
            if finding.action == MISPLACED_MIGRATE:
                continue
            if finding.action == MISPLACED_BLOCK_OPERATOR_REVIEW:
                report.blocked.append(finding.table)
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        src_conn = _connect(src)
        dst_conn = _connect(dst)
        try:
            # Reclassify overlap now that both DBs are open.
            action = finding.action
            detail = finding.detail
            if action == MISPLACED_BLOCK_OPERATOR_REVIEW and finding.table in _table_names(dst_conn):
                action, detail = _classify_nonempty_overlap(src_conn, dst_conn, finding.table)
                finding.action = action
                finding.detail = detail

            if action == MISPLACED_EQUIVALENT_RETIRE:
                _journal_misplaced(
                    paths.control,
                    table=finding.table,
                    source_domain=finding.found_in,
                    target_domain=finding.owned_by,
                    phase="EQUIVALENT_VERIFIED",
                    source_count=finding.row_count,
                    target_count=finding.target_row_count,
                    checksum=_content_checksum(dst_conn, finding.table),
                    detail=detail,
                )
                src_conn.execute(f'DROP TABLE IF EXISTS "{finding.table}"')
                src_conn.commit()
                _journal_misplaced(
                    paths.control,
                    table=finding.table,
                    source_domain=finding.found_in,
                    target_domain=finding.owned_by,
                    phase="SOURCE_RETIRED",
                    source_count=0,
                    target_count=finding.target_row_count,
                    detail="equivalent_source_retired",
                )
                report.retired_equivalent.append(finding.table)
                continue

            if action != MISPLACED_MIGRATE:
                report.blocked.append(finding.table)
                report.errors.append(f"{finding.table}:{action}:{detail}")
                continue

            _journal_misplaced(
                paths.control,
                table=finding.table,
                source_domain=finding.found_in,
                target_domain=finding.owned_by,
                phase="COPY_STARTED",
                source_count=finding.row_count,
                target_count=finding.target_row_count or 0,
            )
            try:
                meta = _copy_misplaced_verified(src_conn, dst_conn, finding.table)
                dst_conn.commit()
            except (sqlite3.Error, DatabaseUpgradeError) as exc:
                try:
                    dst_conn.rollback()
                except sqlite3.Error:
                    pass
                _journal_misplaced(
                    paths.control,
                    table=finding.table,
                    source_domain=finding.found_in,
                    target_domain=finding.owned_by,
                    phase="COPY_FAILED",
                    source_count=finding.row_count,
                    detail=str(exc)[:500],
                )
                report.blocked.append(finding.table)
                report.errors.append(f"{finding.table}:copy_failed:{exc}")
                continue

            _journal_misplaced(
                paths.control,
                table=finding.table,
                source_domain=finding.found_in,
                target_domain=finding.owned_by,
                phase="COPIED_VERIFIED",
                source_count=int(meta["sourceCount"]),
                target_count=int(meta["targetCount"]),
                checksum=str(meta.get("checksum") or ""),
            )
            # Retire source only after verified destination.
            src_conn.execute(f'DROP TABLE IF EXISTS "{finding.table}"')
            src_conn.commit()
            _journal_misplaced(
                paths.control,
                table=finding.table,
                source_domain=finding.found_in,
                target_domain=finding.owned_by,
                phase="SOURCE_RETIRED",
                source_count=0,
                target_count=int(meta["targetCount"]),
                checksum=str(meta.get("checksum") or ""),
            )
            report.migrated.append(finding.table)
        finally:
            src_conn.close()
            dst_conn.close()

    report.completed = not report.blocked and not report.errors
    receipt_dir = receipt_dir or paths.control.parent
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = receipt_dir / "misplaced_table_reconcile_receipt.json"
    receipt.write_text(json.dumps(report.public_dict(), indent=2), encoding="utf-8")
    report.receipt_path = str(receipt)
    return report


def _content_checksum(conn: sqlite3.Connection, table: str, *, limit: int = 50_000) -> str:
    """Bounded deterministic checksum of row payloads for verification."""
    try:
        rows = conn.execute(f'SELECT * FROM "{table}" LIMIT ?', (limit,)).fetchall()
    except sqlite3.Error:
        return "unavailable"
    digest = hashlib.sha256()
    digest.update(table.encode("utf-8"))
    digest.update(str(len(rows)).encode("utf-8"))
    for row in rows:
        if isinstance(row, sqlite3.Row):
            payload = tuple(row)
        else:
            payload = tuple(row)
        digest.update(repr(payload).encode("utf-8", errors="replace"))
    return digest.hexdigest()


def _ensure_runtime_bootstrap_schema(conn: sqlite3.Connection) -> None:
    """Create tables historically owned by runtime _ensure_schema helpers."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id, id);

        -- Canonical RunStore schema (must match Data.modules.run.store.RunStore).
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            conversation_id TEXT,
            parent_run_id TEXT,
            user_request TEXT NOT NULL,
            state TEXT NOT NULL,
            intent TEXT,
            complexity TEXT,
            selected_model TEXT,
            output TEXT,
            error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_runs_conversation
            ON runs(conversation_id, created_at);
        CREATE TABLE IF NOT EXISTS run_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_run_events_run
            ON run_events(run_id, created_at);

        CREATE TABLE IF NOT EXISTS worker_pool_desired (
            pool_id TEXT PRIMARY KEY,
            desired_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT '',
            updated_by TEXT
        );

        -- Canonical QualityContractStore schema.
        CREATE TABLE IF NOT EXISTS quality_contracts (
            contract_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            run_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (contract_id, version)
        );
        CREATE INDEX IF NOT EXISTS idx_quality_contracts_run
            ON quality_contracts(run_id);
        CREATE TABLE IF NOT EXISTS quality_verdicts (
            verdict_id TEXT PRIMARY KEY,
            contract_id TEXT NOT NULL,
            contract_version INTEGER NOT NULL,
            criterion_id TEXT NOT NULL,
            artifact_revision TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_quality_verdicts_contract
            ON quality_verdicts(contract_id, contract_version, artifact_revision);
        CREATE TABLE IF NOT EXISTS quality_acceptances (
            acceptance_id TEXT PRIMARY KEY,
            contract_id TEXT NOT NULL,
            contract_version INTEGER NOT NULL,
            artifact_revision TEXT NOT NULL,
            outcome TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_quality_acceptances_contract
            ON quality_acceptances(contract_id, contract_version);
        """
    )
    # WAVE 24: single schema authority — reuse _WAVE3_CANONICAL_DDL (no duplicated strings).
    apply_wave3_canonical_ddl(conn)
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
            USING fts5(document_id UNINDEXED, title, content)
            """
        )
    except sqlite3.OperationalError:
        pass


def _ensure_cutover_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CUTOVER_STATE_TABLE} (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CUTOVER_RECEIPT_TABLE} (
            table_name TEXT PRIMARY KEY,
            domain TEXT NOT NULL,
            source_count INTEGER NOT NULL,
            target_count INTEGER NOT NULL,
            checksum TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _cutover_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        f"SELECT value FROM {CUTOVER_STATE_TABLE} WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0] if not isinstance(row, sqlite3.Row) else row["value"])


def _cutover_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        f"""
        INSERT INTO {CUTOVER_STATE_TABLE}(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, utc_now()),
    )


def materialize_full_schema_template() -> Path:
    """Build a temporary DB at legacy head + runtime bootstrap tables."""
    tmp = tempfile.NamedTemporaryFile(prefix="leviathan_schema_", suffix=".db", delete=False)
    tmp.close()
    path = Path(tmp.name)
    MigrationRunner(path).apply_all()
    conn = _connect(path, set_wal=True)
    try:
        _ensure_runtime_bootstrap_schema(conn)
        ensure_wal(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _copy_schema_objects(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    tables: set[str],
) -> None:
    """Copy CREATE TABLE / INDEX / TRIGGER SQL for selected tables."""
    existing = _table_names(target)
    for table in sorted(tables):
        if table in existing:
            continue
        row = source.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        if row is None:
            continue
        sql = row[0] if not isinstance(row, sqlite3.Row) else row["sql"]
        if not sql:
            continue
        try:
            target.execute(sql)
        except sqlite3.OperationalError as exc:
            if "already exists" not in str(exc).lower():
                raise

    # Indexes / triggers belonging to those tables.
    for obj_type in ("index", "trigger"):
        rows = source.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = ? AND sql IS NOT NULL",
            (obj_type,),
        ).fetchall()
        for row in rows:
            name = str(row[0] if not isinstance(row, sqlite3.Row) else row["name"])
            tbl = str(row[1] if not isinstance(row, sqlite3.Row) else row["tbl_name"])
            sql = row[2] if not isinstance(row, sqlite3.Row) else row["sql"]
            if tbl not in tables:
                continue
            if name.startswith("sqlite_"):
                continue
            try:
                target.execute(sql)
            except sqlite3.OperationalError:
                # Index may already exist from CREATE TABLE IF NOT EXISTS path.
                pass


def _seed_domain_infrastructure(conn: sqlite3.Connection, domain: DatabaseDomain) -> None:
    """Ensure lane-local commit receipts + schema_migrations exist."""
    runner = MigrationRunner(Path(":memory:"))  # for ensure_table helper only
    # Reuse ensure_table SQL without touching memory path.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS commit_receipts (
            commit_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL,
            operation TEXT NOT NULL,
            domain TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            worker_id TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(idempotency_key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS commit_batches (
            batch_id TEXT PRIMARY KEY,
            commit_id TEXT NOT NULL,
            batch_index INTEGER NOT NULL DEFAULT 0,
            batch_count INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT '',
            applied_at TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    if domain is DatabaseDomain.CONTROL:
        _ensure_cutover_tables(conn)
    _ = runner  # silence unused in some linters


def apply_domain_baseline(path: Path, domain: DatabaseDomain, *, template: Path) -> list[int]:
    """Create domain DB schema from template; record domain migration v1."""
    path.parent.mkdir(parents=True, exist_ok=True)
    src = _connect(template)
    dst = _connect(path, set_wal=True)
    applied: list[int] = []
    try:
        _seed_domain_infrastructure(dst, domain)
        current = MigrationRunner(path).current_version(dst)
        if current >= DOMAIN_BASELINE_VERSION:
            return applied

        owned = set(tables_for(domain))
        # Always materialize product tables for the domain (excluding cutover-only extras
        # that are created by _seed_domain_infrastructure).
        owned |= {
            t
            for t in cutover_copy_tables_for(domain)
            if t not in {CUTOVER_STATE_TABLE, CUTOVER_RECEIPT_TABLE}
        }
        # Include FTS for knowledge.
        if domain is DatabaseDomain.KNOWLEDGE:
            owned.add("knowledge_fts")
        # Do not copy schema_migrations from template.
        owned.discard("schema_migrations")

        present = _table_names(src)
        to_copy = {t for t in owned if t in present}
        _copy_schema_objects(src, dst, to_copy)

        # Ensure infrastructure even if template lacked commit tables somehow.
        _seed_domain_infrastructure(dst, domain)

        dst.execute(
            "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
            (DOMAIN_BASELINE_VERSION, DOMAIN_BASELINE_NAME, utc_now()),
        )
        ensure_wal(dst)
        dst.commit()
        applied.append(DOMAIN_BASELINE_VERSION)
        return applied
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()


def domain_schema_version(path: Path) -> int:
    if not path.is_file():
        return 0
    conn = _connect(path)
    try:
        return MigrationRunner(path).current_version(conn)
    finally:
        conn.close()


def apply_pending_domain_migrations(path: Path, domain: DatabaseDomain) -> list[int]:
    """Apply DOMAIN_MIGRATIONS after baseline. Idempotent; fail-closed on gaps."""
    if not path.is_file():
        return []
    applied: list[int] = []
    conn = _connect(path, set_wal=True)
    try:
        runner = MigrationRunner(path)
        runner.ensure_table(conn)
        current = runner.current_version(conn)
        if current < DOMAIN_BASELINE_VERSION:
            return applied
        for migration in sorted(DOMAIN_MIGRATIONS, key=lambda m: m.version):
            if migration.version <= current:
                continue
            if migration.version != current + 1:
                raise DatabaseUpgradeError(
                    f"{domain.value} domain migration gap: current={current}, "
                    f"next={migration.version}"
                )
            migration.apply(conn, domain)
            conn.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, utc_now()),
            )
            applied.append(migration.version)
            current = migration.version
        conn.commit()
        return applied
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _copy_table_rows(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
) -> int:
    if table not in _table_names(source):
        return 0
    if table not in _table_names(target):
        # Create missing table from source schema.
        row = source.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        if row is None or not (row[0] if not isinstance(row, sqlite3.Row) else row["sql"]):
            return 0
        sql = row[0] if not isinstance(row, sqlite3.Row) else row["sql"]
        target.execute(sql)

    source_count = _row_count(source, table)
    target_count = _row_count(target, table)
    if target_count == source_count and source_count > 0:
        # Idempotent: already copied.
        return target_count
    if target_count > 0 and target_count != source_count:
        raise DatabaseUpgradeError(
            f"table {table}: target already has {target_count} rows but source has {source_count}"
        )
    if source_count == 0:
        return 0

    cols = [
        r[1] if not isinstance(r, sqlite3.Row) else r["name"]
        for r in source.execute(f'PRAGMA table_info("{table}")').fetchall()
    ]
    if not cols:
        return 0
    col_list = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    rows = source.execute(f'SELECT {col_list} FROM "{table}"').fetchall()
    target.executemany(
        f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})',
        [tuple(row) for row in rows],
    )
    return len(rows)


def _verify_copy(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
) -> dict[str, Any]:
    src_count = _row_count(source, table) if table in _table_names(source) else 0
    dst_count = _row_count(target, table) if table in _table_names(target) else 0
    if src_count != dst_count:
        raise DatabaseUpgradeError(
            f"count mismatch for {table}: source={src_count} target={dst_count}"
        )
    src_hash = _content_checksum(source, table) if src_count else "empty"
    dst_hash = _content_checksum(target, table) if dst_count else "empty"
    if src_hash != dst_hash:
        raise DatabaseUpgradeError(
            f"checksum mismatch for {table}: source={src_hash} target={dst_hash}"
        )
    return {
        "table": table,
        "sourceCount": src_count,
        "targetCount": dst_count,
        "checksum": src_hash,
    }


def copy_legacy_to_domain(
    legacy: Path,
    target: Path,
    domain: DatabaseDomain,
    *,
    receipt_conn: sqlite3.Connection | None = None,
    receipt_db_path: Path | None = None,
) -> dict[str, int]:
    """Idempotently copy owned tables from legacy DB into a domain DB."""
    from Data.backend.table_ownership import is_fts_shadow_table

    src = _connect(legacy)
    close_dst = True
    if (
        receipt_conn is not None
        and receipt_db_path is not None
        and Path(receipt_db_path).resolve() == Path(target).resolve()
    ):
        dst = receipt_conn
        close_dst = False
    else:
        dst = _connect(target)
    copied: dict[str, int] = {}
    try:
        tables = sorted(cutover_copy_tables_for(domain))
        present = _table_names(src)
        for table in tables:
            if table in PER_DATABASE_INFRASTRUCTURE and domain is not DatabaseDomain.CONTROL:
                continue
            if table in {CUTOVER_STATE_TABLE, CUTOVER_RECEIPT_TABLE}:
                continue
            if is_fts_shadow_table(table):
                continue
            if table not in present:
                continue
            # FTS virtual tables: recreate schema only; content rebuilt from base tables.
            if table.endswith("_fts") or table in {"knowledge_fts", "knowledge_chunk_fts", "atlas_fts", "memory_fts"}:
                if table not in _table_names(dst):
                    row = src.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
                        (table,),
                    ).fetchone()
                    sql = None if row is None else (row[0] if not isinstance(row, sqlite3.Row) else row["sql"])
                    if sql:
                        try:
                            dst.execute(sql)
                        except sqlite3.OperationalError:
                            pass
                copied[table] = 0
                continue
            count = _copy_table_rows(src, dst, table)
            _verify_copy(src, dst, table)
            copied[table] = count
            if receipt_conn is not None:
                receipt_conn.execute(
                    f"""
                    INSERT INTO {CUTOVER_RECEIPT_TABLE}
                        (table_name, domain, source_count, target_count, checksum, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(table_name) DO UPDATE SET
                        domain=excluded.domain,
                        source_count=excluded.source_count,
                        target_count=excluded.target_count,
                        checksum=excluded.checksum,
                        status=excluded.status,
                        updated_at=excluded.updated_at
                    """,
                    (
                        table,
                        domain.value,
                        count,
                        count,
                        _content_checksum(dst, table) if count else "empty",
                        "COPIED",
                        utc_now(),
                    ),
                )
        if close_dst:
            dst.commit()
        if receipt_conn is not None:
            receipt_conn.commit()
        return copied
    except Exception:
        if close_dst:
            try:
                dst.rollback()
            except Exception:  # noqa: BLE001
                pass
        raise
    finally:
        src.close()
        if close_dst:
            dst.close()


def classify_unmapped_legacy_tables(legacy: Path) -> list[str]:
    """Return user tables in legacy that lack ownership classification."""
    from Data.backend.table_ownership import EPHEMERAL_OR_NON_PRODUCT, is_fts_shadow_table

    conn = _connect(legacy)
    try:
        unknown: list[str] = []
        for name in sorted(_table_names(conn)):
            if name in PER_DATABASE_INFRASTRUCTURE:
                continue
            if name in {CUTOVER_STATE_TABLE, CUTOVER_RECEIPT_TABLE}:
                continue
            if name.startswith("sqlite_"):
                continue
            if name in EPHEMERAL_OR_NON_PRODUCT or is_fts_shadow_table(name):
                continue
            try:
                domain = ownership_for(name)
            except Exception as exc:  # noqa: BLE001
                unknown.append(f"{name} ({exc})")
                continue
            if domain is None:
                unknown.append(name)
        return unknown
    finally:
        conn.close()


def _finalize_upgrade_report(report: UpgradeReport) -> UpgradeReport:
    """COMPLETE is forbidden while errors/blockers remain."""
    if report.errors:
        report.completed = False
        if report.phase is CutoverPhase.COMPLETE:
            report.phase = CutoverPhase.FAILED
    return report


def upgrade_all_databases(paths: DatabasePaths) -> UpgradeReport:
    """Canonical entrypoint: fresh install, legacy cutover, or 3-DB migrate."""
    mode = detect_install_mode(paths)
    report = UpgradeReport(
        mode=mode,
        phase=CutoverPhase.DETECTED,
        legacy_path=str(paths.legacy) if paths.legacy else None,
        legacy_schema_version=None,
    )

    if mode is InstallMode.AMBIGUOUS:
        report.phase = CutoverPhase.FAILED
        report.errors.append(
            "Ambiguous database layout: partial three-DB set or conflicting paths. "
            f"paths={paths.as_mapping()}"
        )
        raise DatabaseUpgradeError(report.errors[0])

    template: Path | None = None
    try:
        if mode is InstallMode.THREE_DB:
            # Apply baseline when missing, then pending domain migrations.
            template = materialize_full_schema_template()
            for domain, path in paths:
                if domain_schema_version(path) < DOMAIN_BASELINE_VERSION:
                    apply_domain_baseline(path, domain, template=template)
                apply_pending_domain_migrations(path, domain)
                report.domain_versions[domain.value] = domain_schema_version(path)
            # Repair cutover stub schemas that conflict with runtime stores.
            control = _connect(paths.control)
            try:
                repair_incompatible_runs_schema(control)
                repair_incompatible_quality_schema(control)
                control.commit()
            finally:
                control.close()
            report.verification["wave3_schema_repairs"] = repair_domain_wave3_schemas(paths)
            # Reconcile product tables that landed in the wrong domain DB.
            reconcile_report = reconcile_misplaced_product_tables(paths, apply=True)
            report.verification["misplaced_reconcile"] = reconcile_report.public_dict()
            if reconcile_report.blocked or reconcile_report.errors or not reconcile_report.completed:
                for err in reconcile_report.errors:
                    if err not in report.errors:
                        report.errors.append(err)
                if reconcile_report.blocked:
                    report.errors.append(
                        "Misplaced tables blocked (UNKNOWN/CONFLICT/SCHEMA) — operator review required: "
                        + ", ".join(reconcile_report.blocked)
                    )
                report.phase = CutoverPhase.FAILED
                report.completed = False
                return _finalize_upgrade_report(report)
            # If cutover already complete, done.
            control = _connect(paths.control)
            try:
                _ensure_cutover_tables(control)
                status = _cutover_get(control, "phase")
                if status == CutoverPhase.COMPLETE.value:
                    report.phase = CutoverPhase.COMPLETE
                    report.completed = True
                    return _finalize_upgrade_report(report)
                # Three DBs exist without complete cutover marker: treat as fresh-complete
                # if no legacy, else resume cutover.
                if paths.legacy and paths.legacy.is_file():
                    report.resumed = True
                    mode = InstallMode.LEGACY_SINGLE
                    report.mode = mode
                else:
                    _cutover_set(control, "phase", CutoverPhase.COMPLETE.value)
                    _cutover_set(control, "mode", InstallMode.FRESH.value)
                    control.commit()
                    report.phase = CutoverPhase.COMPLETE
                    report.completed = True
                    return _finalize_upgrade_report(report)
            finally:
                control.close()

        if mode is InstallMode.FRESH:
            template = template or materialize_full_schema_template()
            paths.ensure_parent_dirs()
            for domain, path in paths:
                apply_domain_baseline(path, domain, template=template)
                apply_pending_domain_migrations(path, domain)
                report.domain_versions[domain.value] = domain_schema_version(path)
            control = _connect(paths.control)
            try:
                repair_incompatible_runs_schema(control)
                repair_incompatible_quality_schema(control)
                _ensure_cutover_tables(control)
                _cutover_set(control, "phase", CutoverPhase.COMPLETE.value)
                _cutover_set(control, "mode", InstallMode.FRESH.value)
                _cutover_set(control, "completed_at", utc_now())
                control.commit()
            finally:
                control.close()
            report.verification["wave3_schema_repairs"] = repair_domain_wave3_schemas(paths)
            report.phase = CutoverPhase.COMPLETE
            report.completed = True
            return _finalize_upgrade_report(report)

        # LEGACY_SINGLE (or resumed)
        assert paths.legacy is not None
        legacy = paths.legacy
        if not legacy.is_file():
            raise DatabaseUpgradeError(f"Legacy database not found: {legacy}")

        # 1) Upgrade legacy to head.
        applied_legacy = MigrationRunner(legacy).apply_all()
        report.applied_legacy = applied_legacy
        legacy_conn = _connect(legacy)
        try:
            _ensure_runtime_bootstrap_schema(legacy_conn)
            # Legacy may already have cutover stubs from a prior partial run.
            repair_incompatible_runs_schema(legacy_conn)
            repair_incompatible_quality_schema(legacy_conn)
            repair_incompatible_wave3_product_schemas(legacy_conn)
            legacy_conn.commit()
            report.legacy_schema_version = MigrationRunner(legacy).current_version(legacy_conn)
        finally:
            legacy_conn.close()
        report.phase = CutoverPhase.LEGACY_UPGRADED

        if report.legacy_schema_version != LEGACY_HEAD_VERSION:
            raise DatabaseUpgradeError(
                f"Legacy schema at {report.legacy_schema_version}, expected {LEGACY_HEAD_VERSION}"
            )

        unknown = classify_unmapped_legacy_tables(legacy)
        if unknown:
            raise DatabaseUpgradeError(
                "Ambiguous/unmapped legacy tables — refuse cutover: " + ", ".join(unknown)
            )

        template = template or materialize_full_schema_template()
        paths.ensure_parent_dirs()
        for domain, path in paths:
            apply_domain_baseline(path, domain, template=template)
            report.domain_versions[domain.value] = domain_schema_version(path)
        report.phase = CutoverPhase.TARGETS_CREATED
        report.verification["wave3_schema_repairs"] = repair_domain_wave3_schemas(paths)

        control = _connect(paths.control)
        try:
            repair_incompatible_runs_schema(control)
            repair_incompatible_quality_schema(control)
            _ensure_cutover_tables(control)
            prior = _cutover_get(control, "phase")
            if prior and prior != CutoverPhase.COMPLETE.value:
                report.resumed = True
            _cutover_set(control, "phase", CutoverPhase.COPYING.value)
            _cutover_set(control, "legacy_path", str(legacy))
            _cutover_set(control, "legacy_schema_version", str(report.legacy_schema_version))
            control.commit()

            report.phase = CutoverPhase.COPYING
            for domain, path in paths:
                copied = copy_legacy_to_domain(
                    legacy,
                    path,
                    domain,
                    receipt_conn=control,
                    receipt_db_path=paths.control,
                )
                report.tables_copied[domain.value] = copied

            # Verification pass: every present owned legacy table accounted for.
            src = _connect(legacy)
            try:
                verified: dict[str, Any] = {"tables": [], "ok": True}
                for table in sorted(_table_names(src)):
                    if table in PER_DATABASE_INFRASTRUCTURE:
                        continue
                    if table.startswith("sqlite_"):
                        continue
                    from Data.backend.table_ownership import is_fts_shadow_table

                    if is_fts_shadow_table(table):
                        continue
                    domain = ownership_for(table)
                    if domain is None:
                        continue
                    if table.endswith("_fts"):
                        continue
                    target = _connect(paths.path_for(domain))
                    try:
                        info = _verify_copy(src, target, table)
                        verified["tables"].append(info)
                    finally:
                        target.close()
                report.verification = verified
            finally:
                src.close()

            report.phase = CutoverPhase.VERIFIED
            _cutover_set(control, "phase", CutoverPhase.COMPLETE.value)
            _cutover_set(control, "completed_at", utc_now())
            _cutover_set(control, "mode", InstallMode.LEGACY_SINGLE.value)
            control.commit()
            report.phase = CutoverPhase.COMPLETE
            report.completed = True
            return _finalize_upgrade_report(report)
        except Exception as exc:
            report.phase = CutoverPhase.FAILED
            report.errors.append(str(exc))
            try:
                _cutover_set(control, "phase", CutoverPhase.FAILED.value)
                _cutover_set(control, "last_error", str(exc))
                control.commit()
            except Exception:  # noqa: BLE001
                pass
            raise DatabaseUpgradeError(str(exc)) from exc
        finally:
            control.close()
    finally:
        if template is not None:
            try:
                template.unlink(missing_ok=True)
            except OSError:
                pass


def ensure_domain_schema(path: Path, domain: DatabaseDomain) -> None:
    """Verify a domain DB is initialized; materialize baseline when empty.

    Stores must not apply the legacy MigrationRunner (that would recreate all
    product tables in every DB). Empty paths get a domain baseline from the
    schema template. Existing DBs with schema_migrations version >= 1 are OK
    (includes legacy full-schema test fixtures). Post-baseline DOMAIN_MIGRATIONS
    are applied idempotently.
    """
    if domain_schema_version(path) >= DOMAIN_BASELINE_VERSION:
        apply_pending_domain_migrations(path, domain)
        return
    template = materialize_full_schema_template()
    try:
        apply_domain_baseline(path, domain, template=template)
    finally:
        try:
            template.unlink(missing_ok=True)
        except OSError:
            pass
    if domain_schema_version(path) < DOMAIN_BASELINE_VERSION:
        raise DatabaseUpgradeError(
            f"{domain.value} database is not initialized at {path}. "
            "Run upgrade_leviathan_databases (Data.backend.db_upgrade) first."
        )
    apply_pending_domain_migrations(path, domain)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry for root upgrade_leviathan_databases.bat."""
    import argparse
    import os
    import sys

    # Ensure repo root on path when invoked as script.
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    parser = argparse.ArgumentParser(description="Upgrade LEVIATHAN canonical databases")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args(list(argv) if argv is not None else None)

    from Data.backend.config import load_settings

    settings = load_settings()
    paths = settings.database_paths
    try:
        report = upgrade_all_databases(paths)
    except DatabaseUpgradeError as exc:
        print(f"[LEVIATHAN] Database upgrade FAILED: {exc}", flush=True)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[LEVIATHAN] Database upgrade FAILED: {exc}", flush=True)
        return 1

    if args.json:
        print(json.dumps(report.public_dict(), indent=2))
    else:
        print("[LEVIATHAN] Database upgrade OK", flush=True)
        print(f"  mode={report.mode.value} phase={report.phase.value}", flush=True)
        print(f"  domain_versions={report.domain_versions}", flush=True)
        if report.legacy_path:
            print(f"  legacy_preserved={report.legacy_path}", flush=True)
    return 0 if report.completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
