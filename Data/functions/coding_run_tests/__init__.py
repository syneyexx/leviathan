from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any


def run(
    selector: str | None = None,
    *,
    timeout_seconds: int = 120,
    cwd: str | None = None,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    """Run tests via subprocess (pytest or npm). Capture exit code honestly.

    Round 8: cwd confined under workspace_root when provided; process group
    killed on timeout (soft future cancel is not enough).
    """
    timeout = max(1, int(timeout_seconds))
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV", ""),
    }
    for key in list(env):
        if not env[key]:
            env.pop(key, None)

    if workspace_root:
        from Data.modules.coding.workspace import confine
        from Data.modules.common.paths import PathEscapeError

        try:
            work = confine(Path(workspace_root), cwd or ".")
        except PathEscapeError as exc:
            return {
                "passed": False,
                "exit_code": 126,
                "stdout": "",
                "stderr": str(exc),
                "argv": [],
                "cwd": str(cwd or ""),
                "status": "REJECTED",
                "error": f"path_escape: {exc}",
                "process_killed": False,
                "truth": {"configuration_is_not_enforcement_proof": True},
            }
    else:
        work = Path(cwd or Path.cwd())

    sel = (selector or "").strip()
    if sel.startswith("npm ") or sel == "npm test" or sel.startswith("npm:"):
        script = sel.split(":", 1)[1] if sel.startswith("npm:") else "test"
        if sel.startswith("npm "):
            argv = sel.split()
        else:
            argv = ["npm", "test"] if script == "test" else ["npm", "run", script]
    else:
        target = sel or "Data/backend/tests/test_coding_agent.py"
        argv = [sys.executable, "-m", "pytest", target, "-q"]

    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(work),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            killed = False
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                killed = True
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                    killed = True
                except OSError:
                    pass
            stdout, stderr = proc.communicate()
            return {
                "passed": False,
                "exit_code": 124,
                "stdout": (stdout or "")[:20_000],
                "stderr": (stderr or "timeout")[:20_000],
                "argv": argv,
                "cwd": str(work),
                "status": "TIMEOUT",
                "error": f"timeout after {timeout}s",
                "process_killed": killed,
                "truth": {
                    "soft_timeout_is_not_termination": False,
                    "process_group_killed_on_timeout": killed,
                },
            }
    except FileNotFoundError as exc:
        return {
            "passed": False,
            "exit_code": 127,
            "stdout": "",
            "stderr": str(exc),
            "argv": argv,
            "cwd": str(work),
            "status": "FAILED",
            "error": f"executable missing: {exc}",
            "process_killed": False,
        }

    exit_code = int(proc.returncode or 0)
    passed = exit_code == 0
    return {
        "passed": passed,
        "exit_code": exit_code,
        "stdout": (stdout or "")[:20_000],
        "stderr": (stderr or "")[:20_000],
        "argv": argv,
        "cwd": str(work),
        "status": "PASSED" if passed else "FAILED",
        "process_killed": False,
    }
