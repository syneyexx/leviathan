from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, TextIO

MAX_CAPTURE_CHARS = 1_000_000
MAX_LOG_BYTES = 2 * 1024 * 1024

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|auth[_-]?token|credential|password|secret|token|_authtoken|npm_config_authtoken)\b(\s*[:=]\s*)([^\s\"']+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_BASIC_AUTH_HEADER = re.compile(r"(?i)\bAuthorization:\s*Basic\s+[A-Za-z0-9+/=]+")
_AUTHORIZATION_EQUALS = re.compile(r"(?i)\bAuthorization\s*=\s*[^\s\"']+")
_URL_USERINFO = re.compile(r"(?i)\b(https?://)([^/\s:@]+):([^/\s@]+)@")
_NPM_AUTH_TOKEN = re.compile(r"(?i)(//[^\s]+/:_authToken=)([^\s]+)")

# Dependency installers execute third-party package/build code. Keep ordinary
# runtime environment for compatibility, but never hand them unrelated HADES
# or provider credentials merely because the parent process owns those values.
_AMBIENT_SECRET_ENV_EXACT = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "COMPOSIO_API_KEY",
        "FINCEPT_API_KEY",
        "FINCEPT_SESSION_TOKEN",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "HADES_LM_STUDIO_API_KEY",
        "OPENAI_API_KEY",
        "SSH_AGENT_PID",
        "SSH_AUTH_SOCK",
    }
)
_AMBIENT_SECRET_ENV_SUFFIXES = (
    "_API_KEY",
    "_ACCESS_TOKEN",
    "_AUTH_TOKEN",
    "_BEARER_TOKEN",
    "_CLIENT_SECRET",
    "_PRIVATE_KEY",
    "_PASSWORD",
    "_SECRET",
    "_TOKEN",
)

# Package-manager configuration is runtime-scoped. Some of these values may
# intentionally contain private-registry credentials (for example
# PIP_INDEX_URL or NPM_TOKEN). Preserve them only for the matching dependency
# runtime; strip cross-runtime package-manager configuration entirely.
_PACKAGE_MANAGER_ENV_PREFIXES: dict[str, tuple[str, ...]] = {
    "python": ("PIP_", "UV_", "POETRY_", "PDM_"),
    "node": ("NPM_", "NPM_CONFIG_", "PNPM_", "YARN_", "NODE_AUTH_"),
    "rust": ("CARGO_",),
    "java": ("MAVEN_", "GRADLE_", "ORG_GRADLE_PROJECT_"),
    "dotnet": ("NUGET_",),
    "go": ("GOPRIVATE", "GONOPROXY", "GONOSUMDB", "GOPROXY"),
}
_ALL_PACKAGE_MANAGER_PREFIXES = tuple(
    sorted({prefix for prefixes in _PACKAGE_MANAGER_ENV_PREFIXES.values() for prefix in prefixes})
)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def redact_dependency_output(value: str) -> str:
    """Redact common credentials before logs or DB traces persist them."""
    # Header-shaped secrets first so generic assignment matching does not
    # strip `Basic`/`Bearer` while leaving the credential token behind.
    value = _BASIC_AUTH_HEADER.sub("Authorization: Basic [REDACTED]", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    value = _AUTHORIZATION_EQUALS.sub("Authorization=[REDACTED]", value)
    value = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)
    value = _URL_USERINFO.sub(r"\1[REDACTED]:[REDACTED]@", value)
    value = _NPM_AUTH_TOKEN.sub(r"\1[REDACTED]", value)
    return value


def is_sensitive_dependency_env_key(key: str) -> bool:
    """Return whether an ambient environment key is credential-shaped."""
    upper = str(key or "").strip().upper()
    return bool(
        upper
        and (
            upper in _AMBIENT_SECRET_ENV_EXACT
            or any(upper.endswith(suffix) for suffix in _AMBIENT_SECRET_ENV_SUFFIXES)
        )
    )


