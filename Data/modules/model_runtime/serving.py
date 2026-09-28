"""Managed local serving workers — process supervision for Wave 3 (U021–U038).

Adapters only. The Model Control Plane owns registry/routing; this module
supervises local OpenAI-compatible serving processes (vLLM-class / llama.cpp).
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
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
    serving_generation: int = 0
    managed_by_leviathan: bool = True
    restart_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        # Never expose full command lines / secrets.
        safe_meta = {
            k: v
            for k, v in dict(self.metadata).items()
            if k
            not in {
                "env",
                "full_command",
                "api_key",
                "command_argv",
            }
        }
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
            "servingGeneration": self.serving_generation,
            "managedByLeviathan": self.managed_by_leviathan,
            "restartCount": self.restart_count,
            "metadata": safe_meta,
            "truth": {
                "dead_is_not_ready": self.state != WorkerState.READY,
                "unavailable_is_not_healthy": self.state
                not in (WorkerState.READY, WorkerState.DRAINING),
                "unmeasured_health_is_visible": self.health_score is None,
                "process_existence_is_not_ready": True,
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

    def __init__(self, *, registry_path: Path | str | None = None) -> None:
        self._workers: dict[str, ServingWorker] = {}
        self._processes: dict[str, subprocess.Popen[Any]] = {}
        self._lock = threading.RLock()
        self._inproc_loaded: dict[str, dict[str, Any]] = {}
        self._stderr_tails: dict[str, str] = {}
        self._stderr_threads: dict[str, threading.Thread] = {}
        self._generation_counter = 0
        self._start_attempts: dict[str, list[float]] = {}
        self.registry_path = Path(registry_path) if registry_path else None
        if self.registry_path is not None:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            self.reconcile_persisted_orphans()

    def _next_generation(self) -> int:
        self._generation_counter += 1
        return self._generation_counter

    def _record_start_attempt(self, model_id: str) -> int:
        now = time.monotonic()
        window = self._start_attempts.setdefault(model_id, [])
        window.append(now)
        # Keep 5 minutes of attempts for crash-loop detection.
        self._start_attempts[model_id] = [t for t in window if now - t < 300.0]
        return len(self._start_attempts[model_id])

    def crash_loop_detected(self, model_id: str, *, threshold: int = 5) -> bool:
        attempts = self._start_attempts.get(model_id) or []
        now = time.monotonic()
        recent = [t for t in attempts if now - t < 300.0]
        return len(recent) >= threshold

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
        from Data.modules.model_runtime.execution_gate import allow_process_ownership

        if not allow_process_ownership():
            from Data.modules.model_runtime.execution_gate import refuse_inline_serving

            refuse_inline_serving(reason="inproc_banned_in_production_api")
        worker_id = str(uuid.uuid4())
        generation = self._next_generation()
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
            serving_generation=generation,
            managed_by_leviathan=True,
            metadata={
                "managed": True,
                "inproc": True,
                "serving_generation": generation,
                "fixture_only": True,
            },
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
        managed_by_leviathan: bool = True,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ServingWorker:
        """Start a managed serving binary. Missing binary → UNAVAILABLE, not READY."""
        from Data.modules.model_runtime.env_policy import build_serving_child_env
        from Data.modules.model_runtime.execution_gate import (
            allow_process_ownership,
            refuse_inline_serving,
        )
        from Data.modules.model_runtime.process_control import spawn_owned_process

        if not allow_process_ownership():
            refuse_inline_serving(reason="subprocess_spawn_banned_in_api")

        worker_id = str(uuid.uuid4())
        generation = self._next_generation()
        attempts = self._record_start_attempt(model_id)
        if self.crash_loop_detected(model_id):
            worker = ServingWorker(
                worker_id=worker_id,
                provider_id=provider_id,
                model_id=model_id,
                backend_kind=backend_kind,
                endpoint=endpoint,
                state=WorkerState.UNAVAILABLE,
                last_error="CRASH_LOOP — repeated rapid start failures; operator action required",
                revision_id=revision_id,
                serving_generation=generation,
                managed_by_leviathan=managed_by_leviathan,
                restart_count=attempts,
                metadata={"crash_loop": True, "start_attempts": attempts},
            )
            with self._lock:
                self._workers[worker_id] = worker
            return worker

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
                serving_generation=generation,
                managed_by_leviathan=managed_by_leviathan,
            )
            with self._lock:
                self._workers[worker_id] = worker
            return worker

        # argv only — never shell=True. Bounded env — never full host secrets.
        child_env = build_serving_child_env(env)
        try:
            proc = spawn_owned_process(list(command), env=child_env)
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
                serving_generation=generation,
                managed_by_leviathan=managed_by_leviathan,
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
                serving_generation=generation,
                managed_by_leviathan=managed_by_leviathan,
            )
            with self._lock:
                self._workers[worker_id] = worker
            return worker

        self._start_stderr_drain(worker_id, proc)

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
            serving_generation=generation,
            managed_by_leviathan=managed_by_leviathan,
            restart_count=max(0, attempts - 1),
            metadata={
                "command": command[:1],
                "serving_generation": generation,
                "launch_fingerprint": f"{generation}:{proc.pid}:{endpoint}",
            },
        )
        with self._lock:
            self._workers[worker_id] = worker
            self._processes[worker_id] = proc

        deadline = time.monotonic() + ready_timeout_seconds
        while time.monotonic() < deadline:
            if cancel_check is not None and cancel_check():
                from Data.modules.model_runtime.process_control import (
                    terminate_owned_process,
                )

                terminate_owned_process(proc)
                worker.state = WorkerState.STOPPED
                worker.last_error = "MODEL_LOAD_CANCELLED during STARTING"
                worker.pid = None
                with self._lock:
                    self._processes.pop(worker_id, None)
                self._persist_registry()
                return worker
            if proc.poll() is not None:
                err = self._stderr_tail(worker_id) or ""
                if not err:
                    try:
                        # Drain thread may still be finishing; best-effort leftover read.
                        if proc.stderr is not None:
                            err = (proc.stderr.read() or b"").decode(
                                "utf-8", errors="replace"
                            )[:400]
                    except Exception:  # noqa: BLE001
                        err = "process exited during start"
                worker.state = WorkerState.DEAD
                worker.last_error = err or f"exit code {proc.returncode}"
                self._persist_registry()
                return worker
            # READY only after health proof — never claim READY without ready_check.
            if ready_check is not None and ready_check():
                worker.state = WorkerState.READY
                worker.last_health_at = _utc_now()
                worker.health_score = 1.0
                self._persist_registry()
                return worker
            if ready_check is None:
                # Process alive but unproven — leave STARTING for health reconcile.
                self._persist_registry()
                return worker
            time.sleep(0.1)

        worker.state = WorkerState.UNHEALTHY
        worker.last_error = "ready timeout — process still starting or unhealthy"
        worker.health_score = 0.0
        self._persist_registry()
        return worker

    def _start_stderr_drain(self, worker_id: str, proc: subprocess.Popen[Any]) -> None:
        """Background reader so PIPE stderr cannot fill and stall the child."""

        def _drain() -> None:
            chunks: list[str] = []
            total = 0
            try:
                stream = proc.stderr
                if stream is None:
                    return
                while True:
                    raw = stream.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace")
                    chunks.append(line)
                    total += len(line)
                    # Bound retained tail to avoid unbounded memory.
                    while total > 8_000 and chunks:
                        dropped = chunks.pop(0)
                        total -= len(dropped)
            except Exception:  # noqa: BLE001
                pass
            with self._lock:
                self._stderr_tails[worker_id] = "".join(chunks)[-400:]

        thread = threading.Thread(
            target=_drain,
            name=f"serving-stderr-{worker_id[:8]}",
            daemon=True,
        )
        self._stderr_threads[worker_id] = thread
        thread.start()

    def _stderr_tail(self, worker_id: str) -> str:
        with self._lock:
            return str(self._stderr_tails.get(worker_id) or "")

    def stop(
        self,
        worker_id: str,
        *,
        drain: bool = True,
        expected_generation: int | None = None,
        force: bool = False,
    ) -> ServingWorker:
        from Data.modules.model_runtime.process_control import terminate_owned_process

        with self._lock:
            worker = self._workers.get(worker_id)
            if worker is None:
                raise KeyError(worker_id)
            if not worker.managed_by_leviathan:
                worker.last_error = (
                    "refusing to stop operator-owned / unmanaged serving process"
                )
                return worker
            if (
                expected_generation is not None
                and worker.serving_generation
                and int(expected_generation) != int(worker.serving_generation)
            ):
                worker.last_error = (
                    f"stale unload generation {expected_generation} "
                    f"(current={worker.serving_generation}); not stopped"
                )
                return worker
            if drain and worker.state == WorkerState.READY:
                worker.state = WorkerState.DRAINING
            proc = self._processes.pop(worker_id, None)
            self._inproc_loaded.pop(worker_id, None)
            stop_meta: dict[str, Any] = {"forced": False}
            if proc is not None and proc.poll() is None:
                stop_meta = terminate_owned_process(
                    proc,
                    graceful_timeout_seconds=0.1 if force else 5.0,
                    force_timeout_seconds=3.0,
                )
            worker.state = WorkerState.STOPPED
            worker.pid = None
            worker.health_score = 0.0
            worker.last_health_at = _utc_now()
            if stop_meta.get("forced"):
                worker.metadata = {
                    **dict(worker.metadata or {}),
                    "forced": True,
                }
            self._persist_registry()
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
        if changed:
            self._persist_registry()
        return changed

    def reconcile_persisted_orphans(self) -> list[ServingWorker]:
        """MODEL-002: after API restart, reconcile prior managed children.

        Ownership proof uses (pid, start identity fingerprint, endpoint). Never
        kill a process solely because a PID number is reused by an unrelated
        process.
        """
        import json

        if self.registry_path is None or not self.registry_path.is_file():
            return []
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return []
        entries = list(raw.get("workers") or [])
        changed: list[ServingWorker] = []
        for entry in entries:
            worker_id = str(entry.get("worker_id") or "")
            if not worker_id:
                continue
            pid = entry.get("pid")
            endpoint = str(entry.get("endpoint") or "")
            fingerprint = str(entry.get("pid_fingerprint") or "")
            state = str(entry.get("state") or WorkerState.DEAD.value)
            alive = isinstance(pid, int) and _pid_alive(int(pid))
            same_identity = alive and fingerprint and fingerprint == _pid_fingerprint(int(pid))
            if not same_identity:
                # Stale PID / reuse / gone — record as DEAD orphan, do not kill.
                worker = ServingWorker(
                    worker_id=worker_id,
                    provider_id=str(entry.get("provider_id") or ""),
                    model_id=str(entry.get("model_id") or ""),
                    backend_kind=str(entry.get("backend_kind") or "unknown"),
                    endpoint=endpoint,
                    state=WorkerState.DEAD,
                    pid=int(pid) if isinstance(pid, int) else None,
                    started_at=entry.get("started_at"),
                    last_error="orphan reconcile: pid gone or reused — not killed",
                    health_score=0.0,
                    last_health_at=_utc_now(),
                    revision_id=entry.get("revision_id"),
                    serving_generation=int(entry.get("serving_generation") or 0),
                    managed_by_leviathan=bool(entry.get("managed_by_leviathan", True)),
                    metadata={
                        "orphan_reconciled": True,
                        "prior_state": state,
                        "pid_alive": alive,
                        "identity_matched": bool(same_identity),
                    },
                )
            else:
                # Still our process — adopt as UNHEALTHY until health proves READY.
                worker = ServingWorker(
                    worker_id=worker_id,
                    provider_id=str(entry.get("provider_id") or ""),
                    model_id=str(entry.get("model_id") or ""),
                    backend_kind=str(entry.get("backend_kind") or "unknown"),
                    endpoint=endpoint,
                    state=WorkerState.UNHEALTHY,
                    pid=int(pid),
                    started_at=entry.get("started_at"),
                    last_error="adopted after control-plane restart — awaiting health",
                    health_score=None,
                    last_health_at=_utc_now(),
                    revision_id=entry.get("revision_id"),
                    serving_generation=int(entry.get("serving_generation") or 0),
                    managed_by_leviathan=bool(entry.get("managed_by_leviathan", True)),
                    metadata={
                        "orphan_reconciled": True,
                        "adopted": True,
                        "pid_fingerprint": fingerprint,
                    },
                )
            with self._lock:
                self._workers[worker_id] = worker
            changed.append(worker)
        self._persist_registry()
        return changed

    def _persist_registry(self) -> None:
        import json

        if self.registry_path is None:
            return
        with self._lock:
            workers = []
            for w in self._workers.values():
                if w.backend_kind == "inproc":
                    continue
                if w.state in (WorkerState.STOPPED, WorkerState.UNAVAILABLE):
                    continue
                workers.append(
                    {
                        "worker_id": w.worker_id,
                        "provider_id": w.provider_id,
                        "model_id": w.model_id,
                        "backend_kind": w.backend_kind,
                        "endpoint": w.endpoint,
                        "state": w.state.value,
                        "pid": w.pid,
                        "started_at": w.started_at,
                        "revision_id": w.revision_id,
                        "serving_generation": w.serving_generation,
                        "managed_by_leviathan": w.managed_by_leviathan,
                        "pid_fingerprint": _pid_fingerprint(w.pid) if w.pid else "",
                    }
                )
            payload = {"updated_at": _utc_now(), "workers": workers}
        try:
            tmp = self.registry_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.registry_path)
        except OSError:
            pass


def _pid_fingerprint(pid: int | None) -> str:
    """Best-effort identity for a PID to detect reuse without scanning / killing."""
    from Data.modules.common.process import pid_fingerprint

    return pid_fingerprint(pid)


def _pid_alive(pid: int) -> bool:
    from Data.modules.common.process import pid_is_alive

    return pid_is_alive(pid)


# Process-wide supervisor used by managed adapters (one per deployment).
_GLOBAL_SUPERVISOR: ServingSupervisor | None = None


def default_serving_registry_path() -> Path:
    """Durable registry beside CONTROL so API restart can reconcile orphans."""
    try:
        from Data.modules.common.database_domains import resolve_control_database_path

        return resolve_control_database_path().parent / "serving_registry.json"
    except Exception:  # noqa: BLE001 — keep serving usable without settings bootstrap
        return Path("Data/backend/data/serving_registry.json")


def get_serving_supervisor() -> ServingSupervisor:
    global _GLOBAL_SUPERVISOR
    if _GLOBAL_SUPERVISOR is None:
        raw = (os.environ.get("LEVIATHAN_SERVING_REGISTRY_PATH") or "").strip()
        registry = Path(raw) if raw else default_serving_registry_path()
        _GLOBAL_SUPERVISOR = ServingSupervisor(registry_path=registry)
    return _GLOBAL_SUPERVISOR


def reset_serving_supervisor_for_tests(
    *, registry_path: Path | str | None = None
) -> ServingSupervisor:
    global _GLOBAL_SUPERVISOR
    _GLOBAL_SUPERVISOR = ServingSupervisor(registry_path=registry_path)
    return _GLOBAL_SUPERVISOR
