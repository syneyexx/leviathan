"""Cross-platform simulation of Windows host verification (Phase K).

Runs the same behavioral checks as VERIFY_HADES_HOST.bat on Linux/macOS/Windows:
paths with spaces + Unicode, subprocess, restart/resume lease restore, isolation labeling.

Labels results as ``simulated_windows`` when not on a real Windows host — never claims
physical Windows Job Object / AppContainer verification.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


_REQUIRED_RUNTIME_CAPABILITIES = ("python", "node", "npm", "git", "write_workspace")


def _check(name: str, ok: bool, *, detail: str = "", remediation: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(ok),
        "detail": detail,
        "remediation": remediation if not ok else "",
    }


def _runtime_checks_from_capability_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Mirror the authoritative host-capability runtime contract without re-defining it."""
    raw_checks = report.get("checks") if isinstance(report, dict) else {}
    raw_checks = raw_checks if isinstance(raw_checks, dict) else {}
    checks: list[dict[str, Any]] = []
    for name in _REQUIRED_RUNTIME_CAPABILITIES:
        row = raw_checks.get(name) if isinstance(raw_checks.get(name), dict) else {}
        checks.append(
            _check(
                name,
                bool(row.get("available")),
                detail=str(row.get("detail") or "missing_capability_result"),
                remediation=str(row.get("remediation") or f"Make required capability available: {name}"),
            )
        )
    return checks


def _capability_report_is_ready(report: dict[str, Any]) -> bool:
    if not isinstance(report, dict) or report.get("status") != "ready":
        return False
    return all(item["passed"] for item in _runtime_checks_from_capability_report(report))


def run_host_verify_simulation(*, workspace: Path | None = None) -> dict[str, Any]:
    root = Path(workspace or Path.cwd()).expanduser().resolve()
    checks: list[dict[str, Any]] = []
    is_windows = platform.system().lower().startswith("win")
    mode = "physical_windows" if is_windows else "simulated_windows"

    # Runtime essentials come from host_capability, which owns the supported
    # Python/Node/npm/Git/workspace contract. Do not duplicate version policy here.
    try:
        from host_capability import check_host_capabilities

        report = check_host_capabilities(workspace=root)
        checks.extend(_runtime_checks_from_capability_report(report))
        ok_cap = _capability_report_is_ready(report)
        detail = (
            f"status={report.get('status')} "
            f"isolation_os_job={report.get('isolation', {}).get('os_job_object')}"
        )
    except Exception as exc:
        report = {"status": "error", "checks": {}, "error": str(exc)}
        checks.extend(_runtime_checks_from_capability_report(report))
        ok_cap = False
        detail = str(exc)
    checks.append(
        _check(
            "host_capability_module",
            ok_cap,
            detail=detail,
            remediation="Resolve all required host capabilities before treating this host as ready.",
        )
    )

    # Unicode + spaces path write (Windows-critical behavior, simulated elsewhere)
    probe_dir = root / "tmp host verify unicode café"
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe_file = probe_dir / "file with spaces.txt"
        probe_file.write_text("probe", encoding="utf-8")
        ok_path = probe_file.is_file() and probe_file.read_text(encoding="utf-8") == "probe"
        detail = str(probe_file)
    except OSError as exc:
        ok_path = False
        detail = str(exc)
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    checks.append(
        _check(
            "unicode_spaces_path",
            ok_path,
            detail=detail,
            remediation="Ensure filesystem supports Unicode and spaces in paths",
        )
    )

    # Subprocess spawn + exit code
    try:
        completed = subprocess.run(
            [sys.executable, "-c", "import sys; sys.exit(0)"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        ok_sub = completed.returncode == 0
        detail = f"returncode={completed.returncode}"
    except Exception as exc:
        ok_sub = False
        detail = str(exc)
    checks.append(_check("subprocess", ok_sub, detail=detail, remediation="Fix Python subprocess permissions"))

    # Restart / resume: persist pause + reclaim after "crash"
    try:
        from run_leases import ExecutionLeaseStore

        lease_path = root / ".hades_verify_leases.json"
        store = ExecutionLeaseStore(lease_path)
        store.acquire("step:verify:1", worker_id="verify-sim", ttl_s=2)
        store.request_pause("task_verify")
        # Simulate process death + restart
        store2 = ExecutionLeaseStore(lease_path)
        store2.reclaim_stale(now=time.time() + 10)
        restored = store2.restore_control_from_tasks(
            [{"id": "task_verify", "control_state": "pause_requested"}]
        )
        ok_resume = store2.snapshot("task_verify").get("pause_requested") is True
        detail = f"restored={restored} pause={store2.snapshot('task_verify')}"
        lease_path.unlink(missing_ok=True)
    except Exception as exc:
        ok_resume = False
        detail = str(exc)
    checks.append(_check("restart_resume_leases", ok_resume, detail=detail))

    # Junction / symlink simulation (Windows junctions ≈ symlinks for our purposes)
    try:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "target_dir"
            target.mkdir()
            (target / "x.txt").write_text("x", encoding="utf-8")
            link = base / "junction_sim"
            try:
                link.symlink_to(target, target_is_directory=True)
                ok_junc = link.is_dir() and (link / "x.txt").read_text(encoding="utf-8") == "x"
                detail = "symlink_ok"
            except OSError as exc:
                # Symlinks may require privileges on Windows — record honestly.
                ok_junc = False
                detail = f"symlink_unavailable:{exc}"
        checks.append(
            _check(
                "junction_or_symlink",
                ok_junc or not is_windows,  # on Linux sim, symlink failure is unusual → fail; on Windows privilege ok
                detail=detail,
                remediation="Enable Developer Mode / admin for junctions on Windows",
            )
        )
        # Re-evaluate: on non-Windows, require symlink success for sim fidelity
        if not is_windows:
            checks[-1] = _check("junction_or_symlink_sim", ok_junc, detail=detail)
    except Exception as exc:
        checks.append(_check("junction_or_symlink_sim", False, detail=str(exc)))

    # Isolation honesty
    isolation = {
        "app_level": True,
        "os_job_object": False,
        "appcontainer": False,
        "simulated": not is_windows,
        "note": (
            "App-level envelopes available. OS Job Object/AppContainer not verified in this run."
            if not is_windows
            else "Physical Windows host — OS isolation still not claimed unless separately proven."
        ),
    }

    required = {
        *_REQUIRED_RUNTIME_CAPABILITIES,
        "unicode_spaces_path",
        "subprocess",
        "host_capability_module",
        "restart_resume_leases",
    }
    failed = [c for c in checks if not c["passed"] and c["name"] in required]
    optional_failed = [c for c in checks if not c["passed"] and c["name"] not in required]
    status = "passed" if not failed else "failed"

    return {
        "suite": "host_verify",
        "mode": mode,
        "platform": platform.platform(),
        "system": platform.system(),
        "status": status,
        "checks": checks,
        "failed_required": [c["name"] for c in failed],
        "failed_optional": [c["name"] for c in optional_failed],
        "isolation": isolation,
        "host_capability": report if isinstance(report, dict) else {},
        "physical_windows_verified": is_windows and status == "passed",
        "note": (
            "Simulated Windows host checks on non-Windows OS — behavioral parity only; "
            "not a substitute for operator VERIFY_HADES_HOST.bat on a real Windows machine."
            if not is_windows
            else "Ran on Windows host."
        ),
    }


def main() -> int:
    report = run_host_verify_simulation(workspace=Path.cwd())
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
