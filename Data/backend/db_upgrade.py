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

        CREATE TABLE IF NOT EXISTS provider_stream_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_id TEXT NOT NULL,
            seq INTEGER NOT NULL DEFAULT 0,
            event_type TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS intelligence_assimilation_receipts (
            receipt_id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS knowledge_commit_receipts (
            receipt_id TEXT PRIMARY KEY,
            commit_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS source_ingestion_commit_records (
            record_id TEXT PRIMARY KEY,
            container_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS dataset_commit_index_rows (
            row_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS market_sim_commit_batches (
            batch_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
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
            # Apply any future domain migrations (currently baseline only).
            template = materialize_full_schema_template()
            for domain, path in paths:
                if domain_schema_version(path) < DOMAIN_BASELINE_VERSION:
                    apply_domain_baseline(path, domain, template=template)
                report.domain_versions[domain.value] = domain_schema_version(path)
            # Repair cutover stub schemas that conflict with runtime stores.
            control = _connect(paths.control)
            try:
                repair_incompatible_runs_schema(control)
                repair_incompatible_quality_schema(control)
                control.commit()
            finally:
                control.close()
            # If cutover already complete, done.
            control = _connect(paths.control)
            try:
                _ensure_cutover_tables(control)
                status = _cutover_get(control, "phase")
                if status == CutoverPhase.COMPLETE.value:
                    report.phase = CutoverPhase.COMPLETE
                    report.completed = True
                    return report
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
                    return report
            finally:
                control.close()

        if mode is InstallMode.FRESH:
            template = template or materialize_full_schema_template()
            paths.ensure_parent_dirs()
            for domain, path in paths:
                apply_domain_baseline(path, domain, template=template)
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
            report.phase = CutoverPhase.COMPLETE
            report.completed = True
            return report

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
            return report
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
    (includes legacy full-schema test fixtures).
    """
    if domain_schema_version(path) >= DOMAIN_BASELINE_VERSION:
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
