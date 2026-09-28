"""Bounded, read-only host projections.

Missing measurements stay null or an explicit unknown token. This module never
writes SQLite, never spawns workers, and never treats a missing metric as zero.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable

_SECRET = re.compile(
    r"(?i)(authorization\s*:\s*bearer\s+)\S+"
    r"|((?:api[_-]?key|secret|password|passwd|token)\s*[=:]\s*)\S+"
    r"|\bsk-[A-Za-z0-9]{8,}\b"
    r"|\bbearer\s+[A-Za-z0-9\-._~+/]{8,}={0,2}"
)

_PROCESSING_PHASES = {
    "uploading",
    "stored",
    "inspecting",
    "expanding",
    "classifying",
    "parsing",
    "normalizing",
    "brain_pending",
    "brain_syncing",
}
_QUEUED_PHASES = {"queued"}
_COMPLETED_PHASES = {"completed", "skipped"}
_FAILED_PHASES = {"failed", "partial", "quarantined", "cancelled"}

_NATIVE_EVENT_HINTS = ("native", "data-plane", "data_plane", "leviathan-data-plane")


def redact_host_text(value: str, *, limit: int = 500) -> str:
    """Redact obvious secrets and bound length. Does not claim to catch every secret."""
    text = value if isinstance(value, str) else str(value)
    redacted = _SECRET.sub(
        lambda match: (match.group(1) or match.group(2) or "") + "[REDACTED]"
        if (match.group(1) or match.group(2))
        else "[REDACTED]",
        text,
    )
    if len(redacted) > limit:
        return redacted[:limit] + "…[truncated]"
    return redacted


def _redact_obj(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return redact_host_text(value, limit=400)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:40]:
            lowered = str(key).lower()
            if any(token in lowered for token in ("secret", "password", "token", "api_key", "apikey", "authorization")):
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = _redact_obj(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_redact_obj(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_host_text(str(value), limit=200)


def _connect_readonly(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    from Data.modules.sqlite_manager.sql_safety import open_readonly_connection

    try:
        return open_readonly_connection(str(path), open_fn=sqlite3.connect)
    except sqlite3.Error:
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _candidate_db_paths(settings: Any) -> list[Path]:
    paths: list[Path] = []
    for attr in ("database_path", "knowledge_database_path", "control_database_path"):
        raw = getattr(settings, attr, None)
        if raw:
            paths.append(Path(raw))
    # Preserve order while dropping duplicates.
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _load_containers(settings: Any, *, limit: int) -> tuple[list[dict[str, Any]], str]:
    """Read ingestion containers without creating tables or files."""
    limit = max(1, min(int(limit), 200))
    for path in _candidate_db_paths(settings):
        conn = _connect_readonly(path)
        if conn is None:
            continue
        try:
            if not _table_exists(conn, "source_ingestion_containers"):
                continue
            rows = conn.execute(
                """
                SELECT container_source_id, project_id, job_id, filename, archive_type,
                       phase, cancel_requested, compressed_bytes, uncompressed_bytes,
                       progress_json, error, created_at, updated_at
                FROM source_ingestion_containers
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        containers: list[dict[str, Any]] = []
        for row in rows:
            progress_raw = row["progress_json"] if isinstance(row, sqlite3.Row) else row[9]
            try:
                progress = json.loads(progress_raw) if progress_raw else {}
            except json.JSONDecodeError:
                progress = {}
            if not isinstance(progress, dict):
                progress = {}
            containers.append(
                {
                    "container_source_id": row["container_source_id"],
                    "project_id": row["project_id"],
                    "job_id": row["job_id"],
                    "filename": row["filename"],
                    "archive_type": row["archive_type"],
                    "phase": row["phase"],
                    "cancel_requested": bool(row["cancel_requested"]),
                    "compressed_bytes": row["compressed_bytes"],
                    "uncompressed_bytes": row["uncompressed_bytes"],
                    "progress": progress,
                    "error": row["error"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "database": str(path),
                }
            )
        return containers, str(path)
    return [], ""


def _job_public(job_runtime: Any, job_id: str | None) -> dict[str, Any] | None:
    if not job_id or job_runtime is None or not hasattr(job_runtime, "get"):
        return None
    try:
        job = job_runtime.get(job_id)
    except Exception:  # noqa: BLE001 — missing job is not a host failure
        return None
    if job is None:
        return None
    if hasattr(job, "public_dict"):
        raw = job.public_dict()
    elif isinstance(job, dict):
        raw = job
    else:
        return None
    # Arguments can carry local paths; never return secret-looking fields.
    if isinstance(raw, dict) and "arguments" in raw:
        raw = dict(raw)
        raw["arguments"] = _redact_obj(raw.get("arguments"))
    return raw


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _progress_fields(progress: dict[str, Any]) -> dict[str, Any]:
    pct = _number(progress.get("progress_pct"))
    if pct is None:
        pct = _number(progress.get("progress"))
    throughput = None
    for key in ("bytes_per_second", "docs_per_second", "throughput"):
        throughput = _number(progress.get(key))
        if throughput is not None:
            break
    eta = progress.get("eta_seconds")
    eta_out = eta if isinstance(eta, (int, float)) and not isinstance(eta, bool) else None
    return {
        "progressPct": pct,
        "throughput": throughput,
        "etaSeconds": eta_out,
        "throughputMeasured": throughput is not None,
        "etaMeasured": eta_out is not None,
    }


def _bucket(phase: str) -> str:
    token = (phase or "").strip().lower()
    if token in _QUEUED_PHASES:
        return "queued"
    if token in _PROCESSING_PHASES:
        return "processing"
    if token in _COMPLETED_PHASES:
        return "completed"
    if token in _FAILED_PHASES:
        return "failed"
    return "unknown"


def build_source_ingestion_read_model(
    *,
    settings: Any,
    job_runtime: Any | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Project canonical source-ingestion containers and their JobStore rows."""
    containers, database = _load_containers(settings, limit=limit)
    jobs: list[dict[str, Any]] = []
    counts = {"queued": 0, "processing": 0, "completed": 0, "failed": 0, "unknown": 0}
    progress_values: list[float] = []
    for container in containers:
        phase = str(container.get("phase") or "")
        bucket = _bucket(phase)
        counts[bucket] = counts.get(bucket, 0) + 1
        job = _job_public(job_runtime, container.get("job_id"))
        measured = _progress_fields(container.get("progress") or {})
        if measured["progressPct"] is not None and bucket == "processing":
            progress_values.append(float(measured["progressPct"]))
        state = phase or "UNMEASURED"
        if job and job.get("state"):
            # JobStore state is authoritative for the job; container phase is the stage.
            job_state = str(job.get("state"))
        else:
            job_state = None
        jobs.append(
            {
                "id": container.get("container_source_id"),
                "jobId": container.get("job_id"),
                "source": container.get("filename") or container.get("container_source_id"),
                "type": container.get("archive_type"),
                "phase": phase or None,
                "state": job_state or state,
                "progressPct": measured["progressPct"],
                "throughput": measured["throughput"],
                "etaSeconds": measured["etaSeconds"],
                "elapsedSeconds": _number((container.get("progress") or {}).get("elapsed_seconds")),
                "worker": (job or {}).get("lease_owner") if job else None,
                "backend": (job or {}).get("worker_pool") if job else None,
                "error": redact_host_text(container["error"], limit=300) if container.get("error") else None,
                "cancelRequested": bool(container.get("cancel_requested")),
                "attempt": (job or {}).get("attempt_number") if job else None,
                "updatedAt": container.get("updated_at"),
                "createdAt": container.get("created_at"),
            }
        )
    overall = None
    if progress_values:
        overall = round(sum(progress_values) / len(progress_values), 2)
    elif counts["completed"] and not (counts["queued"] or counts["processing"] or counts["failed"] or counts["unknown"]):
        overall = 100.0

    # Executor ownership + idle/stall semantics for operator surfaces.
    try:
        from Data.modules.source_ingestion.worker import resolve_runner_mode

        executor_owner = resolve_runner_mode()
    except Exception:  # noqa: BLE001
        executor_owner = "UNMEASURED"

    idle_reason = None
    activity = "UNKNOWN"
    if counts["processing"] > 0:
        activity = "PROCESSING"
    elif counts["queued"] > 0:
        activity = "QUEUED"
    elif counts["failed"] > 0 and not counts["queued"] and not counts["processing"]:
        activity = "IDLE_WITH_FAILURES"
        idle_reason = "NO_QUEUED_WORK"
    elif not any(counts[k] for k in ("queued", "processing", "completed", "failed", "unknown")):
        activity = "IDLE_NO_WORK"
        idle_reason = "NO_QUEUED_WORK"
    else:
        activity = "IDLE"
        idle_reason = "NO_QUEUED_WORK"

    current = next((j for j in jobs if j.get("state") and str(j["state"]).upper() in {"RUNNING", "CLAIMED"}), None)
    last_failed = next((j for j in jobs if str(j.get("state") or "").upper() == "FAILED"), None)
    last_completed = next((j for j in jobs if str(j.get("state") or "").upper() == "COMPLETED"), None)

    return {
        "counts": {
            "queued": counts["queued"],
            "processing": counts["processing"],
            "completed": counts["completed"],
            "failed": counts["failed"],
            "unknown": counts["unknown"],
        },
        "overallProgressPct": overall,
        "jobs": jobs,
        "database": database or None,
        "executor_owner": executor_owner,
        "activity": activity,
        "idle_reason": idle_reason,
        "queue_depth": counts["queued"],
        "currently_processing": current,
        "last_failed": last_failed,
        "last_completed": last_completed,
        "sources_registered": "UNMEASURED",
        "sources_pending": counts["queued"],
        "sources_processing": counts["processing"],
        "sources_ingested": counts["completed"],
        "sources_failed": counts["failed"],
        "documents_created": "UNMEASURED",
        "chunks_created": "UNMEASURED",
        "truth": {
            "readOnly": True,
            "sourceIngestionNotDatasetLearning": True,
            "etaOnlyWhenStored": True,
            "missingThroughputIsNull": True,
            "emptyIsNotComplete": True,
            "partialIsNotComplete": True,
            "fabricOwnsProduction": executor_owner in {"fabric", "external"},
        },
    }


def _default_probe() -> dict[str, Any]:
    try:
        from Data.modules.workers.native_compute import probe_capabilities

        caps = probe_capabilities()
        if hasattr(caps, "public_dict"):
            payload = caps.public_dict()
        else:
            payload = {"status": "UNMEASURED", "detail": "probe returned an unknown shape"}
        return payload if isinstance(payload, dict) else {"status": "UNMEASURED"}
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "UNMEASURED",
            "protocolVersion": None,
            "operations": [],
            "binaryPath": None,
            "detail": f"probe_failed:{type(exc).__name__}",
            "truth": {"unmeasured": True},
        }


def _event_dicts(observability: Any, *, limit: int) -> list[dict[str, Any]]:
    if observability is None:
        return []
    try:
        raw = observability.query_history(limit=max(limit, 50), q="native")
    except Exception:  # noqa: BLE001
        raw = None
    if not isinstance(raw, list):
        try:
            recent = observability.recent(limit=200)
        except Exception:  # noqa: BLE001
            return []
        raw = []
        for item in recent:
            raw.append(item.public_dict() if hasattr(item, "public_dict") else item)
    matched: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        blob = json.dumps(item, default=str).lower()
        if any(hint in blob for hint in _NATIVE_EVENT_HINTS):
            matched.append(_redact_obj(item))
        if len(matched) >= limit:
            break
    return matched


def build_native_operations_read_model(
    *,
    observability: Any | None = None,
    probe_fn: Callable[[], Any] | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Native data-plane truth: probe plus bounded related events. Not a daemon fiction."""
    limit = max(1, min(int(limit), 100))
    probe_call = probe_fn or _default_probe
    try:
        probed = probe_call()
    except Exception as exc:  # noqa: BLE001
        probed = {"status": "UNMEASURED", "detail": f"probe_failed:{type(exc).__name__}"}
    if hasattr(probed, "public_dict"):
        probe = probed.public_dict()
    elif isinstance(probed, dict):
        probe = probed
    else:
        probe = {"status": "UNMEASURED", "detail": "probe returned an unknown shape"}
    status = str(probe.get("status") or "UNMEASURED")
    # A binary path is not availability. Only the probe status says AVAILABLE.
    available = status == "AVAILABLE"
    events = _event_dicts(observability, limit=limit)
    operations_out: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        operations_out.append(
            {
                "at": event.get("timestamp") or event.get("created_at") or event.get("at"),
                "level": event.get("level"),
                "message": event.get("message"),
                "operation": payload.get("operation") or payload.get("op"),
                "taskId": payload.get("taskId") or payload.get("task_id"),
                "backend": payload.get("backend"),
                "durationMs": payload.get("duration_ms") or payload.get("durationMs"),
                "peakRss": payload.get("peak_rss") or payload.get("peakRss"),
                "spillBytes": payload.get("spill_bytes") or payload.get("spillBytes"),
                "fallback": payload.get("fallback") or payload.get("fallback_reason"),
                "receiptValid": payload.get("receipt_valid") if "receipt_valid" in payload else payload.get("receiptValid"),
            }
        )
    return {
        "probe": {
            "status": status,
            "available": available,
            "protocolVersion": probe.get("protocolVersion") or probe.get("protocol_version"),
            "operations": list(probe.get("operations") or [])[:64],
            "binaryPath": probe.get("binaryPath") or probe.get("binary_path"),
            "backend": probe.get("backend") if isinstance(probe.get("backend"), dict) else None,
            "features": probe.get("features") if isinstance(probe.get("features"), dict) else None,
            "detail": redact_host_text(str(probe.get("detail") or ""), limit=400),
        },
        "recentOperations": operations_out,
        "stdoutTail": [],
        "role": "worker-fabric-accelerator",
        "daemon": False,
        "truth": {
            "readOnly": True,
            "binaryPathIsNotAvailable": True,
            "notASecondControlPlane": True,
            "noFabricatedCompileLog": True,
            "unmeasuredFieldsAreNull": True,
            "stdoutTailOnlyWhenCaptured": True,
            "gpuClaimRequiresProbeEvidence": True,
        },
    }


def _runtime_public(settings: Any) -> dict[str, Any]:
    runtime = getattr(settings, "runtime", None)
    host = getattr(runtime, "host", None) if runtime is not None else None
    port = getattr(runtime, "port", None) if runtime is not None else None
    loopback = getattr(runtime, "loopback_only", None) if runtime is not None else None
    return {
        "host": host,
        "port": port if isinstance(port, int) else None,
        "loopbackOnly": loopback if isinstance(loopback, bool) else None,
    }


def _database_rows(sqlite_manager: Any) -> list[dict[str, Any]]:
    if sqlite_manager is None or not hasattr(sqlite_manager, "list_databases"):
        return []
    try:
        rows = sqlite_manager.list_databases()
    except Exception as exc:  # noqa: BLE001
        return [
            {
                "domain": "UNMEASURED",
                "health": "UNMEASURED",
                "readiness": "UNMEASURED",
                "detail": f"list_failed:{type(exc).__name__}",
            }
        ]
    if not isinstance(rows, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        cleaned.append(
            {
                "domain": row.get("domain"),
                "exists": row.get("exists"),
                "health": row.get("health"),
                "readiness": row.get("readiness"),
                "sizeBytes": row.get("sizeBytes"),
                "schemaVersion": row.get("schemaVersion"),
                "journalMode": row.get("journalMode"),
                "tableCount": row.get("tableCount"),
            }
        )
    return cleaned


def build_host_overview(
    *,
    settings: Any,
    sqlite_manager: Any | None = None,
    job_runtime: Any | None = None,
    probe_fn: Callable[[], Any] | None = None,
    version: str = "",
) -> dict[str, Any]:
    """Small composition of existing owners. Does not call the LLM or sample workers."""
    ingestion = build_source_ingestion_read_model(settings=settings, job_runtime=job_runtime, limit=50)
    native = build_native_operations_read_model(probe_fn=probe_fn, limit=1)
    runtime = _runtime_public(settings)
    return {
        "version": version or None,
        "runtime": runtime,
        "databases": _database_rows(sqlite_manager),
        "native": native["probe"],
        "sourceIngestion": {
            "counts": ingestion["counts"],
            "overallProgressPct": ingestion["overallProgressPct"],
        },
        "watcher": {
            "status": "NOT_CONFIGURED",
            "detail": "No file-watcher owner is registered in the current runtime.",
        },
        "truth": {
            "readOnly": True,
            "doesNotMutate": True,
            "threeDatabasesRemainCanonical": True,
            "watcherNotInvented": True,
            "nativeIsAccelerator": True,
            "missingMetricsStayNull": True,
        },
    }
