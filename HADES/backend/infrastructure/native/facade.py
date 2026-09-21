"""NativeRuntimeFacade — public Python API for the C++ companion.

Composes supervisor + transport + typed clients. Preserves the historical
NativeRuntimeClient method surface used by PluginManager and routes.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .clients import NativeFilesystemClient, NativeMetricsClient, NativeProcessClient, NativeServiceClient
from .errors import NativeRuntimeError
from .supervisor import NativeSupervisor
from .transport import PROTOCOL_VERSION, RpcTransport

logger = logging.getLogger("hades.native_runtime")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def locate_native_executable(root: Path | None = None) -> Path | None:
    """Stable production location first; never search random build trees in prod."""
    base = root or repo_root()
    candidates = [
        base / "runtime" / "native" / "hades_native_runtime.exe",
        base / "runtime" / "native" / "hades_native_runtime",
    ]
    if os.environ.get("HADES_NATIVE_DEV_SEARCH", "").strip() in {"1", "true", "yes"}:
        candidates.extend(
            [
                base / "native" / "build" / "hades_native_runtime.exe",
                base / "native" / "build" / "hades_native_runtime",
                base / "native" / "build" / "Release" / "hades_native_runtime.exe",
                base / "native" / "build" / "Debug" / "hades_native_runtime.exe",
            ]
        )
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    for path in candidates:
        if path.is_file():
            return path
    return None


@dataclass
class NativeStatus:
    mode: str = "auto"
    available: bool = False
    connected: bool = False
    version: str | None = None
    protocol_version: int | None = None
    compiler: str | None = None
    uptime_ms: int | None = None
    capabilities: list[str] = field(default_factory=list)
    fallback_active: bool = True
    executable: str | None = None
    last_error: str | None = None
    process_count: int | None = None
    service_count: int | None = None
    generation: int | None = None
    restart_count: int | None = None
    crash_count: int | None = None
    last_crash_reason: str | None = None
    workers: int | None = None
    queued_jobs: int | None = None
    active_jobs: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "available": self.available,
            "connected": self.connected,
            "version": self.version,
            "protocol_version": self.protocol_version,
            "compiler": self.compiler,
            "uptime_ms": self.uptime_ms,
            "capabilities": list(self.capabilities),
            "fallback_active": self.fallback_active,
            "executable": self.executable,
            "last_error": self.last_error,
            "process_count": self.process_count,
            "service_count": self.service_count,
            "generation": self.generation,
            "restart_count": self.restart_count,
            "crash_count": self.crash_count,
            "last_crash_reason": self.last_crash_reason,
            "workers": self.workers,
            "queued_jobs": self.queued_jobs,
            "active_jobs": self.active_jobs,
        }


class NativeRuntimeFacade:
    """Thread-safe facade over the native companion (single persistent process)."""

    def __init__(
        self,
        *,
        executable: Path | None = None,
        mode: str = "auto",
        settings_getter: Callable[[], dict[str, Any]] | None = None,
        repo: Path | None = None,
    ) -> None:
        self._repo = repo or repo_root()
        self._explicit_exe = executable
        self._settings_getter = settings_getter
        self._force_mode = mode
        self._transport = RpcTransport()
        self._supervisor = NativeSupervisor(
            transport=self._transport,
            executable_resolver=self.executable_path,
            repo=self._repo,
        )
        self.process = NativeProcessClient(self)
        self.services = NativeServiceClient(self)
        self.fs = NativeFilesystemClient(self)
        self.metrics = NativeMetricsClient(self)
        # Track job_id per in-flight process.run for timeout→cancel
        self._job_by_request: dict[str, str] = {}
        self._job_lock = threading.Lock()

    # --- compatibility aliases used across the codebase ---
    @property
    def _last_error(self) -> str | None:
        return self._supervisor.last_error

    @_last_error.setter
    def _last_error(self, value: str | None) -> None:
        # tests may assign; store via supervisor state
        self._supervisor._state.last_error = value  # noqa: SLF001 — compat

    def resolve_mode(self) -> str:
        if self._settings_getter:
            try:
                values = self._settings_getter() or {}
                mode = str(values.get("native_runtime_mode") or self._force_mode or "auto").lower()
                if mode in {"auto", "enabled", "disabled"}:
                    return mode
            except Exception:
                pass
        mode = (self._force_mode or "auto").lower()
        return mode if mode in {"auto", "enabled", "disabled"} else "auto"

    def executable_path(self) -> Path | None:
        return self._explicit_exe or locate_native_executable(self._repo)

    def status(self) -> NativeStatus:
        mode = self.resolve_mode()
        exe = self.executable_path()
        available = exe is not None
        connected = self._supervisor.is_running() and bool(self._supervisor.hello)
        hello = self._supervisor.hello
        diag = self._supervisor.diagnostics()
        fallback = mode == "disabled" or not connected
        if mode == "enabled" and not connected:
            fallback = True
        caps = list(hello.get("capabilities") or [])
        return NativeStatus(
            mode=mode,
            available=available,
            connected=connected,
            version=hello.get("version"),
            protocol_version=hello.get("protocol_version") or (PROTOCOL_VERSION if connected else None),
            compiler=hello.get("compiler"),
            uptime_ms=diag.get("uptime_ms"),
            capabilities=caps,
            fallback_active=fallback,
            executable=str(exe) if exe else None,
            last_error=diag.get("last_error") or self._supervisor.last_error,
            process_count=hello.get("process_count"),
            service_count=hello.get("service_count"),
            generation=diag.get("generation"),
            restart_count=diag.get("restart_count"),
            crash_count=diag.get("crash_count"),
            last_crash_reason=diag.get("last_crash_reason"),
        )

    def ensure_started(self) -> bool:
        mode = self.resolve_mode()
        if mode == "disabled":
            return False
        started = self._supervisor.ensure_started()
        if not started and mode == "enabled":
            raise NativeRuntimeError("EXECUTABLE_NOT_FOUND", self._supervisor.last_error or "Native runtime unavailable.")
        return started

    def attach_external_process(self, proc: subprocess.Popen[str]) -> None:
        """Test/support hook: attach an already-started protocol process.

        Production code should use ensure_started()/start() only.
        """
        self._supervisor.attach_external_process(proc)

    def _handshake(self) -> dict[str, Any]:
        """Compatibility helper used by unit tests."""
        result = self._transport.call("runtime.hello", {}, timeout_s=10)
        if int(result.get("protocol_version") or 0) != PROTOCOL_VERSION:
            raise NativeRuntimeError(
                "UNSUPPORTED_PROTOCOL",
                f"Protocol mismatch: peer={result.get('protocol_version')} expected={PROTOCOL_VERSION}",
            )
        return result

    def start(self) -> NativeStatus:
        mode = self.resolve_mode()
        if mode == "disabled":
            self.shutdown()
            return self.status()
        started = self.ensure_started()
        if not started and mode == "enabled":
            raise NativeRuntimeError("EXECUTABLE_NOT_FOUND", self._supervisor.last_error or "Native runtime unavailable.")
        return self.status()

    def restart(self) -> NativeStatus:
        mode = self.resolve_mode()
        if mode == "disabled":
            self.shutdown()
            return self.status()
        from .observability import get_native_observability

        get_native_observability().record_restart()
        ok = self._supervisor.restart()
        if not ok and mode == "enabled":
            raise NativeRuntimeError("EXECUTABLE_NOT_FOUND", self._supervisor.last_error or "Native runtime unavailable.")
        return self.status()

    def shutdown(self) -> None:
        self._supervisor.shutdown()

    def call(self, method: str, params: dict[str, Any] | None = None, *, timeout_s: float | None = None) -> dict[str, Any]:
        if not self.ensure_started():
            raise NativeRuntimeError("NATIVE_UNAVAILABLE", "Native runtime is not active; use Python fallback.")
        from .observability import get_native_observability

        obs = get_native_observability()
        try:
            result = self._raw_call(method, params or {}, timeout_s=timeout_s)
            obs.record_rpc(ok=True)
            return result
        except NativeRuntimeError as exc:
            if exc.code == "TIMEOUT":
                obs.record_timeout()
                obs.record_cancel()
            else:
                obs.record_rpc(ok=False)
            raise

    def _raw_call(self, method: str, params: dict[str, Any], *, timeout_s: float | None = None) -> dict[str, Any]:
        job_id = None
        if method == "process.run":
            job_id = str(params.get("job_id") or f"py-{uuid.uuid4()}")
            params = {**params, "job_id": job_id}

        def on_timeout(_request_id: str, timed_method: str) -> None:
            # Critical: do not leave C++ work orphaned when Python waiter times out.
            if timed_method == "process.run" and job_id:
                try:
                    self._transport.call("process.cancel", {"job_id": job_id}, timeout_s=5.0)
                except Exception as exc:
                    logger.debug("timeout cancel failed for %s: %s", job_id, exc)

        return self._transport.call(method, params, timeout_s=timeout_s, on_timeout=on_timeout)

    # Convenience methods matching historical NativeRuntimeClient API
    def process_run(self, **kwargs: Any) -> dict[str, Any]:
        return self.process.run(**kwargs)

    def process_cancel(self, job_id: str) -> dict[str, Any]:
        return self.process.cancel(job_id)

    def service_start(self, **params: Any) -> dict[str, Any]:
        return self.services.start(**params)

    def service_status(self, service_id: str) -> dict[str, Any]:
        return self.services.status(service_id)

    def service_stop(self, service_id: str) -> dict[str, Any]:
        return self.services.stop(service_id)

    def service_logs(self, service_id: str, *, max_bytes: int = 100_000) -> dict[str, Any]:
        return self.services.logs(service_id, max_bytes=max_bytes)

    def service_probe(self, service_id: str, creation_time: float | None = None) -> dict[str, Any]:
        return self.services.probe(service_id, creation_time)

    def fs_scan(self, path: str, *, max_entries: int = 10_000) -> dict[str, Any]:
        return self.fs.scan(path, max_entries=max_entries)

    def fs_hash(self, path: str) -> dict[str, Any]:
        return self.fs.hash(path)

    def fs_hash_many(self, paths: list[str], *, max_files: int = 1000) -> dict[str, Any]:
        return self.fs.hash_many(paths, max_files=max_files)

    def fs_snapshot(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.fs.snapshot(path, **kwargs)

    def repo_search(self, path: str, query: str, **kwargs: Any) -> dict[str, Any]:
        return self.fs.repo_search(path, query, **kwargs)

    def system_metrics(self) -> dict[str, Any]:
        return self.metrics.system_metrics()

    def health(self) -> dict[str, Any]:
        return self.metrics.health()

    def capabilities(self) -> dict[str, Any]:
        return self.metrics.capabilities()

    def reconcile_services_after_restart(self) -> dict[str, Any]:
        """After native crash/restart, services owned by the old generation are gone.

        Returns guidance for PluginManager — we never pretend services survived.
        """
        diag = self._supervisor.diagnostics()
        return {
            "generation": diag.get("generation"),
            "requires_reconciliation": True,
            "message": "Native runtime generation changed; re-start services explicitly. Do not reattach stale PIDs.",
            "crash_count": diag.get("crash_count"),
            "last_crash_reason": diag.get("last_crash_reason"),
        }

    def benchmark(self) -> dict[str, Any]:
        started = time.perf_counter()
        python_echo = None
        native_echo = None
        try:
            t0 = time.perf_counter()
            subprocess.run(
                [os.environ.get("COMSPEC") or ("cmd.exe" if os.name == "nt" else "/bin/echo"), "hades"]
                if os.name == "nt"
                else ["/bin/echo", "hades"],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
            python_echo = int((time.perf_counter() - t0) * 1000)
        except Exception as exc:
            python_echo = None
            logger.debug("python echo benchmark failed: %s", exc)
        try:
            t0 = time.perf_counter()
            if os.name == "nt":
                self.process_run(executable=os.environ.get("COMSPEC", "cmd.exe"), argv=["/c", "echo", "hades"], timeout_ms=10_000)
            else:
                self.process_run(executable="/bin/echo", argv=["hades"], timeout_ms=10_000)
            native_echo = int((time.perf_counter() - t0) * 1000)
        except Exception as exc:
            native_echo = None
            logger.debug("native echo benchmark failed: %s", exc)
        metrics = None
        try:
            metrics = self.system_metrics()
        except Exception:
            metrics = None
        return {
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "python_process_echo_ms": python_echo,
            "native_process_echo_ms": native_echo,
            "system_metrics": metrics,
            "note": "Micro-benchmark of process launch only; does not measure LM Studio token generation.",
        }


# Historical name
NativeRuntimeClient = NativeRuntimeFacade

_native_client: NativeRuntimeFacade | None = None
_native_lock = threading.Lock()


def get_native_client() -> NativeRuntimeFacade:
    global _native_client
    with _native_lock:
        if _native_client is None:
            _native_client = NativeRuntimeFacade()
        return _native_client


def set_native_client(client: NativeRuntimeFacade | None) -> None:
    global _native_client
    with _native_lock:
        _native_client = client


def configure_native_client(
    *, settings_getter: Callable[[], dict[str, Any]] | None = None, repo: Path | None = None
) -> NativeRuntimeFacade:
    client = NativeRuntimeFacade(settings_getter=settings_getter, repo=repo)
    set_native_client(client)
    return client