def build_dependency_environment(runtime: str, env: dict[str, str] | None = None) -> dict[str, str]:
    """Build a dependency child environment without unrelated ambient secrets.

    Normal runtime variables (PATH, TEMP, locale, proxy settings, etc.) remain
    available. Package-manager-specific configuration is only passed to its own
    runtime so private registry configuration keeps working without leaking, for
    example, NPM_TOKEN into pip or PIP_INDEX_URL into npm lifecycle scripts.
    Other credential-shaped ambient values are removed fail-closed.
    """
    source = dict(os.environ if env is None else env)
    runtime_key = str(runtime or "").strip().lower()
    allowed_prefixes = _PACKAGE_MANAGER_ENV_PREFIXES.get(runtime_key, ())
    child: dict[str, str] = {}
    for raw_key, raw_value in source.items():
        key = str(raw_key)
        upper = key.upper()
        package_scoped = any(upper.startswith(prefix) for prefix in _ALL_PACKAGE_MANAGER_PREFIXES)
        if package_scoped:
            if any(upper.startswith(prefix) for prefix in allowed_prefixes):
                child[key] = str(raw_value)
            continue
        if is_sensitive_dependency_env_key(key):
            continue
        child[key] = str(raw_value)
    return child


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def write_dependency_status(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, {**payload, "updated_at": utc_now_iso()})


def _tail_bytes(path: Path, limit: int) -> tuple[str, int]:
    if not path.exists():
        return "", 0
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > limit:
            handle.seek(max(0, size - limit))
        data = handle.read()
    return data.decode("utf-8", errors="replace"), size


def read_dependency_snapshot(log_path: Path, status_path: Path, *, tail_bytes: int = 100_000) -> dict[str, Any]:
    limit = max(1_000, min(int(tail_bytes), 500_000))
    log, size = _tail_bytes(log_path, limit)
    state: dict[str, Any] = {"phase": "idle"}
    if status_path.exists():
        try:
            loaded = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
        except (OSError, json.JSONDecodeError):
            state = {"phase": "unknown", "reason": "Dependency-statusbestand kon niet worden gelezen."}
    return {"state": state, "log": log, "log_bytes": size}


