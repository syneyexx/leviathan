"""Generic CLI adapter — argv arrays, cwd, timeout, cancel, structured parse."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Mapping

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_EXACT_PLACEHOLDER_RE = re.compile(r"^\??\{([A-Za-z_][A-Za-z0-9_]*)\}$")

from ...types import ModuleHealth, ModuleResult, ModuleStatus
from ..install import InstallationService, InstallError
from ..process import BoundedLogBuffer
from ..results import parse_cli_result
from ..types import ExternalConfig, ExternalFailureCode, ExternalRuntimeState
from .base import AdapterContext, CancelCheck, ProgressCb


class CliAdapter:
    def __init__(self, ctx: AdapterContext) -> None:
        self.ctx = ctx
        self.config: ExternalConfig = ctx.config
        self._state = ExternalRuntimeState.DISCOVERED
        self._install_root: str | None = ctx.install_root
        self._active_proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()
        self._log = BoundedLogBuffer()

    def runtime_state(self) -> ExternalRuntimeState:
        return self._state

    def ensure_installed(self, *, progress: ProgressCb | None = None, cancel_check: CancelCheck | None = None) -> dict[str, Any]:
        if not self.ctx.data_root:
            raise InstallError(ExternalFailureCode.INSTALL_FAILED, "data_root required for install")
        service = InstallationService(Path(self.ctx.data_root))
        result = service.ensure_installed(
            module_id=self.ctx.module_id,
            config=self.config,
            progress=progress,
            cancel_check=cancel_check,
        )
        self._install_root = result.install_root
        self._state = ExternalRuntimeState.INSTALLED
        if self.ctx.store is not None:
            self.ctx.store.add_version(
                version_id=result.version_id,
                module_id=self.ctx.module_id,
                install_root=result.install_root,
                source_ref=result.source_ref,
                resolved_commit=result.resolved_commit,
                content_hash=result.content_hash,
                install_strategies=result.strategies,
                dependency_versions=result.dependency_versions,
                activate=True,
                adapter="CLI",
                name=self.ctx.module_id,
            )
            self.ctx.store.set_runtime_state(self.ctx.module_id, ExternalRuntimeState.INSTALLED.value)
        return result.public_dict()

    def start(self) -> dict[str, Any]:
        ready = self.ensure_ready()
        self._state = ExternalRuntimeState.READY
        return {"status": "READY", "detail": "cli_ephemeral", **ready}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._active_proc and self._active_proc.poll() is None:
                try:
                    self._active_proc.send_signal(signal.SIGTERM)
                    self._active_proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    try:
                        self._active_proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
            self._active_proc = None
        self._state = ExternalRuntimeState.READY
        return {"status": "READY", "detail": "cli_idle"}

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    def ensure_ready(self) -> dict[str, Any]:
        root = self._resolve_root()
        if root is None or not Path(root).exists():
            if self.ctx.store is not None:
                version = self.ctx.store.get_active_version(self.ctx.module_id)
                if version:
                    self._install_root = version["install_root"]
                    root = self._install_root
        if root is None or not Path(root).exists():
            # Path-less CLI (system binary) with no install root is still ready if command exists.
            if self.config.source.source_type in {"none", "binary"} and self.config.runtime.command:
                self._state = ExternalRuntimeState.READY
                return {"ready": True, "install_root": None}
            self._state = ExternalRuntimeState.NOT_INSTALLED
            return {"ready": False, "code": ExternalFailureCode.NOT_INSTALLED.value}
        self._state = ExternalRuntimeState.READY
        return {"ready": True, "install_root": root}

    def health(self) -> ModuleHealth:
        ready = self.ensure_ready()
        status = ModuleStatus.READY if ready.get("ready") else ModuleStatus.ERROR
        return ModuleHealth(
            module_id=self.ctx.module_id,
            status=status,
            detail="cli_ready" if ready.get("ready") else str(ready.get("code") or "not_ready"),
            telemetry={"runtime_state": self._state.value, "adapter": "CLI"},
        )

    def logs(self, *, limit: int = 200) -> list[str]:
        lines = self._log.snapshot(limit)
        if self.ctx.store is not None:
            stored = self.ctx.store.get_logs(self.ctx.module_id, limit=limit)
            if stored:
                return stored
        return lines

    def invoke(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        *,
        progress: ProgressCb | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ModuleResult:
        ready = self.ensure_ready()
        if not ready.get("ready"):
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="FAILED",
                error=ExternalFailureCode.NOT_INSTALLED.value,
                output={"error": {"code": ExternalFailureCode.NOT_INSTALLED.value}},
            )

        try:
            argv = self._build_argv(operation, arguments)
        except FileNotFoundError as exc:
            code = str(exc)
            if ExternalFailureCode.CAPABILITY_NOT_FOUND.value in code:
                failure = ExternalFailureCode.CAPABILITY_NOT_FOUND
            elif ExternalFailureCode.DEPENDENCY_MISSING.value in code:
                failure = ExternalFailureCode.DEPENDENCY_MISSING
            else:
                failure = ExternalFailureCode.CAPABILITY_NOT_FOUND
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="FAILED",
                error=failure.value,
                output={"error": {"code": failure.value, "detail": code}},
            )

        cwd = self._resolve_cwd()
        env = os.environ.copy()
        env.update(self.config.runtime.env)
        install_root = self._install_root or ""
        env = {k: v.replace("$INSTALL_ROOT", install_root) for k, v in env.items()}

        stdin_data: bytes | None = None
        if self.config.runtime.stdin_format == "json":
            import json

            stdin_data = json.dumps(dict(arguments), default=str).encode("utf-8")
        elif self.config.runtime.stdin_format == "text":
            stdin_data = str(arguments.get("stdin") or arguments.get("input") or "").encode("utf-8")

        op_cfg = self._operation_config(operation)
        timeout = float(
            arguments.get("timeout_seconds")
            or (op_cfg or {}).get("timeout_seconds")
            or self.config.runtime.timeout_seconds
        )
        if progress:
            progress(0.05, "starting", " ".join(argv[:6]))
        self._state = ExternalRuntimeState.BUSY
        started = time.perf_counter()
        last_progress_at = started
        try:
            with self._lock:
                self._active_proc = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                )
                proc = self._active_proc

            deadline = time.monotonic() + timeout
            stdout_b = b""
            stderr_b = b""
            while True:
                if cancel_check and cancel_check():
                    try:
                        proc.send_signal(signal.SIGTERM)
                        proc.wait(timeout=3)
                    except Exception:  # noqa: BLE001
                        try:
                            proc.kill()
                        except Exception:  # noqa: BLE001
                            pass
                    self._state = ExternalRuntimeState.READY
                    if progress:
                        progress(1.0, "cancelled", ExternalFailureCode.CANCELLED.value)
                    return ModuleResult(
                        module_id=self.ctx.module_id,
                        operation=operation,
                        status="CANCELLED",
                        error=ExternalFailureCode.CANCELLED.value,
                        output={"error": {"code": ExternalFailureCode.CANCELLED.value}},
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
                    self._state = ExternalRuntimeState.READY
                    return ModuleResult(
                        module_id=self.ctx.module_id,
                        operation=operation,
                        status="TIMEOUT",
                        error=ExternalFailureCode.TIMEOUT.value,
                        output={"error": {"code": ExternalFailureCode.TIMEOUT.value}},
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                # Honest mid-run heartbeat — elapsed fraction of timeout, not invented work %.
                now = time.perf_counter()
                if progress and (now - last_progress_at) >= 0.4:
                    elapsed = now - started
                    frac = min(0.9, max(0.05, elapsed / max(timeout, 0.001)))
                    progress(frac, "running", f"pid={proc.pid} elapsed={elapsed:.1f}s")
                    last_progress_at = now
                try:
                    stdout_b, stderr_b = proc.communicate(input=stdin_data, timeout=min(0.5, remaining))
                    stdin_data = None
                    break
                except subprocess.TimeoutExpired:
                    stdin_data = None
                    continue

            exit_code = int(proc.returncode or 0)
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
            for line in (stdout + "\n" + stderr).splitlines():
                if line.strip():
                    self._log.append(line)
            if self.ctx.store is not None:
                self.ctx.store.append_logs(
                    self.ctx.module_id,
                    [ln for ln in (stdout + "\n" + stderr).splitlines() if ln.strip()][-100:],
                )

            if progress:
                progress(0.9, "parsing", f"exit={exit_code}")
            # Per-op accept_exit_codes: some CLIs use nonzero to mean "not configured"
            # while still returning useful stdout (e.g. alphaXiv not logged in).
            op_spec = next(
                (
                    o
                    for o in (self.config.runtime.operations or ())
                    if isinstance(o, dict) and str(o.get("name") or o.get("operation") or "") == operation
                ),
                None,
            )
            accept_exit = {0}
            if isinstance(op_spec, dict) and op_spec.get("accept_exit_codes") is not None:
                try:
                    accept_exit = {int(x) for x in op_spec.get("accept_exit_codes") or [0]}
                except (TypeError, ValueError):
                    accept_exit = {0}
            effective_exit = 0 if exit_code in accept_exit else exit_code
            status, output, failure = parse_cli_result(
                stdout=stdout,
                stderr=stderr,
                exit_code=effective_exit,
                spec=self.config.result,
                cwd=Path(cwd) if cwd else None,
            )
            if isinstance(output, dict):
                meta = dict(output.get("metadata") or {})
                meta["exit_code"] = exit_code
                if effective_exit != exit_code:
                    meta["accepted_nonzero_exit"] = True
                output = {**output, "metadata": meta}
                # Prefer ArtifactStore ids over raw paths / giant stdout in Chat.
                try:
                    from ..artifacts_materialize import (
                        materialize_external_files,
                        materialize_large_stdout,
                    )

                    output = materialize_external_files(
                        output,
                        artifact_store=self.ctx.artifact_store,
                        module_id=self.ctx.module_id,
                        operation=operation,
                    )
                    output = materialize_large_stdout(
                        output,
                        stdout=stdout,
                        artifact_store=self.ctx.artifact_store,
                        module_id=self.ctx.module_id,
                        operation=operation,
                        max_inline_bytes=int(self.config.result.max_inline_bytes or 64_000),
                    )
                except Exception:  # noqa: BLE001 — materialization must not fail the tool
                    pass
            self._state = ExternalRuntimeState.READY
            if self.ctx.store is not None:
                self.ctx.store.touch_used(self.ctx.module_id)
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status=status,
                output=output,
                error=failure.value if failure else None,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except FileNotFoundError as exc:
            self._state = ExternalRuntimeState.FAILED
            return ModuleResult(
                module_id=self.ctx.module_id,
                operation=operation,
                status="FAILED",
                error=ExternalFailureCode.DEPENDENCY_MISSING.value,
                output={"error": {"code": ExternalFailureCode.DEPENDENCY_MISSING.value, "detail": str(exc)}},
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        finally:
            with self._lock:
                self._active_proc = None
            if self._state == ExternalRuntimeState.BUSY:
                self._state = ExternalRuntimeState.READY

    def _resolve_root(self) -> str | None:
        if self._install_root:
            return self._install_root
        if self.config.source.path:
            return str(Path(self.config.source.path).expanduser())
        return None

    def _resolve_cwd(self) -> str | None:
        if self.config.runtime.cwd:
            return self.config.runtime.cwd.replace("$INSTALL_ROOT", self._install_root or "")
        return self._install_root

    def _operation_config(self, operation: str) -> dict[str, Any] | None:
        for op in self.config.runtime.operations:
            if str(op.get("name") or op.get("operation") or "") == operation:
                return dict(op)
        return None

    def _build_argv(self, operation: str, arguments: Mapping[str, Any]) -> list[str]:
        if isinstance(arguments.get("argv"), (list, tuple)) and arguments["argv"]:
            return [str(x).replace("$INSTALL_ROOT", self._install_root or "") for x in arguments["argv"]]

        op = self._operation_config(operation)
        if op is not None:
            cmd = op.get("command") or op.get("argv")
            if isinstance(cmd, (list, tuple)) and cmd:
                merged = dict(op.get("defaults") or {})
                merged.update({k: v for k, v in arguments.items() if v is not None})
                return self._render_argv([str(x) for x in cmd], merged)

        declared_ops = list(self.config.runtime.operations or [])
        if declared_ops:
            # Named operations exist — unknown names must not silently run runtime.command
            # (interactive TUIs hang forever / EOFError on that path).
            raise FileNotFoundError(
                f"{ExternalFailureCode.CAPABILITY_NOT_FOUND.value}: unknown CLI operation {operation!r}"
            )
        if self.config.runtime.command:
            # Legacy single-command modules with no operations table: run default argv.
            return self._render_argv(
                [str(x) for x in self.config.runtime.command],
                {**dict(arguments), "operation": operation},
            )
        raise FileNotFoundError(
            f"{ExternalFailureCode.CAPABILITY_NOT_FOUND.value}: no CLI command/operation configured "
            f"for {operation!r}"
        )

    def _render_argv(self, template: list[str], arguments: Mapping[str, Any]) -> list[str]:
        """Render argv templates.

        Exact segments like ``{payload}`` / ``?{payload}`` accept arbitrary values
        (including JSON with braces). Mixed segments only replace known ``{key}``
        placeholders and fail if any remain unsubstituted.
        """
        install_root = self._install_root or ""
        rendered: list[str] = []
        for part in template:
            text = part.replace("$INSTALL_ROOT", install_root)
            exact = _EXACT_PLACEHOLDER_RE.fullmatch(text)
            if exact is not None:
                key = exact.group(1)
                optional = text.startswith("?")
                if key not in arguments or arguments.get(key) is None:
                    if optional:
                        continue
                    raise FileNotFoundError(f"Missing argv substitution for operation template segment: {text}")
                value = arguments.get(key)
                if optional and value == "":
                    continue
                rendered.append(str(value).replace("$INSTALL_ROOT", install_root))
                continue

            # Mixed template: substitute known keys, then require no leftover {name}.
            for key, value in arguments.items():
                if isinstance(value, (str, int, float)):
                    text = text.replace("{" + str(key) + "}", str(value))
            if text.startswith("?") and _PLACEHOLDER_RE.search(text):
                continue
            if text.startswith("?"):
                text = text[1:]
                if text == "":
                    continue
            leftover = _PLACEHOLDER_RE.findall(text)
            if leftover:
                raise FileNotFoundError(
                    f"Missing argv substitution for operation template segment: {text}"
                )
            rendered.append(text)
        if rendered and self._install_root:
            bin_candidate = Path(self._install_root) / rendered[0]
            venv_bin = Path(self._install_root) / ".venv" / ("Scripts" if os.name == "nt" else "bin") / rendered[0]
            if venv_bin.exists():
                rendered[0] = str(venv_bin)
            elif bin_candidate.exists():
                rendered[0] = str(bin_candidate)
            else:
                # Alias bare python → python3 when only python3 is on PATH.
                rendered[0] = _resolve_python_alias(rendered[0])
        elif rendered:
            rendered[0] = _resolve_python_alias(rendered[0])
        return rendered


def _resolve_python_alias(executable: str) -> str:
    if executable not in {"python", "python.exe"}:
        return executable
    import shutil

    return shutil.which("python3") or shutil.which("python") or executable
