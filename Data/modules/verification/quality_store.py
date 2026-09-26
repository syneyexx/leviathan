"""Durable persistence for quality contracts, verdicts, and acceptance records."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .quality_contract import (
    AcceptanceOutcome,
    AcceptanceRecord,
    CriterionVerdict,
    CriterionVerdictStatus,
    QualityContract,
)


class QualityContractStore:
    """SQLite store for TEAM quality contracts — shares the deployment metadata DB path."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_contracts (
                contract_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (contract_id, version)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality_contracts_run "
            "ON quality_contracts(run_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_verdicts (
                verdict_id TEXT PRIMARY KEY,
                contract_id TEXT NOT NULL,
                contract_version INTEGER NOT NULL,
                criterion_id TEXT NOT NULL,
                artifact_revision TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality_verdicts_contract "
            "ON quality_verdicts(contract_id, contract_version, artifact_revision)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_acceptances (
                acceptance_id TEXT PRIMARY KEY,
                contract_id TEXT NOT NULL,
                contract_version INTEGER NOT NULL,
                artifact_revision TEXT NOT NULL,
                outcome TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality_acceptances_contract "
            "ON quality_acceptances(contract_id, contract_version)"
        )

    def save_contract(self, contract: QualityContract) -> QualityContract:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO quality_contracts(
                    contract_id, version, run_id, payload_json, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    contract.contract_id,
                    contract.version,
                    contract.run_id,
                    json.dumps(contract.public_dict(), default=str),
                    contract.content_hash(),
                    contract.created_at or contract.revised_at or "",
                ),
            )
        return contract

    def get_contract(
        self, contract_id: str, *, version: int | None = None
    ) -> QualityContract | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            if version is None:
                row = conn.execute(
                    """
                    SELECT payload_json FROM quality_contracts
                    WHERE contract_id = ?
                    ORDER BY version DESC LIMIT 1
                    """,
                    (contract_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT payload_json FROM quality_contracts
                    WHERE contract_id = ? AND version = ?
                    """,
                    (contract_id, version),
                ).fetchone()
        if row is None:
            return None
        return QualityContract.from_dict(json.loads(row[0]))

    def get_contract_for_run(self, run_id: str) -> QualityContract | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT payload_json FROM quality_contracts
                WHERE run_id = ?
                ORDER BY version DESC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return QualityContract.from_dict(json.loads(row[0]))

    def save_verdict(self, verdict: CriterionVerdict, *, contract_id: str) -> CriterionVerdict:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO quality_verdicts(
                    verdict_id, contract_id, contract_version, criterion_id,
                    artifact_revision, status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verdict.verdict_id,
                    contract_id,
                    verdict.contract_version,
                    verdict.criterion_id,
                    verdict.artifact_revision,
                    verdict.status.value,
                    json.dumps(verdict.public_dict(), default=str),
                    verdict.created_at,
                ),
            )
        return verdict

    def list_verdicts(
        self,
        contract_id: str,
        *,
        contract_version: int | None = None,
        artifact_revision: str | None = None,
        include_stale: bool = False,
    ) -> list[CriterionVerdict]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            sql = "SELECT payload_json, status FROM quality_verdicts WHERE contract_id = ?"
            params: list[Any] = [contract_id]
            if contract_version is not None:
                sql += " AND contract_version = ?"
                params.append(contract_version)
            if artifact_revision is not None:
                sql += " AND artifact_revision = ?"
                params.append(artifact_revision)
            sql += " ORDER BY created_at ASC, verdict_id ASC"
            rows = conn.execute(sql, params).fetchall()
        out: list[CriterionVerdict] = []
        for payload_json, status in rows:
            if not include_stale and status == CriterionVerdictStatus.STALE.value:
                continue
            out.append(CriterionVerdict.from_dict(json.loads(payload_json)))
        return out

    def save_acceptance(self, record: AcceptanceRecord) -> AcceptanceRecord:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO quality_acceptances(
                    acceptance_id, contract_id, contract_version, artifact_revision,
                    outcome, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.acceptance_id,
                    record.contract_id,
                    record.contract_version,
                    record.artifact_revision,
                    record.outcome.value,
                    json.dumps(record.public_dict(), default=str),
                    record.created_at,
                ),
            )
        return record

    def latest_acceptance(self, contract_id: str) -> AcceptanceRecord | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT payload_json FROM quality_acceptances
                WHERE contract_id = ?
                ORDER BY created_at DESC, acceptance_id DESC LIMIT 1
                """,
                (contract_id,),
            ).fetchone()
        if row is None:
            return None
        raw = json.loads(row[0])
        return AcceptanceRecord(
            acceptance_id=str(raw["acceptance_id"]),
            contract_id=str(raw["contract_id"]),
            contract_version=int(raw["contract_version"]),
            contract_hash=str(raw.get("contract_hash") or ""),
            artifact_revision=str(raw["artifact_revision"]),
            outcome=AcceptanceOutcome(str(raw["outcome"])),
            mandatory_verdict_ids=tuple(raw.get("mandatory_verdict_ids") or ()),
            advisory_notes=tuple(raw.get("advisory_notes") or ()),
            blockers=tuple(raw.get("blockers") or ()),
            created_at=str(raw.get("created_at") or ""),
            limitations=tuple(raw.get("limitations") or ()),
        )