class DependencyCommandRunner:
    """Run one dependency command with live, bounded logging and process-tree cancellation."""

    def __init__(
        self,
        *,
        log_path: Path,
        status_path: Path,
        runtime: str,
        command_index: int,
        total_commands: int,
        timeout_seconds: int,
        stall_timeout_seconds: int,
        phase: str = "installing",
        on_output: Callable[[str, str], None] | None = None,
    ) -> None:
        self.log_path = log_path
        self.status_path = status_path
        self.runtime = runtime
        self.command_index = command_index
        self.total_commands = total_commands
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.stall_timeout_seconds = max(0, int(stall_timeout_seconds))
        self.phase = phase
        self.on_output = on_output
        self._io_lock = threading.RLock()
        self._last_output_monotonic = time.monotonic()
        self._last_output_at = utc_now_iso()

    def _append_log(self, label: str, text: str) -> str:
        safe = redact_dependency_output(text.rstrip("\r\n"))
        if not safe:
            return ""
        line = f"[{utc_now_iso()}] [{label}] {safe}\n"
        encoded = line.encode("utf-8", errors="replace")
        with self._io_lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_path.exists() and self.log_path.stat().st_size > MAX_LOG_BYTES * 2:
                existing, _ = _tail_bytes(self.log_path, MAX_LOG_BYTES)
                self.log_path.write_text(existing, encoding="utf-8")
            with self.log_path.open("ab") as handle:
                handle.write(encoded)
            self._last_output_monotonic = time.monotonic()
            self._last_output_at = utc_now_iso()
        if self.on_output is not None:
            try:
                self.on_output(label, safe)
            except Exception:
                pass
        return safe

    @staticmethod
    def _capture_append(parts: list[str], value: str) -> None:
        if not value:
            return
        parts.append(value)
        total = sum(len(item) for item in parts)
        if total > MAX_CAPTURE_CHARS * 2:
            joined = "\n".join(parts)
            parts[:] = [joined[-MAX_CAPTURE_CHARS:]]

    def _pump(self, stream: TextIO, label: str, sink: list[str]) -> None:
        try:
            for raw in iter(stream.readline, ""):
                safe = self._append_log(label, raw)
                if safe:
                    with self._io_lock:
                        self._capture_append(sink, safe)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    shell=False,
                )
            except Exception:
                try:
                    process.terminate()
                except OSError:
                    pass
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (AttributeError, OSError):
                try:
                    process.terminate()
                except OSError:
                    pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (AttributeError, OSError):
                    try:
                        process.kill()
                    except OSError:
                        pass
            else:
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

    def _status(
        self,
        *,
        command: list[str],
        pid: int | None,
        started_at: str,
        elapsed: float,
        silence: float,
        reason: str = "",
    ) -> None:
        write_dependency_status(
            self.status_path,
            {
                "phase": self.phase,
                "runtime": self.runtime,
                "command_index": self.command_index,
                "total_commands": self.total_commands,
                "command": command,
                "pid": pid,
                "started_at": started_at,
                "elapsed_seconds": round(max(0.0, elapsed), 1),
                "silence_seconds": round(max(0.0, silence), 1),
                "timeout_seconds": self.timeout_seconds,
                "stall_timeout_seconds": self.stall_timeout_seconds,
                "last_output_at": self._last_output_at,
                "reason": reason,
            },
        )

    def run(self, command: list[str], *, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
        if not command or not all(isinstance(item, str) and item for item in command):
            raise ValueError("Dependency-commando moet een niet-lege argv-lijst zijn.")

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        started = time.monotonic()
        started_at = utc_now_iso()
        self._last_output_monotonic = started
        self._last_output_at = started_at
        self._append_log("hades", "START " + " ".join(command))

        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        child_env = build_dependency_environment(self.runtime, env)
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_thread = threading.Thread(target=self._pump, args=(process.stdout, "stdout", stdout_parts), daemon=True)
        stderr_thread = threading.Thread(target=self._pump, args=(process.stderr, "stderr", stderr_parts), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        failure_reason = ""
        timed_out = False
        stalled = False
        last_status_write = 0.0
        while process.poll() is None:
            now = time.monotonic()
            elapsed = now - started
            silence = now - self._last_output_monotonic
            if elapsed >= self.timeout_seconds:
                timed_out = True
                failure_reason = f"Dependency-commando overschreed de totale timeout van {self.timeout_seconds} seconden."
                self._append_log("hades", failure_reason)
                self._terminate_process_tree(process)
                break
            if self.stall_timeout_seconds and silence >= self.stall_timeout_seconds:
                stalled = True
                failure_reason = (
                    f"Geen dependency-output ontvangen gedurende {self.stall_timeout_seconds} seconden; "
                    "het installatieproces lijkt vastgelopen."
                )
                self._append_log("hades", failure_reason)
                self._terminate_process_tree(process)
                break
            if now - last_status_write >= 0.5:
                self._status(
                    command=command,
                    pid=process.pid,
                    started_at=started_at,
                    elapsed=elapsed,
                    silence=silence,
                )
                last_status_write = now
            time.sleep(0.1)

        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._terminate_process_tree(process)
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

        elapsed = time.monotonic() - started
        exit_code = process.returncode
        if not failure_reason and exit_code not in {0, None}:
            failure_reason = f"Dependency-commando eindigde met exitcode {exit_code}."
        self.phase = "failed" if failure_reason else "command_completed"
        self._status(
            command=command,
            pid=process.pid,
            started_at=started_at,
            elapsed=elapsed,
            silence=time.monotonic() - self._last_output_monotonic,
            reason=failure_reason,
        )
        self._append_log("hades", "DONE" if not failure_reason else f"FAILED: {failure_reason}")
        return {
            "command": command,
            "stdout": "\n".join(stdout_parts)[-MAX_CAPTURE_CHARS:],
            "stderr": "\n".join(stderr_parts)[-MAX_CAPTURE_CHARS:],
            "exit_code": exit_code,
            "error": failure_reason or None,
            "timed_out": timed_out,
            "stalled": stalled,
            "duration_ms": round(elapsed * 1000),
        }
