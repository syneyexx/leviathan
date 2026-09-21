"""Host capability checks with concrete remediation hints (Phase K)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


MIN_PYTHON_VERSION = (3, 11, 0)
MIN_NODE_VERSION = (22, 13, 0)


def _parse_version(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(value or "").strip())
    if not match:
        return None
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3) or 0),
    )


def _version_at_least(actual: tuple[int, int, int], minimum: tuple[int, int, int]) -> bool:
    return actual >= minimum


def _check_node_runtime(node_path: str | None) -> tuple[bool, str]:
    if not node_path:
        return False, "missing"
    try:
        completed = subprocess.run(
            [node_path, "--version"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"version_probe_failed:{exc.__class__.__name__}"
    raw = (completed.stdout or completed.stderr or "").strip()
    version = _parse_version(raw)
    if completed.returncode != 0 or version is None:
        return False, raw or f"exit_{completed.returncode}"
    rendered = ".".join(str(part) for part in version)
    return _version_at_least(version, MIN_NODE_VERSION), f"{rendered} ({node_path})"


def check_host_capabilities(*, workspace: Path | None = None) -> dict[str, Any]:
    root = Path(workspace or Path.cwd()).expanduser().resolve()
    checks: dict[str, Any] = {}

    def _ok(name: str, available: bool, *, detail: str, fix: str) -> None:
        checks[name] = {
            "available": available,
            "detail": detail,
            "remediation": fix if not available else "",
        }

    python_version = (
        int(sys.version_info[0]),
        int(sys.version_info[1]),
        int(sys.version_info[2]),
    )
    _ok(
        "python",
        _version_at_least(python_version, MIN_PYTHON_VERSION),
        detail=f"{sys.version.split()[0]}",
        fix="Install Python 3.11+ and recreate the venv.",
    )

    node = shutil.which("node")
    node_ok, node_detail = _check_node_runtime(node)
    _ok(
        "node",
        node_ok,
        detail=node_detail,
        fix="Install Node.js 22.13+ and ensure node is on PATH.",
    )
    npm = shutil.which("npm")
    _ok("npm", bool(npm), detail=npm or "missing", fix="Install npm (comes with Node.js) and ensure npm is on PATH.")
    git = shutil.which("git")
    _ok("git", bool(git), detail=git or "missing", fix="Install Git for Windows / git package.")

    writable = False
    try:
        probe = root / ".hades_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        writable = True
    except OSError as exc:
        detail = str(exc)
    else:
        detail = str(root)
    _ok(
        "write_workspace",
        writable,
        detail=detail,
        fix="Choose a workspace directory with write permission for the HADES user.",
    )

    # Model connection is optional; report reachability attempt without inventing success.
    lm_url = os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    model_reachable = False
    model_detail = "not_probed"
    try:
        import urllib.request

        req = urllib.request.Request(lm_url.rstrip("/") + "/models", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:  # noqa: S310 — local optional probe
            model_reachable = 200 <= getattr(resp, "status", 200) < 300
            model_detail = f"http_{getattr(resp, 'status', '?')}"
    except Exception as exc:
        model_detail = f"unreachable:{exc.__class__.__name__}"
    _ok(
        "model_connection",
        model_reachable,
        detail=f"{lm_url} ({model_detail})",
        fix="Start LM Studio local server or update HADES_LM_STUDIO_BASE_URL.",
    )

    browser = bool(shutil.which("chrome") or shutil.which("chromium") or shutil.which("msedge"))
    _ok(
        "browser_optional",
        browser,
        detail="browser binary on PATH" if browser else "no chrome/edge/chromium on PATH",
        fix="Optional: install Chrome/Edge for preview screenshots via plugin adapters.",
    )

    isolation = {
        "app_level": True,
        "os_job_object": False,
        "appcontainer": False,
        "docker": bool(shutil.which("docker")),
        "note": "Resource limits alone are not filesystem/network isolation.",
    }

    available = sum(1 for c in checks.values() if c["available"])
    required = ("python", "node", "npm", "git", "write_workspace")
    status = "ready" if all(checks[key]["available"] for key in required) else "degraded"
    return {
        "status": status,
        "checks": checks,
        "available_count": available,
        "total_checks": len(checks),
        "isolation": isolation,
        "platform": sys.platform,
        "workspace": str(root),
    }
