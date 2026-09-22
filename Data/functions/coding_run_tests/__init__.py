from __future__ import annotations

import os
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
    """Run tests via subprocess (pytest or npm). Capture exit code honestly."""
    work = Path(cwd or workspace_root or Path.cwd())
    timeout = max(1, int(timeout_seconds))
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV", ""),
    }
    # Drop obviously sensitive vars.
    for key in list(env):
        if not env[key]:
            env.pop(key, None)

    sel = (selector or "").strip()
    if sel.startswith("npm ") or sel == "npm test" or sel.startswith("npm:"):
        script = sel.split(":", 1)[1] if sel.startswith("npm:") else "test"
        if sel.startswith("npm "):
            argv = sel.split()
        else:
            argv = ["npm", "test"] if script == "test" else ["npm", "run", script]
    else:
        # Default: pytest on coding tests or operator selector.
        target = sel or "Data/backend/tests/test_coding_agent.py"
        argv = [sys.executable, "-m", "pytest", target, "-q"]

    try:
        proc = subprocess.run(
            argv,
            cwd=str(work),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
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
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "passed": False,
            "exit_code": 124,
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "") if isinstance(exc.stderr, str) else "timeout",
            "argv": argv,
            "cwd": str(work),
            "status": "FAILED",
            "error": f"timeout after {timeout}s",
        }

    passed = proc.returncode == 0
    return {
        "passed": passed,
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "")[:20_000],
        "stderr": (proc.stderr or "")[:20_000],
        "argv": argv,
        "cwd": str(work),
        "status": "PASSED" if passed else "FAILED",
    }
