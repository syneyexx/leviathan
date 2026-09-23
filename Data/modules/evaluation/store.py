"""Durable evaluation reports + regression corpus (central SQLite only)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import (
    EvalCase,
    EvalCaseResult,
    EvalOutcome,
    EvalReport,
    JudgmentKind,
    MeasurementState,
    RegressionCase,
    outcome_to_measurement,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class EvaluationStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
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
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS eval_reports (
                report_id TEXT PRIMARY KEY,
                suite_id TEXT NOT NULL,
                suite_version TEXT NOT NULL DEFAULT '1',
                name TEXT NOT NULL,
                system_level INTEGER NOT NULL DEFAULT 0,
                summary_json TEXT NOT NULL DEFAULT '{}',
                component_scope_json TEXT NOT NULL DEFAULT '[]',
                artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                results_json TEXT NOT NULL DEFAULT '[]',
                recorded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_eval_reports_suite
                ON eval_reports(suite_id, recorded_at DESC);

            CREATE TABLE IF NOT EXISTS eval_case_results (
                result_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                measurement TEXT NOT NULL,
                judgment_kind TEXT NOT NULL,
                detail TEXT,
                component TEXT,
                artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                payload_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(report_id) REFERENCES eval_reports(report_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_eval_case_results_report
                ON eval_case_results(report_id, case_id);

            CREATE TABLE IF NOT EXISTS eval_regression_corpus (
                regression_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                incident_ref TEXT NOT NULL,
                case_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reproducible INTEGER NOT NULL DEFAULT 1,
                notes TEXT
            );
            """
        )

    def save_report(self, report: EvalReport) -> EvalReport:
        report_id = report.report_id or str(uuid.uuid4())
        recorded_at = report.recorded_at or _utc_now()
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_reports(
                    report_id, suite_id, suite_version, name, system_level,
                    summary_json, component_scope_json, artifact_refs_json,
                    results_json, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    report.suite_id,
                    report.suite_version,
                    report.name,
                    1 if report.system_level else 0,
                    json.dumps(report.summary),
                    json.dumps(list(report.component_scope)),
                    json.dumps(list(report.artifact_refs)),
                    json.dumps([r.public_dict() for r in report.results]),
                    recorded_at,
                ),
            )
            conn.execute("DELETE FROM eval_case_results WHERE report_id = ?", (report_id,))
            for result in report.results:
                conn.execute(
                    """
                    INSERT INTO eval_case_results(
                        result_id, report_id, case_id, outcome, measurement,
                        judgment_kind, detail, component, artifact_refs_json,
                        evidence_refs_json, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        report_id,
                        result.case_id,
                        result.outcome.value,
                        result.resolved_measurement().value,
                        result.judgment_kind.value,
                        result.detail,
                        result.component,
                        json.dumps(list(result.artifact_refs)),
                        json.dumps(list(result.evidence_refs)),
                        json.dumps(result.public_dict()),
                    ),
                )
        return EvalReport(
            suite_id=report.suite_id,
            name=report.name,
            results=report.results,
            summary=report.summary,
            suite_version=report.suite_version,
            recorded_at=recorded_at,
            report_id=report_id,
            component_scope=report.component_scope,
            system_level=report.system_level,
            artifact_refs=report.artifact_refs,
        )

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM eval_reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
        return self._row_to_report(row) if row else None

    def latest_report(self, suite_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                """
                SELECT * FROM eval_reports
                WHERE suite_id = ?
                ORDER BY recorded_at DESC
                LIMIT 1
                """,
                (suite_id,),
            ).fetchone()
        return self._row_to_report(row) if row else None

    def list_reports(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM eval_reports
                ORDER BY recorded_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._row_to_report(row) for row in rows]

    def add_regression(self, item: RegressionCase) -> RegressionCase:
        with self.connect() as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_regression_corpus(
                    regression_id, title, incident_ref, case_json,
                    created_at, reproducible, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.regression_id,
                    item.title,
                    item.incident_ref,
                    json.dumps(item.case.public_dict()),
                    item.created_at,
                    1 if item.reproducible else 0,
                    item.notes,
                ),
            )
        return item

    def list_regressions(self, *, limit: int = 100) -> list[RegressionCase]:
        with self.connect() as conn:
            self._ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM eval_regression_corpus
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
        out: list[RegressionCase] = []
        for row in rows:
            case_raw = json.loads(row["case_json"] or "{}")
            out.append(
                RegressionCase(
                    regression_id=row["regression_id"],
                    title=row["title"],
                    incident_ref=row["incident_ref"],
                    case=self._case_from_dict(case_raw),
                    created_at=row["created_at"],
                    reproducible=bool(row["reproducible"]),
                    notes=row["notes"],
                )
            )
        return out

    def has_relevant_eval(
        self,
        *,
        component: str | None = None,
        suite_id: str | None = None,
        require_pass: bool = False,
    ) -> dict[str, Any]:
        """Promotion helper: was a relevant eval recorded? (U335 / Wave 2 exit gate)."""
        with self.connect() as conn:
            self._ensure_schema(conn)
            if suite_id:
                row = conn.execute(
                    """
                    SELECT * FROM eval_reports
                    WHERE suite_id = ?
                    ORDER BY recorded_at DESC LIMIT 1
                    """,
                    (suite_id,),
                ).fetchone()
            elif component:
                row = conn.execute(
                    """
                    SELECT r.* FROM eval_reports r
                    WHERE r.component_scope_json LIKE ?
                       OR EXISTS (
                            SELECT 1 FROM eval_case_results c
                            WHERE c.report_id = r.report_id AND c.component = ?
                       )
                    ORDER BY r.recorded_at DESC LIMIT 1
                    """,
                    (f'%"{component}"%', component),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM eval_reports ORDER BY recorded_at DESC LIMIT 1"
                ).fetchone()
        if row is None:
            return {
                "recorded": False,
                "measurement": MeasurementState.UNMEASURED.value,
                "detail": "no relevant eval report recorded",
                "promotable": False,
            }
        report = self._row_to_report(row)
        summary = report.get("summary") or {}
        failed = int(summary.get("failed", 0)) + int(summary.get("error", 0))
        unmeasured = int(summary.get("unmeasured", 0))
        if failed:
            measurement = MeasurementState.FAIL
        elif unmeasured:
            measurement = MeasurementState.UNMEASURED
        else:
            measurement = MeasurementState.PASS
        promotable = measurement == MeasurementState.PASS if require_pass else failed == 0
        return {
            "recorded": True,
            "report_id": report["report_id"],
            "suite_id": report["suite_id"],
            "measurement": measurement.value,
            "detail": f"latest={report['report_id']} measurement={measurement.value}",
            "promotable": promotable and report["recorded_at"] is not None,
            "truth": {"unmeasured_is_not_passed": True},
        }

    @staticmethod
    def _case_from_dict(data: dict[str, Any]) -> EvalCase:
        try:
            judgment = JudgmentKind(str(data.get("judgment_kind") or JudgmentKind.DETERMINISTIC.value))
        except ValueError:
            judgment = JudgmentKind.DETERMINISTIC
        return EvalCase(
            case_id=str(data.get("case_id") or uuid.uuid4()),
            name=str(data.get("name") or "case"),
            description=str(data.get("description") or ""),
            check=str(data.get("check") or "always_unmeasured"),
            params=dict(data.get("params") or {}),
            version=str(data.get("version") or "1"),
            suite_id=data.get("suite_id"),
            judgment_kind=judgment,
            component=data.get("component"),
            system_level=bool(data.get("system_level")),
            sealed=bool(data.get("sealed")),
            tags=tuple(data.get("tags") or ()),
        )

    @staticmethod
    def _row_to_report(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "report_id": row["report_id"],
            "suite_id": row["suite_id"],
            "suite_version": row["suite_version"],
            "name": row["name"],
            "system_level": bool(row["system_level"]),
            "summary": json.loads(row["summary_json"] or "{}"),
            "component_scope": json.loads(row["component_scope_json"] or "[]"),
            "artifact_refs": json.loads(row["artifact_refs_json"] or "[]"),
            "results": json.loads(row["results_json"] or "[]"),
            "recorded_at": row["recorded_at"],
        }


def seed_default_regressions(store: EvaluationStore) -> list[RegressionCase]:
    """Seed a minimal sealed regression corpus for Wave 2."""
    now = _utc_now()
    seeds = [
        RegressionCase(
            regression_id="reg-unmeasured-not-pass",
            title="UNMEASURED must not promote as PASS",
            incident_ref="wave2-invariant-u338",
            case=EvalCase(
                case_id="reg-unmeasured-invariant",
                name="UNMEASURED ≠ PASS",
                description="Regression: missing measurement stays UNMEASURED",
                check="always_unmeasured",
                params={"reason": "sealed regression — unmeasured quality gate"},
                version="1",
                suite_id="regression",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="evaluation",
                system_level=True,
                sealed=True,
                tags=("regression", "honesty"),
            ),
            created_at=now,
            notes="Core honesty invariant from Wave 2 exit gate",
        ),
        RegressionCase(
            regression_id="reg-capability-catalog",
            title="file.read capability must remain registered",
            incident_ref="wave2-foundation-capability",
            case=EvalCase(
                case_id="reg-file-read-exists",
                name="file.read registered",
                description="Regression: catalog must expose file.read",
                check="capability_exists",
                params={"capability_id": "file.read"},
                version="1",
                suite_id="regression",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="execution",
                sealed=True,
                tags=("regression", "capabilities"),
            ),
            created_at=now,
        ),
    ]
    existing = {item.regression_id for item in store.list_regressions(limit=500)}
    saved: list[RegressionCase] = []
    for item in seeds:
        if item.regression_id not in existing:
            store.add_regression(item)
            saved.append(item)
    return saved
