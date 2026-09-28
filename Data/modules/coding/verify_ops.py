"""Typed Coding verification operations — test / lint / typecheck / build.

All subprocess execution goes through the canonical process runner.
Tool selection comes from detected project metadata, not free-form model text.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from Data.modules.coding.process import ProcessResult, run_argv
from Data.modules.coding.workspace import confine
from Data.modules.common.paths import PathEscapeError


_ALLOWED_PHASES = frozenset({"test", "lint", "typecheck", "build"})

# Allowlisted tool binaries (basename) — never arbitrary model strings as executables.
_ALLOWED_TOOLS: dict[str, frozenset[str]] = {
    "test": frozenset({"pytest", "npm", "pnpm", "yarn", "cargo", "go"}),
    "lint": frozenset({"ruff", "eslint", "flake8", "cargo", "golangci-lint"}),
    "typecheck": frozenset({"mypy", "pyright", "tsc", "cargo"}),
    "build": frozenset({"npm", "pnpm", "yarn", "cargo", "go", "python", "cmake"}),
}


def _tool_unavailable(tool: str, phase: str) -> dict[str, Any]:
    return {
        "ok": False,
        "passed": False,
        "phase": phase,
        "status": "TOOL_UNAVAILABLE",
        "error_code": "CODING_TOOL_UNAVAILABLE",
        "error": f"tool not available/detected: {tool}",
        "executed": False,
        "exit_code": 127,
        "argv": [],
    }


def _detect_default_tool(workspace_root: Path, phase: str) -> str | None:
    root = workspace_root
    if phase == "test":
        if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
            return "pytest"
        if (root / "package.json").exists():
            return "npm"
        if (root / "Cargo.toml").exists():
            return "cargo"
        if (root / "go.mod").exists():
            return "go"
        return "pytest"
    if phase == "lint":
        if (root / "pyproject.toml").exists() or (root / "ruff.toml").exists():
            return "ruff"
        if (root / "package.json").exists():
            return "eslint"
        if (root / "Cargo.toml").exists():
            return "cargo"
        return None
    if phase == "typecheck":
        if (root / "mypy.ini").exists() or (root / "pyproject.toml").exists():
            return "mypy"
        if (root / "tsconfig.json").exists():
            return "tsc"
        if (root / "Cargo.toml").exists():
            return "cargo"
        return None
    if phase == "build":
        if (root / "package.json").exists():
            return "npm"
        if (root / "Cargo.toml").exists():
            return "cargo"
        if (root / "go.mod").exists():
            return "go"
        return None
    return None


def _build_argv(
    phase: str,
    tool: str,
    *,
    selector: str | None,
    workspace_root: Path,
) -> list[str] | None:
    allowed = _ALLOWED_TOOLS.get(phase, frozenset())
    if tool not in allowed:
        return None
    sel = (selector or "").strip()

    if phase == "test":
        if tool == "pytest":
            target = sel or "."
            # Reject shell metacharacters as argv data is fine — but bound length.
            if len(target) > 500:
                target = target[:500]
            return [sys.executable, "-m", "pytest", target, "-q"]
        if tool == "npm":
            script = "test"
            if sel.startswith("npm:"):
                script = sel.split(":", 1)[1] or "test"
            elif sel and sel not in {"test", "npm test"}:
                script = sel
            # Validate script exists in package.json when present.
            pkg = workspace_root / "package.json"
            if pkg.exists():
                try:
                    import json

                    data = json.loads(pkg.read_text(encoding="utf-8"))
                    scripts = data.get("scripts") or {}
                    if script not in scripts:
                        return None
                except (OSError, json.JSONDecodeError, TypeError):
                    pass
            return ["npm", "run", script] if script != "test" else ["npm", "test"]
        if tool in {"pnpm", "yarn"}:
            return [tool, "test"]
        if tool == "cargo":
            return ["cargo", "test"]
        if tool == "go":
            return ["go", "test", "./..."]

    if phase == "lint":
        if tool == "ruff":
            return [sys.executable, "-m", "ruff", "check", sel or "."]
        if tool == "flake8":
            return [sys.executable, "-m", "flake8", sel or "."]
        if tool == "eslint":
            return ["npx", "--no-install", "eslint", sel or "."]
        if tool == "cargo":
            return ["cargo", "clippy", "--", "-D", "warnings"]
        if tool == "golangci-lint":
            return ["golangci-lint", "run"]

    if phase == "typecheck":
        if tool == "mypy":
            return [sys.executable, "-m", "mypy", sel or "."]
        if tool == "pyright":
            return [sys.executable, "-m", "pyright", sel or "."]
        if tool == "tsc":
            return ["npx", "--no-install", "tsc", "--noEmit"]
        if tool == "cargo":
            return ["cargo", "check"]

    if phase == "build":
        if tool == "npm":
            script = sel or "build"
            if script.startswith("npm:"):
                script = script.split(":", 1)[1] or "build"
            pkg = workspace_root / "package.json"
            if pkg.exists():
                try:
                    import json

                    data = json.loads(pkg.read_text(encoding="utf-8"))
                    scripts = data.get("scripts") or {}
                    if script not in scripts:
                        return None
                except (OSError, json.JSONDecodeError, TypeError):
                    pass
            return ["npm", "run", script]
        if tool in {"pnpm", "yarn"}:
            return [tool, "run", sel or "build"]
        if tool == "cargo":
            return ["cargo", "build"]
        if tool == "go":
            return ["go", "build", "./..."]
        if tool == "python":
            return [sys.executable, "-m", "build"]
        if tool == "cmake":
            return ["cmake", "--build", sel or "build"]

    return None


def run_verification(
    *,
    phase: str,
    workspace_root: Path | str,
    selector: str | None = None,
    tool: str | None = None,
    timeout_seconds: int = 120,
    cancel_check: Callable[[], bool] | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    phase_n = (phase or "test").strip().lower()
    if phase_n not in _ALLOWED_PHASES:
        return {
            "ok": False,
            "passed": False,
            "phase": phase_n,
            "status": "REJECTED",
            "error_code": "CODING_VERIFY_PHASE_INVALID",
            "error": f"unsupported phase: {phase_n}",
            "executed": False,
            "exit_code": 126,
        }

    root = Path(workspace_root)
    try:
        work = confine(root, cwd or ".")
    except PathEscapeError as exc:
        return {
            "ok": False,
            "passed": False,
            "phase": phase_n,
            "status": "REJECTED",
            "error_code": "WORKSPACE_DENIED",
            "error": str(exc),
            "executed": False,
            "exit_code": 126,
        }

    chosen = (tool or "").strip().lower() or (_detect_default_tool(root, phase_n) or "")
    if not chosen:
        return _tool_unavailable("(none)", phase_n)

    argv = _build_argv(phase_n, chosen, selector=selector, workspace_root=root)
    if argv is None:
        return _tool_unavailable(chosen, phase_n)

    result: ProcessResult = run_argv(
        argv,
        cwd=work,
        timeout_seconds=timeout_seconds,
        cancel_check=cancel_check,
        purpose=f"coding.verify.{phase_n}",
    )

    error_code = None
    if result.status == "TIMEOUT":
        error_code = "CODING_PROCESS_TIMEOUT"
    elif result.status == "CANCELLED":
        error_code = "CODING_PROCESS_CANCELLED"
    elif result.status == "FAILED":
        error_code = {
            "test": "CODING_TEST_FAILED",
            "lint": "CODING_LINT_FAILED",
            "typecheck": "CODING_TYPECHECK_FAILED",
            "build": "CODING_BUILD_FAILED",
        }.get(phase_n, "CODING_PROCESS_FAILED")

    return {
        "ok": result.passed,
        "passed": result.passed,
        "phase": phase_n,
        "tool": chosen,
        "status": result.status,
        "error_code": error_code,
        "error": result.error,
        "executed": True,
        "exit_code": result.exit_code,
        "argv": result.argv,
        "cwd": result.cwd,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_seconds": result.duration_seconds,
        "process_killed": result.process_killed,
        "truth": {
            **result.truth,
            "exit_code_is_authority": True,
            "no_implicit_install": True,
        },
    }
