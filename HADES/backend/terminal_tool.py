"""Policy terminal tool: allowlisted commands, cwd jail, optional secured isolation."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from artifacts import ArtifactService
from platform_db import utc_now

try:
    from gen2.sandbox import path_is_within
except Exception:  # pragma: no cover - gen2 optional during early boot
    path_is_within = None  # type: ignore[assignment]

from execution_isolation import (
    SECURED_MODE,
    TRUSTED_MODE,
    IsolationPolicy,
    IsolationUnavailable,
    default_policy_for_data_root,
    detect_isolation_capabilities,
    run_isolated,
)

DEFAULT_ALLOWLIST = (
    "python",
    "python3",
    "py",
    "pip",
    "pip3",
    "node",
    "npm",
    "npx",
    "git",
    "dir",
    "ls",
    "type",
    "cat",
    "echo",
    "where",
    "which",
    "pytest",
    "unittest",
)

# Interpreters that can construct absolute paths in-process and bypass argv path checks.
_INTERPRETER_BINARIES = frozenset({"python", "python3", "py", "node", "nodejs"})


class TerminalPolicyError(PermissionError):
    pass


class PolicyTerminalService:
    def __init__(self, artifact_service: ArtifactService, data_root: Path) -> None:
        self.artifacts = artifact_service
        self.data_root = Path(data_root).resolve()
        self.default_cwd = self.data_root / "terminal_cwd"
        self.default_cwd.mkdir(parents=True, exist_ok=True)

    def resolve_allowlist(self, settings: dict[str, Any] | None = None) -> list[str]:
        raw = (settings or {}).get("terminal_allowlist")
        if isinstance(raw, list) and raw:
            return [str(item).strip().lower() for item in raw if str(item).strip()]
        if isinstance(raw, str) and raw.strip():
            return [part.strip().lower() for part in raw.replace(";", ",").split(",") if part.strip()]
        return list(DEFAULT_ALLOWLIST)

    def resolve_execution_mode(self, settings: dict[str, Any] | None = None) -> str:
        """Return trusted|secured. Autonomous/default secured; explicit trusted opt-in."""
        cfg = settings or {}
        raw = str(cfg.get("terminal_execution_mode") or cfg.get("execution_mode") or "").strip().lower()
        if raw in {TRUSTED_MODE, SECURED_MODE}:
            return raw
        # Autonomous tool use defaults to secured isolation.
        if bool(cfg.get("terminal_autonomous") or cfg.get("autonomous") or cfg.get("require_isolation")):
            return SECURED_MODE
        # Backward compatible default for manual allowlisted runs: secured when available,
        # else trusted with explicit labeling (never silent secured claim).
        caps = detect_isolation_capabilities()
        if caps.get("secured_fs_isolation_available"):
            return SECURED_MODE
        return TRUSTED_MODE

    def _validate_argv(self, argv: list[str], allowlist: list[str]) -> None:
        if not argv:
            raise TerminalPolicyError("Lege commandoregel.")
        if any("|" in part or "&" in part or ";" in part or "`" in part for part in argv):
            raise TerminalPolicyError("Shell-metacharacters zijn geblokkeerd; geef argv-array zonder shell.")
        binary = Path(argv[0]).name.lower()
        if binary.endswith(".exe"):
            binary = binary[:-4]
        if binary not in allowlist:
            raise TerminalPolicyError(f"Commando '{binary}' staat niet op de terminal-allowlist.")

    def _binary_name(self, argv0: str) -> str:
        binary = Path(argv0).name.lower()
        if binary.endswith(".exe"):
            binary = binary[:-4]
        return binary

    def _path_allowed(self, candidate: Path, *, root: Path | None = None) -> bool:
        base = (root or self.data_root).expanduser().resolve(strict=False)
        if path_is_within is not None:
            return bool(path_is_within(candidate, base))
        try:
            candidate.expanduser().resolve(strict=False).relative_to(base)
            return True
        except (ValueError, OSError):
            return False

    def _resolve_cwd(self, cwd: str | None) -> Path:
        root = self.default_cwd
        if not cwd:
            return root
        candidate = Path(cwd).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve(strict=False)
        else:
            candidate = candidate.resolve(strict=False)
        if not self._path_allowed(candidate, root=self.data_root):
            raise TerminalPolicyError("CWD moet binnen de HADES data-root blijven.")
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
        if not candidate.is_dir():
            raise TerminalPolicyError("CWD is geen map.")
        if not self._path_allowed(candidate, root=self.data_root):
            raise TerminalPolicyError("CWD moet binnen de HADES data-root blijven.")
        return candidate

    def assert_path_inside_cwd_jail(self, path: str | Path, *, cwd: Path | None = None) -> Path:
        """Deny paths that resolve outside the active cwd jail (G10)."""
        work = (cwd or self.default_cwd).expanduser().resolve(strict=False)
        if not self._path_allowed(work, root=self.data_root):
            raise TerminalPolicyError("CWD moet binnen de HADES data-root blijven.")
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (work / candidate).resolve(strict=False)
        else:
            candidate = candidate.resolve(strict=False)
        if not self._path_allowed(candidate, root=work):
            raise TerminalPolicyError("Pad buiten terminal jail (cwd allowlist).")
        return candidate

    def _validate_argv_paths(self, argv: list[str], workdir: Path) -> None:
        """Reject path-like argv entries that escape the cwd jail."""
        for part in argv[1:]:
            text = str(part)
            looks_path = (
                "/" in text
                or "\\" in text
                or text.startswith("~")
                or text in {".", ".."}
                or text.startswith("./")
                or text.startswith(".\\")
            )
            if not looks_path or text.startswith("-") or "://" in text:
                continue
            self.assert_path_inside_cwd_jail(text, cwd=workdir)

    def _coding_workspace_roots(self, settings: dict[str, Any] | None) -> tuple[list[Path], list[Path]]:
        cfg = settings or {}
        extra_read: list[Path] = []
        extra_write: list[Path] = []
        for key in ("coding_workspace", "workspace_root", "approved_workspace"):
            raw = cfg.get(key)
            if raw:
                extra_write.append(Path(str(raw)))
                extra_read.append(Path(str(raw)))
        for key in ("terminal_extra_read_roots", "extra_read_roots"):
            raw = cfg.get(key)
            if isinstance(raw, list):
                extra_read.extend(Path(str(x)) for x in raw)
        for key in ("terminal_extra_write_roots", "extra_write_roots"):
            raw = cfg.get(key)
            if isinstance(raw, list):
                extra_write.extend(Path(str(x)) for x in raw)
        return extra_read, extra_write

    def run(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        timeout_seconds: int | None = None,
        settings: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        cfg = settings or {}
        if str(cfg.get("subprocess_policy") or "ask").strip().lower() == "block":
            raise TerminalPolicyError("subprocess_policy=block blokkeert terminal-uitvoering.")
        allowlist = self.resolve_allowlist(cfg)
        cleaned = [str(part) for part in argv if str(part).strip() != ""]
        self._validate_argv(cleaned, allowlist)
        workdir = self._resolve_cwd(cwd)
        self._validate_argv_paths(cleaned, workdir)
        configured_default = cfg["terminal_timeout_seconds"] if "terminal_timeout_seconds" in cfg else 30
        max_timeout = cfg["terminal_max_timeout_seconds"] if "terminal_max_timeout_seconds" in cfg else 120

        if timeout_seconds is None:
            requested: int | None
            if configured_default is None or isinstance(configured_default, int):
                requested = configured_default
            else:
                requested = int(configured_default)
        else:
            requested = int(timeout_seconds)

        if requested is not None:
            requested = max(1, int(requested))
            if max_timeout is not None:
                requested = min(int(max_timeout), requested)

        effective_timeout = requested
        mode = self.resolve_execution_mode(cfg)
        extra_read, extra_write = self._coding_workspace_roots(cfg)
        policy = default_policy_for_data_root(
            self.data_root,
            extra_read=extra_read,
            extra_write=extra_write,
            allow_network=bool(cfg.get("terminal_allow_network") or False),
            mode=mode,
        )
        # Interpreters in secured mode must go through FS isolation — argv path checks are insufficient.
        binary = self._binary_name(cleaned[0])
        if mode == SECURED_MODE and binary in _INTERPRETER_BINARIES:
            policy.mode = SECURED_MODE

        started = time.perf_counter()
        isolation_meta: dict[str, Any] = {
            "execution_mode": mode,
            "isolation_enforced": False,
            "fs_isolation": False,
            "network_isolation": False,
            "adapter": None,
        }
        try:
            isolated = run_isolated(
                cleaned,
                cwd=workdir,
                policy=policy,
                timeout_seconds=float(effective_timeout) if effective_timeout is not None else None,
                env=os.environ,
            )
            stdout = isolated.stdout or ""
            stderr = isolated.stderr or ""
            exit_code = int(isolated.exit_code if isolated.exit_code is not None else 1)
            if isolated.reason == "timeout" or exit_code == 124:
                status = "timeout"
            else:
                status = "completed" if exit_code == 0 else "failed"
            isolation_meta.update(
                {
                    "execution_mode": isolated.mode,
                    "isolation_enforced": isolated.isolation_enforced,
                    "fs_isolation": isolated.fs_isolation,
                    "network_isolation": isolated.network_isolation,
                    "adapter": isolated.adapter,
                    "env_filtered": isolated.env_filtered,
                    "isolation_reason": isolated.reason,
                    "isolation_evidence": isolated.evidence,
                }
            )
        except IsolationUnavailable as exc:
            # Fail closed for secured mode — do not silently run unbounded.
            duration_ms = int((time.perf_counter() - started) * 1000)
            raise TerminalPolicyError(
                "Secured terminal isolation is unavailable; refusing unbounded execution. "
                f"Detail: {exc}. Set terminal_execution_mode=trusted only for explicitly trusted runs."
            ) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        out_limit = cfg.get("terminal_output_max_chars", 20_000)
        transcript = (
            f"$ {' '.join(cleaned)}\n"
            f"cwd={workdir}\n"
            f"exit={exit_code} status={status} duration_ms={duration_ms}\n"
            f"execution_mode={isolation_meta.get('execution_mode')} "
            f"fs_isolation={isolation_meta.get('fs_isolation')} "
            f"adapter={isolation_meta.get('adapter')}\n"
            f"--- stdout ---\n{stdout}\n"
            f"--- stderr ---\n{stderr}\n"
        )
        artifact = self.artifacts.create_text_result(
            name=f"terminal-{int(time.time())}.txt",
            text=transcript,
            mime_type="text/plain",
            conversation_id=conversation_id,
            task_id=task_id,
            kind="log",
        )
        stdout = stdout[-int(out_limit) :] if out_limit is not None else stdout
        stderr = stderr[-int(out_limit) :] if out_limit is not None else stderr
        return {
            "status": status,
            "argv": cleaned,
            "cwd": str(workdir),
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "stdout": stdout,
            "stderr": stderr,
            "allowlist": allowlist,
            "artifact_id": artifact.get("id"),
            "created_at": utc_now(),
            **isolation_meta,
        }
