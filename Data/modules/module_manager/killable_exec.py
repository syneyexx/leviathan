"""Killable process-boundary execution for ModuleManager containment.

ThreadPoolExecutor().future.result(timeout=...) is NOT safe containment: the
worker thread keeps running after the caller reports timeout. This module runs
untrusted / mutating / timed work in an owned child process with:

- hard timeout
- process-tree termination
- stdout/stderr drain (no pipe deadlock)
- cooperative cancellation
- lease fencing (generation token; post-timeout results discarded)
- accurate timeout reporting without waiting for timed-out work via a contextmanager
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from Data.modules.common.process_control import (
    kill_process_tree,
    owned_child_popen_kwargs,
    scrub_child_environment,
    terminate_owned_process,
)


@dataclass
class KillableExecResult:
    status: str  # COMPLETED | FAILED | TIMEOUT | CANCELLED | REJECTED
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    process_killed: bool = False
    lease_token: str = ""
    fenced: bool = False
    truth: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        out = dict(self.payload) if self.payload else {}
        out.setdefault("status", self.status)
        if self.error and "error" not in out:
            out["error"] = self.error
        out["truth"] = {
            **dict(self.truth),
            "killable_process_boundary": True,
            "thread_pool_timeout_is_not_containment": True,
            "lease_fenced": self.fenced,
        }
        return out


class KillableModuleExecutor:
    """Execute a module operation in a killable owned subprocess."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = max(0.1, float(timeout_seconds))

    def execute(
        self,
        *,
        entrypoint: str,
        operation: str,
        arguments: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        lease_token: str | None = None,
        cwd: str | Path | None = None,
    ) -> KillableExecResult:
        token = (lease_token or "").strip() or uuid.uuid4().hex
        script = _worker_script()
        payload = {
            "entrypoint": entrypoint,
            "operation": operation,
            "arguments": dict(arguments),
            "context": dict(context or {}),
            "lease_token": token,
        }
        workdir = Path(cwd) if cwd is not None else Path(__file__).resolve().parents[3]
        env = scrub_child_environment(
            extras={"PYTHONPATH": str(workdir)},
            permit_secret_extras=False,
        )
        # Ensure repo root is importable for Data.* modules.
        existing = env.get("PYTHONPATH", "")
        root = str(workdir)
        if root not in existing.split(os.pathsep):
            env["PYTHONPATH"] = root + (os.pathsep + existing if existing else "")

        started = time.monotonic()
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        killed = False
        fenced = False
        status = "FAILED"
        error: str | None = None
        parsed: dict[str, Any] = {}

        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(workdir),
                env=env,
                **owned_child_popen_kwargs(),
            )
        except OSError as exc:
            return KillableExecResult(
                status="FAILED",
                error=f"spawn_failed: {exc}",
                duration_seconds=time.monotonic() - started,
                lease_token=token,
                truth={"subprocess_isolation": True},
            )

        assert proc.stdin is not None
        drain_done = threading.Event()

        def _drain(stream: Any, sink: list[bytes]) -> None:
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    sink.append(chunk)
                    # Bound capture (~2 MiB).
                    if sum(len(c) for c in sink) > 2_000_000:
                        break
            except Exception:  # noqa: BLE001
                return
            finally:
                drain_done.set()

        threads = [
            threading.Thread(target=_drain, args=(proc.stdout, stdout_chunks), daemon=True),
            threading.Thread(target=_drain, args=(proc.stderr, stderr_chunks), daemon=True),
        ]
        for t in threads:
            t.start()

        try:
            proc.stdin.write(json.dumps(payload).encode("utf-8"))
            proc.stdin.close()
        except OSError as exc:
            killed = True
            terminate_owned_process(proc, graceful_timeout_seconds=0.5, force_timeout_seconds=1.0)
            kill_process_tree(proc, grace_seconds=0.05)
            return KillableExecResult(
                status="FAILED",
                error=f"stdin_write_failed: {exc}",
                duration_seconds=time.monotonic() - started,
                process_killed=True,
                lease_token=token,
                truth={"subprocess_isolation": True},
            )

        deadline = started + self.timeout_seconds
        exit_code: int | None = None
        try:
            while True:
                if callable(cancel_check) and cancel_check():
                    killed = True
                    fenced = True
                    terminate_owned_process(proc, graceful_timeout_seconds=1.0, force_timeout_seconds=2.0)
                    if proc.poll() is None:
                        kill_process_tree(proc, grace_seconds=0.05)
                    status = "CANCELLED"
                    error = "cancelled"
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    killed = True
                    fenced = True
                    terminate_owned_process(proc, graceful_timeout_seconds=1.0, force_timeout_seconds=2.0)
                    if proc.poll() is None:
                        kill_process_tree(proc, grace_seconds=0.05)
                    status = "TIMEOUT"
                    error = f"execute timeout after {self.timeout_seconds}s"
                    break
                code = proc.poll()
                if code is not None:
                    exit_code = int(code)
                    break
                time.sleep(min(0.05, max(0.01, remaining)))
        finally:
            # Never block the caller waiting for timed-out work beyond a short drain.
            if proc.poll() is None:
                killed = True
                fenced = True
                kill_process_tree(proc, grace_seconds=0.05)
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
            for t in threads:
                t.join(timeout=0.5)
            # Close pipes to avoid ResourceWarning on owned children.
            for stream in (proc.stdout, proc.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:  # noqa: BLE001
                    pass
            try:
                if proc.stdin is not None and not proc.stdin.closed:
                    proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass

        duration = time.monotonic() - started
        stdout_b = b"".join(stdout_chunks)
        stderr_b = b"".join(stderr_chunks)
        stdout_t = stdout_b.decode("utf-8", errors="replace")
        stderr_t = stderr_b.decode("utf-8", errors="replace")

        if status == "TIMEOUT":
            return KillableExecResult(
                status="TIMEOUT",
                error=error,
                stdout=stdout_t[-8000:],
                stderr=stderr_t[-8000:],
                duration_seconds=duration,
                process_killed=killed,
                lease_token=token,
                fenced=True,
                truth={
                    "subprocess_isolation": True,
                    "timeout_seconds": self.timeout_seconds,
                    "no_continued_side_effects_after_timeout": True,
                },
            )
        if status == "CANCELLED":
            return KillableExecResult(
                status="CANCELLED",
                error=error,
                stdout=stdout_t[-8000:],
                stderr=stderr_t[-8000:],
                duration_seconds=duration,
                process_killed=killed,
                lease_token=token,
                fenced=True,
                truth={"subprocess_isolation": True},
            )

        if exit_code is None:
            exit_code = int(proc.returncode) if proc.returncode is not None else -1

        if exit_code != 0:
            return KillableExecResult(
                status="FAILED",
                error=(stderr_t or stdout_t or f"subprocess exit {exit_code}").strip()[:2000],
                stdout=stdout_t[-8000:],
                stderr=stderr_t[-8000:],
                duration_seconds=duration,
                process_killed=killed,
                lease_token=token,
                fenced=fenced,
                truth={"subprocess_isolation": True, "exit_code": exit_code},
            )

        try:
            line = stdout_t.strip().splitlines()[-1] if stdout_t.strip() else ""
            parsed = json.loads(line)
        except (json.JSONDecodeError, IndexError) as exc:
            return KillableExecResult(
                status="FAILED",
                error=f"Invalid subprocess JSON: {exc}; raw={stdout_t[:500]!r}",
                stdout=stdout_t[-8000:],
                stderr=stderr_t[-8000:],
                duration_seconds=duration,
                lease_token=token,
                truth={"subprocess_isolation": True},
            )

        # Lease fence: discard results that do not echo the caller's token
        # (stale/post-timeout workers must not resurrect side-effect claims).
        echoed = str(parsed.get("lease_token") or "")
        if echoed and echoed != token:
            return KillableExecResult(
                status="REJECTED",
                error="lease_fence: stale worker result discarded",
                payload={},
                duration_seconds=duration,
                lease_token=token,
                fenced=True,
                truth={"subprocess_isolation": True, "lease_fence": True},
            )

        result_status = str(parsed.get("status") or "FAILED")
        return KillableExecResult(
            status=result_status,
            payload=parsed if isinstance(parsed, dict) else {},
            error=str(parsed.get("error")) if parsed.get("error") else None,
            stdout=stdout_t[-8000:],
            stderr=stderr_t[-8000:],
            duration_seconds=duration,
            process_killed=killed,
            lease_token=token,
            fenced=False,
            truth={"subprocess_isolation": True},
        )


def _worker_script() -> str:
    return """
import json, importlib, sys, traceback
payload = json.loads(sys.stdin.read())
lease = payload.get("lease_token") or ""
try:
    module_name, _, attr = payload["entrypoint"].partition(":")
    mod = importlib.import_module(module_name)
    factory = getattr(mod, attr)
    instance = factory()
    from Data.modules.module_manager.types import ModuleContext
    ctx_data = payload.get("context") or {}
    instance.initialize(ModuleContext(
        database_path=ctx_data.get("database_path"),
        data_root=ctx_data.get("data_root"),
        feature_flags=ctx_data.get("feature_flags") or {},
        metadata=ctx_data.get("metadata") or {},
    ))
    result = instance.execute(payload["operation"], payload.get("arguments") or {})
    out = result.public_dict() if hasattr(result, "public_dict") else dict(result)
    out["lease_token"] = lease
    print(json.dumps(out))
    try:
        instance.shutdown()
    except Exception:
        pass
except Exception as exc:
    print(json.dumps({
        "status": "FAILED",
        "error": f"{exc}\\n{traceback.format_exc(limit=3)}",
        "lease_token": lease,
        "truth": {"subprocess_isolation": True},
    }))
    sys.exit(1)
"""
