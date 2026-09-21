from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .types import RequirementResult, VerificationOutcome, VerificationReport


class VerificationReportStore:
    """Durable store for VerificationReport rows. report ≠ live re-evaluation."""

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

    def save(self, report: VerificationReport) -> VerificationReport:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO verification_reports(
                    report_id, outcome, created_at, run_id, job_id,
                    requirements_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.outcome.value,
                    report.created_at,
                    report.run_id,
                    report.job_id,
                    json.dumps([item.public_dict() for item in report.requirements]),
                    json.dumps(report.metadata),
                ),
            )
        return report

    def get(self, report_id: str) -> VerificationReport | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM verification_reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def list(
        self,
        *,
        run_id: str | None = None,
        job_id: str | None = None,
        outcome: VerificationOutcome | str | None = None,
        limit: int = 100,
    ) -> list[VerificationReport]:
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if job_id:
            clauses.append("job_id = ?")
            params.append(job_id)
        if outcome is not None:
            value = outcome.value if isinstance(outcome, VerificationOutcome) else str(outcome)
            clauses.append("outcome = ?")
            params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                f"""
                SELECT * FROM verification_reports
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def _from_row(self, row: sqlite3.Row) -> VerificationReport:
        raw_reqs = json.loads(row["requirements_json"] or "[]")
        requirements: list[RequirementResult] = []
        for item in raw_reqs:
            try:
                requirements.append(
                    RequirementResult(
                        requirement_id=str(item.get("requirement_id") or ""),
                        outcome=VerificationOutcome(str(item.get("outcome") or "UNMEASURED")),
                        matched_evidence_ids=tuple(item.get("matched_evidence_ids") or ()),
                        detail=item.get("detail"),
                    )
                )
            except (TypeError, ValueError):
                continue
        return VerificationReport(
            report_id=row["report_id"],
            outcome=VerificationOutcome(row["outcome"]),
            created_at=row["created_at"],
            run_id=row["run_id"],
            job_id=row["job_id"],
            requirements=tuple(requirements),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
