"""Managed local serving workers — process supervision for Wave 3 (U021–U038).

Adapters only. The Model Control Plane owns registry/routing; this module
supervises local OpenAI-compatible serving processes (vLLM-class / llama.cpp).
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class InferenceJobClass(str, Enum):
    """Interactive traffic must not be starved by bulk work (U026 / U033)."""

    INTERACTIVE = "INTERACTIVE"
    BACKGROUND = "BACKGROUND"
    BATCH = "BATCH"


class WorkerState(str, Enum):
    STARTING = "STARTING"
    READY = "READY"
    DRAINING = "DRAINING"
    UNHEALTHY = "UNHEALTHY"
    STOPPED = "STOPPED"
    DEAD = "DEAD"  # process gone — honest recovery surface
    UNAVAILABLE = "UNAVAILABLE"  # binary/config missing — not a fake ready


@dataclass
class ServingWorker:
    worker_id: str
    provider_id: str
    model_id: str
    backend_kind: str  # vllm_class | llama_cpp | inproc
    endpoint: str
    state: WorkerState
    pid: int | None = None
    started_at: str | None = None
    last_health_at: str | None = None
    last_error: str | None = None
    health_score: float | None = None  # 0..1; None = unmeasured
    revision_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "backend_kind": self.backend_kind,
            "endpoint": self.endpoint,
            "state": self.state.value,
            "pid": self.pid,
            "started_at": self.started_at,
            "last_health_at": self.last_health_at,
            "last_error": self.last_error,
            "health_score": self.health_score,
            "revision_id": self.revision_id,
            "metadata": dict(self.metadata),
            "truth": {
                "dead_is_not_ready": self.state != WorkerState.READY,
                "unavailable_is_not_healthy": self.state
                not in (WorkerState.READY, WorkerState.DRAINING),
                "unmeasured_health_is_visible": self.health_score is None,
            },
        }


@dataclass
class StreamCancelToken:
    """Cooperative cancellation for true token streams (U025)."""

    cancelled: bool = False
    reason: str | None = None

    def cancel(self, reason: str = "client_disconnect") -> None:
        self.cancelled = True
        self.reason = reason


class ServingSupervisor:
    """Tracks managed serving workers and reconciles killed processes honestly."""

    def __init__(self) -> None:
        self._workers: dict[str, ServingWorker] = {}
        self._processes: dict[str, subprocess.Popen[Any]] = {}
        self._lock = threading.RLock()
        self._inproc_loaded: dict[str, dict[str, Any]] = {}

    def list_workers(self) -> list[ServingWorker]:
        with self._lock:
            self.reconcile()
            return list(self._workers.values())

    def get_worker(self, worker_id: str) -> ServingWorker | None:
        with self._lock:
            self.reconcile()
            return self._workers.get(worker_id)

    def workers_for_model(self, model_id: str) -> list[ServingWorker]:
        return [w for w in self.list_workers() if w.model_id == model_id]

    def start_inproc(
        self,
        *,
        provider_id: str,
        model_id: str,
        revision_id: str | None = None,
        endpoint: str = "inproc://local",
        backend_kind: str = "inproc",
    ) -> ServingWorker:
        """Test/dev backend: no external binary; load is in-process residency."""
        worker_id = str(uuid.uuid4())
        worker = ServingWorker(
            worker_id=worker_id,
            provider_id=provider_id,
            model_id=model_id,
            backend_kind=backend_kind,
            endpoint=endpoint,
            state=WorkerState.READY,
            pid=os.getpid(),
            started_at=_utc_now(),
            last_health_at=_utc_now(),
            health_score=1.0,
            revision_id=revision_id or f"inproc:{model_id}",
            metadata={"managed": True, "inproc": True},
        )
        with self._lock:
            self._workers[worker_id] = worker
            self._inproc_loaded[worker_id] = {
                "model_id": model_id,
                "loaded_at": _utc_now(),
            }
        return worker

    def start_subprocess(
        self,
        *,
        provider_id: str,
        model_id: str,
        backend_kind: str,
        command: list[str],
        endpoint: str,
        revision_id: str | None = None,
        env: dict[str, str] | None = None,
        ready_check: Callable[[], bool] | None = None,
        ready_timeout_seconds: float = 30.0,
    ) -> ServingWorker:
        """Start a managed serving binary. Missing binary → UNAVAILABLE, not READY."""
        worker_id = str(uuid.uuid4())
        if not command:
            worker = ServingWorker(
                worker_id=worker_id,
                provider_id=provider_id,
                model_id=model_id,
                backend_kind=backend_kind,
                endpoint=endpoint,
                state=WorkerState.UNAVAILABLE,
                last_error="empty command — serving binary not configured",
                revision_id=revision_id,
            )
            with self._lock:
                self._workers[worker_id] = worker
            return worker

        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env={**os.environ, **(env or {})},
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            worker = ServingWorker(
                worker_id=worker_id,
                provider_id=provider_id,
                model_id=model_id,
                backend_kind=backend_kind,
                endpoint=endpoint,
                state=WorkerState.UNAVAILABLE,
                last_error=f"serving binary not found: {exc}",
                revision_id=revision_id,
            )
            with self._lock:
                self._workers[worker_id] = worker
            return worker
        except OSError as exc:
            worker = ServingWorker(
                worker_id=worker_id,
                provider_id=provider_id,
                model_id=model_id,
                backend_kind=backend_kind,
                endpoint=endpoint,
                state=WorkerState.UNAVAILABLE,
                last_error=str(exc),
                revision_id=revision_id,
            )
            with self._lock:
                self._workers[worker_id] = worker
            return worker

        worker = ServingWorker(
            worker_id=worker_id,
            provider_id=provider_id,
            model_id=model_id,
            backend_kind=backend_kind,
            endpoint=endpoint,
            state=WorkerState.STARTING,
            pid=proc.pid,
            started_at=_utc_now(),
            revision_id=revision_id,
            metadata={"command": command[:1]},
        )
        with self._lock:
            self._workers[worker_id] = worker
            self._processes[worker_id] = proc

        deadline = time.monotonic() + ready_timeout_seconds
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                err = ""
                try:
                    err = (proc.stderr.read() or b"").decode("utf-8", errors="replace")[:400]
                except Exception:  # noqa: BLE001
                    err = "process exited during start"
                worker.state = WorkerState.DEAD
                worker.last_error = err or f"exit code {proc.returncode}"
                return worker
            if ready_check is None or ready_check():
                worker.state = WorkerState.READY
                worker.last_health_at = _utc_now()
                worker.health_score = 1.0
                return worker
            time.sleep(0.1)

        worker.state = WorkerState.UNHEALTHY
        worker.last_error = "ready timeout — process still starting or unhealthy"
        worker.health_score = 0.0
        return worker

    def stop(self, worker_id: str, *, drain: bool = True) -> ServingWorker:
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker is None:
                raise KeyError(worker_id)
            if drain and worker.state == WorkerState.READY:
                worker.state = WorkerState.DRAINING
            proc = self._processes.pop(worker_id, None)
            self._inproc_loaded.pop(worker_id, None)
            if proc is not None and proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    try:
                        proc.terminate()
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        proc.kill()
            worker.state = WorkerState.STOPPED
            worker.pid = None
            worker.health_score = 0.0
            worker.last_health_at = _utc_now()
            return worker

    def mark_dead(self, worker_id: str, reason: str) -> ServingWorker:
        with self._lock:
            worker = self._workers[worker_id]
            worker.state = WorkerState.DEAD
            worker.last_error = reason
            worker.health_score = 0.0
            worker.last_health_at = _utc_now()
            self._processes.pop(worker_id, None)
            self._inproc_loaded.pop(worker_id, None)
            return worker

    def update_health(
        self,
        worker_id: str,
        *,
        score: float | None,
        healthy: bool,
        detail: str | None = None,
    ) -> ServingWorker:
        with self._lock:
            worker = self._workers[worker_id]
            worker.health_score = score
            worker.last_health_at = _utc_now()
            if not healthy:
                if worker.state not in (WorkerState.DEAD, WorkerState.STOPPED, WorkerState.UNAVAILABLE):
                    worker.state = WorkerState.UNHEALTHY
                worker.last_error = detail
            elif worker.state in (WorkerState.UNHEALTHY, WorkerState.STARTING, WorkerState.DRAINING):
                worker.state = WorkerState.READY
                worker.last_error = None
            return worker

    def reconcile(self) -> list[ServingWorker]:
        """Detect killed workers → DEAD (honest). Never leave them as READY."""
        changed: list[ServingWorker] = []
        with self._lock:
            for worker_id, worker in list(self._workers.items()):
                if worker.backend_kind == "inproc":
                    continue
                proc = self._processes.get(worker_id)
                if proc is None:
                    if worker.state in (WorkerState.READY, WorkerState.STARTING, WorkerState.DRAINING):
                        # Lost process handle but claimed live — mark dead.
                        if worker.pid is not None and not _pid_alive(worker.pid):
                            worker.state = WorkerState.DEAD
                            worker.last_error = "serving worker process gone (reconcile)"
                            worker.health_score = 0.0
                            worker.last_health_at = _utc_now()
                            changed.append(worker)
                    continue
                if proc.poll() is not None:
                    worker.state = WorkerState.DEAD
                    worker.last_error = (
                        f"serving worker exited with code {proc.returncode}"
                    )
                    worker.health_score = 0.0
                    worker.last_health_at = _utc_now()
                    worker.pid = None
                    self._processes.pop(worker_id, None)
                    changed.append(worker)
        return changed


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


# Process-wide supervisor used by managed adapters (one per deployment).
_GLOBAL_SUPERVISOR: ServingSupervisor | None = None


def get_serving_supervisor() -> ServingSupervisor:
    global _GLOBAL_SUPERVISOR
    if _GLOBAL_SUPERVISOR is None:
        _GLOBAL_SUPERVISOR = ServingSupervisor()
    return _GLOBAL_SUPERVISOR


def reset_serving_supervisor_for_tests() -> ServingSupervisor:
    global _GLOBAL_SUPERVISOR
    _GLOBAL_SUPERVISOR = ServingSupervisor()
    return _GLOBAL_SUPERVISOR
