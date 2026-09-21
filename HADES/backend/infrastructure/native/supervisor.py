"""Native companion process supervision: start/stop/restart, crash detection, backoff."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .errors import NativeRuntimeError
from .transport import RpcTransport

logger = logging.getLogger("hades.native.supervisor")


@dataclass
class SupervisorState:
    generation: int = 0
    restart_count: int = 0
    crash_count: int = 0
    last_crash_at: float | None = None
    last_crash_reason: str | None = None
    last_error: str | None = None
    started_at: float = 0.0
    consecutive_failures: int = 0


class NativeSupervisor:
    """Owns the single persistent hades_native_runtime process."""

    def __init__(
        self,
        *,
        transport: RpcTransport,
        executable_resolver: Callable[[], Path | None],
        repo: Path,
        max_restarts: int = 5,
        backoff_base_s: float = 0.5,
        backoff_max_s: float = 30.0,
    ) -> None:
        self._transport = transport
        self._resolve_exe = executable_resolver
        self._repo = repo
        self._max_restarts = max_restarts
        self._backoff_base_s = backoff_base_s
        self._backoff_max_s = backoff_max_s
        self._lock = threading.RLock()
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._state = SupervisorState()
        self._hello: dict[str, Any] = {}
        self._stderr_tail: list[str] = []
        self._stopping = False

    @property
    def state(self) -> SupervisorState:
        with self._lock:
            return SupervisorState(**self._state.__dict__)

    @property
    def hello(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._hello)

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._state.last_error

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def attach_external_process(self, proc: subprocess.Popen[str]) -> None:
        """Attach a pre-launched process (unit tests / advanced recovery only)."""
        with self._lock:
            self._proc = proc
            self._state.generation += 1
            self._state.started_at = time.monotonic()
            self._hello = {}
            generation = self._state.generation

            def write_fn(line: str) -> None:
                if proc.stdin is None:
                    raise NativeRuntimeError("NATIVE_UNAVAILABLE", "stdin closed")
                proc.stdin.write(line)
                proc.stdin.flush()

            self._transport.attach(write_fn, generation=generation)
            self._reader = threading.Thread(
                target=self._read_loop, args=(proc, generation), name="hades-native-stdout", daemon=True
            )
            self._reader.start()
            threading.Thread(target=self._stderr_loop, args=(proc,), name="hades-native-stderr", daemon=True).start()

    def ensure_started(self) -> bool:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None and self._hello:
                return True
        exe = self._resolve_exe()
        if exe is None:
            with self._lock:
                self._state.last_error = "Native runtime executable not found under runtime/native/."
            return False
        with self._lock:
            if self._proc is not None and self._proc.poll() is None and self._hello:
                return True
            already_running = self._proc is not None and self._proc.poll() is None
            if not already_running:
                if not self._launch(exe):
                    return False
        with self._lock:
            if self._hello and self._proc is not None and self._proc.poll() is None:
                return True
        try:
            hello = self._transport.call("runtime.hello", {}, timeout_s=10)
            if int(hello.get("protocol_version") or 0) != 1:
                raise NativeRuntimeError(
                    "UNSUPPORTED_PROTOCOL",
                    f"Protocol mismatch: peer={hello.get('protocol_version')} expected=1",
                )
            try:
                caps_raw = self._transport.call("runtime.capabilities", {}, timeout_s=5)
                if isinstance(caps_raw, dict):
                    hello["capabilities"] = [key for key, value in caps_raw.items() if value]
                    hello["capability_map"] = caps_raw
            except Exception:
                hello.setdefault("capabilities", [])
            with self._lock:
                self._hello = hello
                self._state.last_error = None
                self._state.consecutive_failures = 0
            return True
        except Exception as exc:
            with self._lock:
                self._state.last_error = str(exc)
            logger.warning("native handshake failed: %s", exc)
            self._teardown_process()
            return False

    def restart(self) -> bool:
        self.shutdown()
        with self._lock:
            self._state.restart_count += 1
            failures = self._state.consecutive_failures
        if failures > 0:
            delay = min(self._backoff_max_s, self._backoff_base_s * (2 ** min(failures, 6)))
            time.sleep(delay)
        return self.ensure_started()

    def note_crash(self, reason: str, *, generation: int | None = None) -> bool:
        """Record a crash for the current process generation only.

        Returns False when ``generation`` is stale so an old reader cannot
        mutate hello/backoff state after a newer companion has attached.
        """
        with self._lock:
            if generation is not None and int(generation) != self._state.generation:
                return False
            self._state.crash_count += 1
            self._state.last_crash_at = time.time()
            self._state.last_crash_reason = reason
            self._state.consecutive_failures += 1
            self._state.last_error = reason
            self._hello = {}
            return True

    def can_auto_restart(self) -> bool:
        with self._lock:
            return (not self._stopping) and self._state.consecutive_failures < self._max_restarts

    def shutdown(self) -> None:
        with self._lock:
            self._stopping = True
            proc = self._proc
            generation = self._state.generation
            self._proc = None
            self._hello = {}
            # Detach under the same lock so a concurrent attach cannot be
            # cleared by this teardown after it has already published a new write path.
            self._transport.detach(
                reason="Native runtime shutting down.",
                shutting_down=True,
                generation=generation,
            )
        if proc is None:
            with self._lock:
                self._stopping = False
            return
        try:
            if proc.poll() is None and proc.stdin:
                try:
                    import json
                    import uuid

                    req = json.dumps(
                        {"version": 1, "id": str(uuid.uuid4()), "method": "runtime.shutdown", "params": {}},
                        ensure_ascii=False,
                    )
                    proc.stdin.write(req + "\n")
                    proc.stdin.flush()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
        except Exception as exc:
            logger.debug("native shutdown: %s", exc)
        finally:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
        with self._lock:
            self._stopping = False

    def _launch(self, exe: Path) -> bool:
        """Start companion. Caller must hold _lock for process field updates after return path."""
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                [str(exe)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(self._repo),
                shell=False,
                creationflags=creationflags,
            )
        except OSError as exc:
            self._state.last_error = f"Failed to launch native runtime: {exc}"
            self._state.consecutive_failures += 1
            self._proc = None
            return False
        self._proc = proc
        self._state.generation += 1
        self._state.started_at = time.monotonic()
        self._hello = {}
        generation = self._state.generation

        def write_fn(line: str) -> None:
            if proc.stdin is None:
                raise NativeRuntimeError("NATIVE_UNAVAILABLE", "stdin closed")
            proc.stdin.write(line)
            proc.stdin.flush()

        self._transport.attach(write_fn, generation=generation)
        self._reader = threading.Thread(target=self._read_loop, args=(proc, generation), name="hades-native-stdout", daemon=True)
        self._reader.start()
        threading.Thread(target=self._stderr_loop, args=(proc,), name="hades-native-stderr", daemon=True).start()
        return True

    def _teardown_process(self) -> None:
        with self._lock:
            proc = self._proc
            generation = self._state.generation
            self._proc = None
            self._hello = {}
            self._transport.detach(generation=generation)
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass

    def _read_loop(self, proc: subprocess.Popen[str], generation: int) -> None:
        import json

        if proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("native stdout non-JSON: %s", line[:200])
                    continue
                self._transport.deliver(message, reader_generation=generation)
        except Exception as exc:
            logger.debug("native stdout reader ended: %s", exc)
        finally:
            reason = "Native runtime connection closed."
            exited = proc.poll() is not None
            if exited:
                reason = f"Native runtime exited with code {proc.returncode}."
            with self._lock:
                is_current = self._proc is proc and self._state.generation == generation
                shutting_down = self._stopping
                if is_current and exited:
                    # Mutate crash/hello state only while still owning the live generation.
                    self._state.crash_count += 1
                    self._state.last_crash_at = time.time()
                    self._state.last_crash_reason = reason
                    self._state.consecutive_failures += 1
                    self._state.last_error = reason
                    self._hello = {}
                elif is_current:
                    self._hello = {}
                if is_current:
                    self._proc = None
            # Always fail waiters that registered under this reader generation.
            self._transport.fail_pending_for_generation(
                generation,
                NativeRuntimeError("INTERNAL_ERROR", reason),
                shutting_down=shutting_down,
            )
            # Bounded auto-restart is opt-in via ensure_started by callers; do not tight-loop here.

    def _stderr_loop(self, proc: subprocess.Popen[str]) -> None:
        if proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                text = line.rstrip()
                if not text:
                    continue
                with self._lock:
                    self._stderr_tail.append(text)
                    if len(self._stderr_tail) > 200:
                        self._stderr_tail = self._stderr_tail[-100:]
                logger.debug("native stderr: %s", text)
        except Exception:
            pass

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "generation": self._state.generation,
                "restart_count": self._state.restart_count,
                "crash_count": self._state.crash_count,
                "last_crash_at": self._state.last_crash_at,
                "last_crash_reason": self._state.last_crash_reason,
                "last_error": self._state.last_error,
                "consecutive_failures": self._state.consecutive_failures,
                "uptime_ms": int((time.monotonic() - self._state.started_at) * 1000)
                if self.is_running() and self._state.started_at
                else None,
                "pending_rpcs": self._transport.pending_count(),
            }
