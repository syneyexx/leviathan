"""Generic long-running PROCESS_SERVICE adapter with health probes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ...types import ModuleHealth, ModuleResult, ModuleStatus
from ..install import InstallationService, InstallError
from ..process import OwnedProcess, wait_for_probe
from ..types import ExternalFailureCode, ExternalRuntimeState, RuntimeMode, normalize_capability_parts
from .base import AdapterContext, CancelCheck, ProgressCb
from .cli import CliAdapter


class ProcessServiceAdapter:
    def __init__(self, ctx: AdapterContext) -> None:
        self.ctx = ctx
        self.config = ctx.config
        self._state = ExternalRuntimeState.STOPPED
        self._install_root: str | None = ctx.install_root
        self._owned: OwnedProcess | None = None
        # Optional CLI invoke path for one-shot ops against the service.
        self._cli = CliAdapter(ctx)
        self._last_used_at: datetime | None = None

    def runtime_state(self) -> ExternalRuntimeState:
        if self._owned and self._owned.is_alive():
            return ExternalRuntimeState.RUNNING if self._state != ExternalRuntimeState.DEGRADED else self._state
        if self._state == ExternalRuntimeState.RUNNING:
            # Reconcile stale RUNNING.
            self._state = ExternalRuntimeState.STOPPED
        return self._state

    def ensure_installed(self, *, progress: ProgressCb | None = None, cancel_check: CancelCheck | None = None) -> dict[str, Any]:
        result = self._cli.ensure_installed(progress=progress, cancel_check=cancel_check)
        self._install_root = result.get("install_root") or self._install_root
        return result

    def _resolve_install_root(self) -> str | None:
        """Prefer in-memory root; else CONTROL active version (restart-safe)."""
        if self._install_root and Path(self._install_root).exists():
            return self._install_root
        if self.ctx.store is not None:
            version = self.ctx.store.get_active_version(self.ctx.module_id)
            if version and version.get("install_root") and Path(str(version["install_root"])).exists():
                self._install_root = str(version["install_root"])
                return self._install_root
        if self.ctx.install_root and Path(self.ctx.install_root).exists():
            self._install_root = self.ctx.install_root
            return self._install_root
        return self._install_root

    def start(self) -> dict[str, Any]:
        self._reconcile_persisted()
        if self._owned and self._owned.is_alive():
            self._state = ExternalRuntimeState.RUNNING
            return {"status": "RUNNING", "pid": self._owned.pid}
        if not self.config.runtime.command:
            raise InstallError(ExternalFailureCode.START_FAILED, "process service requires runtime.command")
        self._state = ExternalRuntimeState.STARTING
        root = self._resolve_install_root()
        cwd = (self.config.runtime.cwd or root or "").replace("$INSTALL_ROOT", root or "") or None
        if cwd in {"", "$INSTALL_ROOT"}:
            cwd = root
        command = [c.replace("$INSTALL_ROOT", root or "") for c in self.config.runtime.command]
        if command:
            from .cli import _resolve_python_alias

            exe = command[0]
            if root:
                import os as _os
                from pathlib import Path as _Path

                venv_bin = (
                    _Path(root)
                    / ".venv"
                    / ("Scripts" if _os.name == "nt" else "bin")
                    / exe
                )
                if venv_bin.exists():
                    exe = str(venv_bin)
                else:
                    exe = _resolve_python_alias(exe)
            else:
                exe = _resolve_python_alias(exe)
            command[0] = exe
        env = {k: v.replace("$INSTALL_ROOT", root or "") for k, v in self.config.runtime.env.items()}
        # Prefer install-root venv on PATH for module-local binaries (uvicorn, etc.).
        if root:
            import os as _os
            from pathlib import Path as _Path

            venv_path = _Path(root) / ".venv" / ("Scripts" if _os.name == "nt" else "bin")
            if venv_path.is_dir():
                env = {**_os.environ, **env, "PATH": f"{venv_path}{_os.pathsep}{_os.environ.get('PATH', '')}"}
        if (self.config.runtime.cwd or "").find("$INSTALL_ROOT") >= 0 and not root:
            raise InstallError(
                ExternalFailureCode.START_FAILED,
                "process service $INSTALL_ROOT unresolved; install/activate a version before start",
            )
        self._owned = OwnedProcess(
            module_id=self.ctx.module_id,
            command=command,
            cwd=cwd,
            env=env,
            restart_count=(self._owned.restart_count + 1) if self._owned else 0,
        )
        try:
            pid = self._owned.start()
        except Exception as exc:  # noqa: BLE001
            self._state = ExternalRuntimeState.FAILED
            raise InstallError(ExternalFailureCode.START_FAILED, str(exc)) from exc

        ok, detail = wait_for_probe(
            self.config.runtime.ready_probe,
            timeout_seconds=self.config.runtime.startup_timeout_seconds,
            is_alive=self._owned.is_alive,
        )
        if not ok:
            self._owned.stop()
            self._state = ExternalRuntimeState.FAILED
            raise InstallError(ExternalFailureCode.START_FAILED, f"ready probe failed: {detail}")

        self._state = ExternalRuntimeState.RUNNING
        self._touch()
        if self.ctx.store is not None:
            self.ctx.store.upsert_process(
                module_id=self.ctx.module_id,
                pid=pid,
                fingerprint=self._owned.fingerprint,
                command=command,
                cwd=cwd,
                started_at=self._owned.started_at,
                restart_count=self._owned.restart_count,
                health="OK",
            )
            self.ctx.store.set_runtime_state(
                self.ctx.module_id,
                ExternalRuntimeState.RUNNING.value,
                desired_state="RUNNING",
            )
        return {"status": "RUNNING", "pid": pid, "ready": detail}

    def stop(self) -> dict[str, Any]:
        self._state = ExternalRuntimeState.STOPPING
        code = None
        if self._owned:
            code = self._owned.stop()
        elif self.ctx.store is not None:
            # Reconcile persisted PID — only kill if fingerprint matches.
            from ..process import OwnedProcess as OP

            rec = self.ctx.store.get_process(self.ctx.module_id)
            if rec and rec.get("pid"):
                orphan = OP(
                    module_id=self.ctx.module_id,
                    command=list(rec.get("command") or []),
                    cwd=rec.get("cwd"),
                    env={},
                    pid=int(rec["pid"]),
                    fingerprint=rec.get("fingerprint"),
                    started_at=rec.get("started_at"),
                    restart_count=int(rec.get("restart_count") or 0),
                )
                code = orphan.stop()
        self._state = ExternalRuntimeState.STOPPED
        if self.ctx.store is not None:
            self.ctx.store.upsert_process(
                module_id=self.ctx.module_id,
                pid=None,
                fingerprint=None,
                command=self._owned.command if self._owned else [],
                cwd=self._owned.cwd if self._owned else None,
                exit_code=code,
                restart_count=self._owned.restart_count if self._owned else 0,
                health="STOPPED",
            )
            self.ctx.store.set_runtime_state(
                self.ctx.module_id,
                ExternalRuntimeState.STOPPED.value,
                desired_state="STOPPED",
            )
        self._owned = None
        return {"status": "STOPPED", "exit_code": code}

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    def ensure_ready(self) -> dict[str, Any]:
        self._reconcile_persisted()
        # Do not idle-stop here — ensure_ready means the caller needs the process.
        if self.runtime_state() == ExternalRuntimeState.RUNNING:
            ok, detail = wait_for_probe(
                self.config.runtime.health_probe or self.config.runtime.ready_probe,
                timeout_seconds=min(5.0, self.config.runtime.startup_timeout_seconds),
                is_alive=lambda: bool(self._owned and self._owned.is_alive()),
            )
            if ok:
                self._touch()
                return {"ready": True, "status": "RUNNING", "detail": detail}
            self._state = ExternalRuntimeState.DEGRADED
            return {"ready": False, "code": ExternalFailureCode.HEALTH_FAILED.value, "detail": detail}
        # Lazy start.
        started = self.start()
        return {"ready": True, **started}

    def health(self) -> ModuleHealth:
        self.maybe_idle_shutdown()
        state = self.runtime_state()
        detail = state.value
        status = ModuleStatus.READY if state in {ExternalRuntimeState.RUNNING, ExternalRuntimeState.READY} else ModuleStatus.ERROR
        if state == ExternalRuntimeState.STOPPED:
            status = ModuleStatus.SHUTDOWN
        return ModuleHealth(
            module_id=self.ctx.module_id,
            status=status,
            detail=detail,
            telemetry={
                "runtime_state": state.value,
                "adapter": "PROCESS_SERVICE",
                "process": self._owned.public_dict() if self._owned else None,
                "idle_timeout_seconds": self.config.runtime.idle_timeout_seconds,
                "last_used_at": self._last_used_at.isoformat() if self._last_used_at else None,
            },
        )

    def maybe_idle_shutdown(self) -> dict[str, Any] | None:
        """Stop when idle_timeout elapsed, mode is LAZY/RESIDENT, and process is alive.

        Never terminates while the adapter believes work is in flight via recent touch.
        ModuleManager.sweep_idle_modules also skips modules with active_jobs.
        """
        timeout = self.config.runtime.idle_timeout_seconds
        if timeout is None or timeout <= 0:
            return None
        if self.config.runtime.mode not in {RuntimeMode.LAZY, RuntimeMode.RESIDENT}:
            return None
        if self.runtime_state() != ExternalRuntimeState.RUNNING:
            return None
        # Desired RUNNING without idle intent — operator wants it resident forever.
        if self.ctx.store is not None:
            rec = self.ctx.store.get_module(self.ctx.module_id)
            # If desired_state is RUNNING and idle_timeout is set, idle still applies for LAZY.
            if rec and rec.get("desired_state") == "RUNNING" and self.config.runtime.mode == RuntimeMode.RESIDENT:
                # RESIDENT + explicit desired RUNNING: still honor idle_timeout when configured.
                pass
        last = self._last_used_at
        if last is None and self.ctx.store is not None:
            mod = self.ctx.store.get_module(self.ctx.module_id)
            raw = (mod or {}).get("last_used_at")
            if raw:
                try:
                    last = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                except ValueError:
                    last = None
        if last is None:
            # No use recorded yet — use process start time.
            if self._owned and self._owned.started_at:
                try:
                    last = datetime.fromisoformat(str(self._owned.started_at).replace("Z", "+00:00"))
                except ValueError:
                    last = None
        if last is None:
            return None
        now = datetime.now(timezone.utc)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        idle_for = (now - last).total_seconds()
        if idle_for < float(timeout):
            return None
        stopped = self.stop()
        return {"stopped": True, "idle_for_seconds": idle_for, "timeout_seconds": timeout, **stopped}

    def _touch(self) -> None:
        self._last_used_at = datetime.now(timezone.utc)
        if self.ctx.store is not None:
            try:
                self.ctx.store.touch_used(self.ctx.module_id)
            except Exception:  # noqa: BLE001
                pass

    def logs(self, *, limit: int = 200) -> list[str]:
        if self._owned:
            return self._owned.stdout_buf.snapshot(limit // 2) + self._owned.stderr_buf.snapshot(limit // 2)
        if self.ctx.store is not None:
            return self.ctx.store.get_logs(self.ctx.module_id, limit=limit)
        return []

    def invoke(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        progress: ProgressCb | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ModuleResult:
        # Lifecycle ops
        if operation in {"start", "stop", "restart", "health", "status"}:
            if operation == "start":
                out = self.start()
            elif operation == "stop":
                out = self.stop()
            elif operation == "restart":
                out = self.restart()
            else:
                out = self.health().public_dict()
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="COMPLETED",
                output=normalize_capability_parts(summary=operation, structured_data=out, module_status=out),
            )
        ready = self.ensure_ready()
        if not ready.get("ready"):
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="FAILED",
                error=ExternalFailureCode.START_FAILED.value,
                output={"error": {"code": ExternalFailureCode.START_FAILED.value, "detail": ready}},
            )
        self._touch()
        # Prefer HTTP operations when configured; else CLI against install root.
        if self.config.runtime.base_url or any(op.get("method") for op in self.config.runtime.operations):
            from .http_openapi import HttpOpenApiAdapter

            http = HttpOpenApiAdapter(self.ctx)
            http._base_url = self.config.runtime.base_url  # type: ignore[attr-defined]
            return http.invoke(operation, arguments, progress=progress, cancel_check=cancel_check)
        return self._cli.invoke(operation, arguments, progress=progress, cancel_check=cancel_check)

    def _reconcile_persisted(self) -> None:
        """On LEVIATHAN restart: do not trust persisted RUNNING."""
        if self._owned is not None:
            return
        if self.ctx.store is None:
            return
        rec = self.ctx.store.get_process(self.ctx.module_id)
        if not rec or not rec.get("pid"):
            self._state = ExternalRuntimeState.STOPPED
            return
        from ..process import pid_matches_fingerprint

        alive = pid_matches_fingerprint(
            int(rec["pid"]),
            rec.get("fingerprint"),
            list(rec.get("command") or []),
            rec.get("cwd"),
        )
        if alive:
            self._owned = OwnedProcess(
                module_id=self.ctx.module_id,
                command=list(rec.get("command") or []),
                cwd=rec.get("cwd"),
                env={},
                pid=int(rec["pid"]),
                fingerprint=rec.get("fingerprint"),
                started_at=rec.get("started_at"),
                restart_count=int(rec.get("restart_count") or 0),
            )
            self._state = ExternalRuntimeState.RUNNING
        else:
            self._state = ExternalRuntimeState.STOPPED
            self.ctx.store.set_runtime_state(self.ctx.module_id, ExternalRuntimeState.STOPPED.value)
            self.ctx.store.upsert_process(
                module_id=self.ctx.module_id,
                pid=None,
                fingerprint=None,
                command=list(rec.get("command") or []),
                cwd=rec.get("cwd"),
                health="RECONCILED_DEAD",
                restart_count=int(rec.get("restart_count") or 0),
            )
