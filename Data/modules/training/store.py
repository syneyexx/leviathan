"""SQLite persistence for durable training jobs (migration v14 tables)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .types import (
    ACTIVE_DURABLE_STATUSES,
    ArtifactRecord,
    CheckpointRecord,
    DurableTrainingJob,
    DurableTrainingStatus,
    MetricRecord,
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


class TrainingStore:
    """Owns training_jobs / metrics / checkpoints / artifacts rows."""

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


    def create_job(
        self,
        *,
        name: str,
        method: str,
        base_model_ref: str,
        config: dict[str, Any],
        dataset_version_id: str | None = None,
        output_dir: str | None = None,
        seed: int | None = None,
        config_hash: str | None = None,
        planner: dict[str, Any] | None = None,
        preflight: dict[str, Any] | None = None,
        environment: dict[str, Any] | None = None,
        log_path: str | None = None,
        trace_id: str | None = None,
        job_id: str | None = None,
    ) -> DurableTrainingJob:
        now = utc_now()
        record = DurableTrainingJob(
            job_id=job_id or str(uuid.uuid4()),
            name=name.strip() or "training",
            status=DurableTrainingStatus.QUEUED,
            method=method,
            base_model_ref=base_model_ref,
            dataset_version_id=dataset_version_id,
            output_dir=output_dir,
            config=dict(config),
            planner=dict(planner or {}),
            preflight=dict(preflight or {}),
            progress=0.0,
            cancel_requested=False,
            worker_pid=None,
            checkpoint={},
            metrics_summary={},
            evaluation={},
            artifact_id=None,
            error=None,
            log_path=log_path,
            trace_id=trace_id or str(uuid.uuid4()),
            seed=seed,
            config_hash=config_hash,
            environment=dict(environment or {}),
            phase="queued",
            created_at=now,
            started_at=None,
            updated_at=now,
            finished_at=None,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO training_jobs(
                    job_id, name, status, phase, method, base_model_ref, dataset_version_id,
                    output_dir, config_json, planner_json, preflight_json, progress,
                    cancel_requested, worker_pid, checkpoint_json, metrics_summary_json,
                    evaluation_json, artifact_id, error, log_path, trace_id, seed,
                    config_hash, environment_json, created_at, started_at, updated_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    record.name,
                    record.status.value,
                    record.phase,
                    record.method,
                    record.base_model_ref,
                    record.dataset_version_id,
                    record.output_dir,
                    json.dumps(record.config),
                    json.dumps(record.planner),
                    json.dumps(record.preflight),
                    record.progress,
                    0,
                    None,
                    json.dumps(record.checkpoint),
                    json.dumps(record.metrics_summary),
                    json.dumps(record.evaluation),
                    None,
                    None,
                    record.log_path,
                    record.trace_id,
                    record.seed,
                    record.config_hash,
                    json.dumps(record.environment),
                    record.created_at,
                    None,
                    record.updated_at,
                    None,
                ),
            )
        return record

    def get_job(self, job_id: str) -> DurableTrainingJob | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM training_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._job_from_row(row) if row else None

    def list_jobs(self, *, status: str | None = None, limit: int = 100) -> list[DurableTrainingJob]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.append(max(1, min(int(limit), 500)))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM training_jobs {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def list_active_jobs(self) -> list[DurableTrainingJob]:
        statuses = tuple(s.value for s in ACTIVE_DURABLE_STATUSES)
        placeholders = ",".join("?" for _ in statuses)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM training_jobs WHERE status IN ({placeholders})",
                statuses,
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def update_job(self, job_id: str, **fields: Any) -> DurableTrainingJob:
        mapping = {
            "status": "status",
            "phase": "phase",
            "progress": "progress",
            "cancel_requested": "cancel_requested",
            "worker_pid": "worker_pid",
            "checkpoint": "checkpoint_json",
            "metrics_summary": "metrics_summary_json",
            "evaluation": "evaluation_json",
            "artifact_id": "artifact_id",
            "error": "error",
            "log_path": "log_path",
            "planner": "planner_json",
            "preflight": "preflight_json",
            "environment": "environment_json",
            "output_dir": "output_dir",
            "started_at": "started_at",
            "finished_at": "finished_at",
        }
        json_fields = {
            "checkpoint",
            "metrics_summary",
            "evaluation",
            "planner",
            "preflight",
            "environment",
        }
        sets: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            col = mapping.get(key)
            if col is None:
                raise ValueError(f"Unsupported field: {key}")
            if key == "status" and isinstance(value, DurableTrainingStatus):
                value = value.value
            if key == "cancel_requested":
                value = 1 if value else 0
            if key in json_fields:
                value = json.dumps(value or {})
            sets.append(f"{col} = ?")
            values.append(value)
        now = utc_now()
        sets.append("updated_at = ?")
        values.append(now)
        values.append(job_id)
        with self.connect() as conn:
            cur = conn.execute(
                f"UPDATE training_jobs SET {', '.join(sets)} WHERE job_id = ?",
                values,
            )
            if cur.rowcount == 0:
                raise KeyError(job_id)
        job = self.get_job(job_id)
        assert job is not None
        return job

    def request_cancel(self, job_id: str) -> DurableTrainingJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return self.update_job(
            job_id,
            cancel_requested=True,
            status=DurableTrainingStatus.CANCELLING,
            phase="cancelling",
        )

    def append_metric(
        self,
        job_id: str,
        *,
        metric_name: str,
        metric_value: float,
        step: int | None = None,
        epoch: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MetricRecord:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO training_metrics(
                    job_id, step, epoch, metric_name, metric_value, recorded_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    step,
                    epoch,
                    metric_name,
                    float(metric_value),
                    now,
                    json.dumps(metadata or {}),
                ),
            )
            row_id = int(cur.lastrowid)
        return MetricRecord(
            id=row_id,
            job_id=job_id,
            step=step,
            epoch=epoch,
            metric_name=metric_name,
            metric_value=float(metric_value),
            recorded_at=now,
            metadata=metadata or {},
        )

    def list_metrics(self, job_id: str, *, limit: int = 500) -> list[MetricRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM training_metrics
                WHERE job_id = ?
                ORDER BY recorded_at ASC, id ASC
                LIMIT ?
                """,
                (job_id, max(1, min(int(limit), 5000))),
            ).fetchall()
        return [
            MetricRecord(
                id=int(row["id"]),
                job_id=row["job_id"],
                step=row["step"],
                epoch=row["epoch"],
                metric_name=row["metric_name"],
                metric_value=float(row["metric_value"]),
                recorded_at=row["recorded_at"],
                metadata=_loads(row["metadata_json"], {}),
            )
            for row in rows
        ]

    def add_checkpoint(
        self,
        *,
        job_id: str,
        path: str,
        step: int | None = None,
        epoch: float | None = None,
        content_hash: str | None = None,
        metrics: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        checkpoint_id: str | None = None,
    ) -> CheckpointRecord:
        now = utc_now()
        record = CheckpointRecord(
            checkpoint_id=checkpoint_id or str(uuid.uuid4()),
            job_id=job_id,
            step=step,
            epoch=epoch,
            path=path,
            content_hash=content_hash,
            metrics=dict(metrics or {}),
            created_at=now,
            metadata=dict(metadata or {}),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO training_checkpoints(
                    checkpoint_id, job_id, step, epoch, path, content_hash,
                    metrics_json, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.checkpoint_id,
                    record.job_id,
                    record.step,
                    record.epoch,
                    record.path,
                    record.content_hash,
                    json.dumps(record.metrics),
                    record.created_at,
                    json.dumps(record.metadata),
                ),
            )
        return record

    def list_checkpoints(self, job_id: str) -> list[CheckpointRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM training_checkpoints
                WHERE job_id = ?
                ORDER BY created_at ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            CheckpointRecord(
                checkpoint_id=row["checkpoint_id"],
                job_id=row["job_id"],
                step=row["step"],
                epoch=row["epoch"],
                path=row["path"],
                content_hash=row["content_hash"],
                metrics=_loads(row["metrics_json"], {}),
                created_at=row["created_at"],
                metadata=_loads(row["metadata_json"], {}),
            )
            for row in rows
        ]

    def add_artifact(
        self,
        *,
        job_id: str,
        artifact_type: str,
        path: str,
        base_model_ref: str | None = None,
        dataset_version_id: str | None = None,
        method: str | None = None,
        config_hash: str | None = None,
        content_hash: str | None = None,
        model_card_path: str | None = None,
        evaluation: dict[str, Any] | None = None,
        compatibility: dict[str, Any] | None = None,
        registered_model_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        artifact_id: str | None = None,
    ) -> ArtifactRecord:
        now = utc_now()
        record = ArtifactRecord(
            artifact_id=artifact_id or str(uuid.uuid4()),
            job_id=job_id,
            artifact_type=artifact_type,
            path=path,
            base_model_ref=base_model_ref,
            dataset_version_id=dataset_version_id,
            method=method,
            config_hash=config_hash,
            content_hash=content_hash,
            model_card_path=model_card_path,
            evaluation=dict(evaluation or {}),
            compatibility=dict(compatibility or {}),
            registered_model_id=registered_model_id,
            created_at=now,
            metadata=dict(metadata or {}),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO training_artifacts(
                    artifact_id, job_id, artifact_type, path, base_model_ref,
                    dataset_version_id, method, config_hash, content_hash,
                    model_card_path, evaluation_json, compatibility_json,
                    registered_model_id, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.artifact_id,
                    record.job_id,
                    record.artifact_type,
                    record.path,
                    record.base_model_ref,
                    record.dataset_version_id,
                    record.method,
                    record.config_hash,
                    record.content_hash,
                    record.model_card_path,
                    json.dumps(record.evaluation),
                    json.dumps(record.compatibility),
                    record.registered_model_id,
                    record.created_at,
                    json.dumps(record.metadata),
                ),
            )
        return record

    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM training_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            return None
        return ArtifactRecord(
            artifact_id=row["artifact_id"],
            job_id=row["job_id"],
            artifact_type=row["artifact_type"],
            path=row["path"],
            base_model_ref=row["base_model_ref"],
            dataset_version_id=row["dataset_version_id"],
            method=row["method"],
            config_hash=row["config_hash"],
            content_hash=row["content_hash"],
            model_card_path=row["model_card_path"],
            evaluation=_loads(row["evaluation_json"], {}),
            compatibility=_loads(row["compatibility_json"], {}),
            registered_model_id=row["registered_model_id"],
            created_at=row["created_at"],
            metadata=_loads(row["metadata_json"], {}),
        )

    def update_artifact_registered_model(self, artifact_id: str, model_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE training_artifacts SET registered_model_id = ? WHERE artifact_id = ?",
                (model_id, artifact_id),
            )

    def list_jobs_referencing_dataset_version(self, version_id: str) -> list[DurableTrainingJob]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM training_jobs
                WHERE dataset_version_id = ?
                ORDER BY created_at DESC
                """,
                (version_id,),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def dataset_version_exists(self, version_id: str) -> bool:
        with self.connect() as conn:
            try:
                row = conn.execute(
                    "SELECT 1 FROM dataset_versions WHERE version_id = ?",
                    (version_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                return False
        return row is not None

    def _job_from_row(self, row: sqlite3.Row) -> DurableTrainingJob:
        return DurableTrainingJob(
            job_id=row["job_id"],
            name=row["name"],
            status=DurableTrainingStatus(row["status"]),
            method=row["method"],
            base_model_ref=row["base_model_ref"],
            dataset_version_id=row["dataset_version_id"],
            output_dir=row["output_dir"],
            config=_loads(row["config_json"], {}),
            planner=_loads(row["planner_json"], {}),
            preflight=_loads(row["preflight_json"], {}),
            progress=row["progress"],
            cancel_requested=bool(row["cancel_requested"]),
            worker_pid=row["worker_pid"],
            checkpoint=_loads(row["checkpoint_json"], {}),
            metrics_summary=_loads(row["metrics_summary_json"], {}),
            evaluation=_loads(row["evaluation_json"], {}),
            artifact_id=row["artifact_id"],
            error=row["error"],
            log_path=row["log_path"],
            trace_id=row["trace_id"],
            seed=row["seed"],
            config_hash=row["config_hash"],
            environment=_loads(row["environment_json"], {}),
            phase=row["phase"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
        )
