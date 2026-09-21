"""Offline dataset-brain job management for HADES.

This module stays lightweight and manages background materialization/indexing jobs.
The worker owns runtime job-state writes after spawn; HF tokens travel only through
the child environment and are never persisted.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from training_service import DATASET_RECORD_ID_RE, TrainingWorkspace

BRAIN_JOB_ID_RE = re.compile(r"^brain_[0-9a-f]{16}$")
_ACTIVE = {"queued", "running", "cancelling"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_name = handle.name
        os.replace(temp_name, path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Verwacht JSON-object in {path.name}.")
    return value


def _safe_dataset_id(dataset_id: str) -> str:
    value = str(dataset_id or "")
    if not DATASET_RECORD_ID_RE.fullmatch(value):
        raise KeyError(dataset_id)
    return value


def _safe_job_id(job_id: str) -> str:
    value = str(job_id or "")
    if not BRAIN_JOB_ID_RE.fullmatch(value):
        raise KeyError(job_id)
    return value


def _pid_alive(pid: Any) -> bool:
    """Return whether a worker PID is alive without mutating the process.

    ``os.kill(pid, 0)`` is the conventional POSIX probe, but it is destructive on
    Windows because Python routes non-CTRL signals through ``TerminateProcess``.
    Windows therefore uses read-only process-handle inspection instead.
    """
    try:
        value = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL

            handle = kernel32.OpenProcess(process_query_limited_information, False, value)
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return int(exit_code.value) == still_active
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return False

    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # EPERM still proves the PID exists.
        return True
    except OSError:
        return False
    return True


def brain_dir(training_root: Path, dataset_id: str) -> Path:
    return training_root / "datasets" / _safe_dataset_id(dataset_id) / "brain"


def manifest_path(training_root: Path, dataset_id: str) -> Path:
    return brain_dir(training_root, dataset_id) / "manifest.json"


def read_manifest(training_root: Path, dataset_id: str) -> dict[str, Any] | None:
    path = manifest_path(training_root, dataset_id)
    if not path.is_file():
        return None
    try:
        value = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if value.get("dataset_id") != dataset_id:
        return None
    return value


def write_manifest(training_root: Path, dataset_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    path = manifest_path(training_root, dataset_id)
    current = read_manifest(training_root, dataset_id) or {
        "version": 1,
        "dataset_id": dataset_id,
        "status": "not_indexed",
        "materialized_rows": 0,
        "materialized_complete": False,
        "indexed_rows": 0,
        "chunks_indexed": 0,
        "source_id": None,
        "snapshot_path": str(brain_dir(training_root, dataset_id) / "data.jsonl"),
        "snapshot_bytes": 0,
        "error": None,
        "created_at": utc_now(),
    }
    current.update(updates)
    current["updated_at"] = utc_now()
    _atomic_json(path, current)
    return current


def write_brain_job_state(job_path: str | Path, updates: dict[str, Any]) -> dict[str, Any]:
    path = Path(job_path)
    current = _read_json(path)
    current.update(updates)
    current["updated_at"] = utc_now()
    _atomic_json(path, current)
    return current


class DatasetBrainManager:
    def __init__(self, training_root: str | Path, database_path: str | Path):
        self.root = Path(training_root).expanduser().resolve()
        self.database_path = Path(database_path).expanduser().resolve()
        self.workspace = TrainingWorkspace(self.root)
        self.jobs_dir = self.root / "brain_jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_database(cls, database: Any) -> "DatasetBrainManager":
        db_path = Path(str(database.path)).expanduser().resolve()
        return cls(db_path.parent / "training", db_path)

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_dir / _safe_job_id(job_id) / "job.json"

    @staticmethod
    def _job_pid(path: Path, item: dict[str, Any]) -> int | None:
        try:
            embedded = int(item.get("pid") or 0)
        except (TypeError, ValueError):
            embedded = 0
        if embedded > 0:
            return embedded
        pid_file = path.parent / "worker.pid"
        try:
            value = int(pid_file.read_text(encoding="ascii").strip()) if pid_file.is_file() else 0
        except (OSError, ValueError):
            value = 0
        return value if value > 0 else None

    def _reconcile_job(self, path: Path, item: dict[str, Any]) -> dict[str, Any]:
        if item.get("status") not in _ACTIVE:
            return item
        pid = self._job_pid(path, item)
        if _pid_alive(pid):
            return {**item, "pid": pid}
        interrupted = write_brain_job_state(
            path,
            {
                "status": "interrupted",
                "pid": pid,
                "error": "Brain-worker draaide niet meer; veilig checkpoint kan worden hervat.",
                "finished_at": utc_now(),
            },
        )
        try:
            write_manifest(
                self.root,
                str(item.get("dataset_id") or ""),
                {"status": "interrupted", "active_job_id": None, "error": "worker_interrupted_resume_available"},
            )
        except Exception:
            pass
        return interrupted

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        if not path.is_file():
            raise KeyError(job_id)
        return self._reconcile_job(path, _read_json(path))

    def list_jobs(self, *, dataset_id: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for child in self.jobs_dir.iterdir() if self.jobs_dir.exists() else []:
            path = child / "job.json"
            if not path.is_file():
                continue
            try:
                item = _read_json(path)
                if BRAIN_JOB_ID_RE.fullmatch(str(item.get("id") or "")):
                    item = self._reconcile_job(path, item)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if not BRAIN_JOB_ID_RE.fullmatch(str(item.get("id") or "")):
                continue
            if dataset_id and item.get("dataset_id") != dataset_id:
                continue
            items.append(item)
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return items

    def status(self, dataset_id: str) -> dict[str, Any]:
        dataset_id = _safe_dataset_id(dataset_id)
        self.workspace.get_dataset(dataset_id)
        manifest = read_manifest(self.root, dataset_id) or {
            "dataset_id": dataset_id,
            "status": "not_indexed",
            "materialized_rows": 0,
            "materialized_complete": False,
            "indexed_rows": 0,
            "chunks_indexed": 0,
            "source_id": None,
            "snapshot_path": str(brain_dir(self.root, dataset_id) / "data.jsonl"),
            "snapshot_bytes": 0,
            "error": None,
        }
        latest = next(iter(self.list_jobs(dataset_id=dataset_id)), None)
        if latest and latest.get("status") in _ACTIVE:
            manifest = {**manifest, "status": latest.get("status"), "active_job_id": latest.get("id")}
        elif latest:
            # Durable terminal/interrupted job wins over a stale active-looking
            # manifest when best-effort manifest compensation failed.
            updates: dict[str, Any] = {"latest_job_id": latest.get("id")}
            manifest_status = str(manifest.get("status") or "").lower()
            if manifest_status in _ACTIVE:
                updates["status"] = latest.get("status")
                updates["active_job_id"] = None
                if latest.get("error"):
                    updates["error"] = latest.get("error")
            manifest = {**manifest, **updates}
        snapshot = Path(str(manifest.get("snapshot_path") or ""))
        manifest["snapshot_exists"] = snapshot.is_file()
        manifest["snapshot_size_bytes"] = snapshot.stat().st_size if snapshot.is_file() else 0
        return manifest

    def statuses(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for dataset in self.workspace.list_datasets():
            try:
                item = self.status(str(dataset["id"]))
            except Exception as exc:
                item = {"dataset_id": dataset.get("id"), "status": "error", "error": f"{type(exc).__name__}: {exc}"}
            item["dataset_name"] = dataset.get("name")
            item["source_type"] = dataset.get("source_type")
            out.append(item)
        return out

    def create_job(
        self,
        *,
        dataset_id: str,
        token: str | None = None,
        rebuild_index: bool = False,
        rematerialize: bool = False,
        launch: bool = True,
    ) -> dict[str, Any]:
        dataset_id = _safe_dataset_id(dataset_id)
        dataset = self.workspace.get_dataset(dataset_id)
        for existing in self.list_jobs(dataset_id=dataset_id):
            if existing.get("status") in _ACTIVE:
                raise ValueError("Deze dataset heeft al een actieve Brain-indexering.")

        job_id = f"brain_{secrets.token_hex(8)}"
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        now = utc_now()
        job = {
            "id": job_id,
            "dataset_id": dataset_id,
            "dataset_name": dataset.get("name"),
            "source_type": dataset.get("source_type"),
            "status": "queued",
            "phase": "queued",
            "progress": 0.0,
            "materialized_rows": 0,
            "indexed_rows": 0,
            "chunks_indexed": 0,
            "database_path": str(self.database_path),
            "training_root": str(self.root),
            "snapshot_path": str(brain_dir(self.root, dataset_id) / "data.jsonl"),
            "log_path": str(job_dir / "brain.log"),
            "rebuild_index": bool(rebuild_index),
            "rematerialize": bool(rematerialize),
            "pid": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        job_path = job_dir / "job.json"
        _atomic_json(job_path, job)
        write_manifest(self.root, dataset_id, {"status": "queued", "active_job_id": job_id, "error": None})
        if not launch:
            return job

        worker_path = Path(__file__).resolve().parent / "dataset_brain_worker.py"
        env = os.environ.copy()
        if token and token.strip():
            env["HF_TOKEN"] = token.strip()
        log_handle = (job_dir / "brain.log").open("ab", buffering=0)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                [sys.executable, str(worker_path), "--job", str(job_path)],
                cwd=str(worker_path.parent),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creationflags,
            )
            (job_dir / "worker.pid").write_text(str(process.pid), encoding="ascii")
        except Exception as exc:
            write_manifest(self.root, dataset_id, {"status": "failed", "active_job_id": None, "error": str(exc)[:4000]})
            return write_brain_job_state(
                job_path,
                {"status": "failed", "error": f"Brain-worker starten mislukt: {exc}", "finished_at": utc_now()},
            )
        finally:
            try:
                log_handle.close()
            except OSError:
                pass
        # Worker is the sole job-state writer from this point onward; do not race it.
        current = _read_json(job_path)
        return {**current, "status": current.get("status") if current.get("status") != "queued" else "running", "pid": process.pid}

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job.get("status") not in _ACTIVE:
            return job
        (self._job_path(job_id).parent / "cancel.requested").write_text("cancel\n", encoding="utf-8")
        write_manifest(self.root, str(job["dataset_id"]), {"status": "cancelling"})
        return write_brain_job_state(self._job_path(job_id), {"status": "cancelling"})

    def tail_log(self, job_id: str, *, max_bytes: int = 96_000) -> str:
        job = self.get_job(job_id)
        path = Path(str(job.get("log_path") or ""))
        if not path.is_file():
            return ""
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, os.SEEK_END)
            data = handle.read(max_bytes)
        return data.decode("utf-8", errors="replace")

    def remove_dataset_brain(self, dataset_id: str, *, platform_db: Any | None = None) -> dict[str, Any]:
        dataset_id = _safe_dataset_id(dataset_id)
        self.workspace.get_dataset(dataset_id)
        for job in self.list_jobs(dataset_id=dataset_id):
            if job.get("status") in _ACTIVE:
                raise ValueError("Stop eerst de actieve Brain-indexering voor deze dataset.")
        source_removed = 0
        source_id: str | None = None
        if platform_db is not None:
            source = platform_db.get_knowledge_source_by_uri("dataset", f"dataset://{dataset_id}")
            if source:
                source_id = str(source.get("id") or "") or None
                source_removed = int(platform_db.delete_knowledge_source(source_id)) if source_id else 0
        shutil.rmtree(brain_dir(self.root, dataset_id), ignore_errors=True)
        for job in list(self.list_jobs(dataset_id=dataset_id)):
            shutil.rmtree(self._job_path(str(job["id"])).parent, ignore_errors=True)
        return {"dataset_id": dataset_id, "removed": True, "source_id": source_id, "knowledge_source_removed": bool(source_removed)}
