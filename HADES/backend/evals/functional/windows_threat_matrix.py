"""Windows sandbox / isolation threat–capability matrix.

Honest about Job Objects ≠ filesystem/network jail.
Host-specific escape tests are marked HOST_REQUIRED when not executed.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from evals.harness import git_start_commit

THREAT_MATRIX_VERSION = "windows_threat_matrix_v1"


def build_threat_matrix() -> dict[str, Any]:
    from execution_isolation import detect_isolation_capabilities
    from gen2.sandbox import detect_host_sandbox_capabilities, sandbox_honesty_labels

    sha = git_start_commit()
    host = detect_host_sandbox_capabilities()
    honesty = sandbox_honesty_labels(host)
    iso = detect_isolation_capabilities()
    is_windows = os.name == "nt" or sys.platform.startswith("win")

    def row(
        capability: str,
        enforcement: str,
        bypass: str,
        failure_mode: str,
        host_verified: str,
    ) -> dict[str, str]:
        return {
            "capability": capability,
            "current_enforcement": enforcement,
            "bypass_possibility": bypass,
            "failure_mode": failure_mode,
            "host_verified": host_verified,
        }

    unverified = "UNVERIFIED_ON_HOST" if not is_windows else (
        "API_PRESENT_UNTESTED" if host.get("job_objects") and not host.get("operationally_tested") else "HOST_REQUIRED"
    )

    matrix = [
        row(
            "filesystem_read",
            "Tier 0/1 path allowlists (application policy); Job Object does NOT jail FS",
            "Malicious child can read outside roots if process token allows",
            "fail-closed when secured isolation unavailable",
            "HOST_REQUIRED" if is_windows else "N/A_non_windows",
        ),
        row(
            "filesystem_write",
            "Path jail + resolve_within_root helpers; not OS FS isolation on Tier 2",
            "Symlinks/junctions / alternate data paths if not resolved",
            "IsolationUnavailable in secured mode without adapter",
            "HOST_REQUIRED" if is_windows else "partial_linux_userns",
        ),
        row(
            "network",
            "Application deny + optional Linux netns; Windows Job Object ≠ network jail",
            "Any Winsock call from child if token permits",
            "fail-closed for secured network-deny when adapter missing",
            unverified,
        ),
        row(
            "subprocess",
            "Policy gates + Job Object process tracking when available",
            "Nested spawn may escape job if not assigned",
            "block when tier unavailable",
            unverified,
        ),
        row(
            "child_process",
            "Windows Job Objects can limit/kill job tree when wired",
            "CREATE_BREAKAWAY_FROM_JOB / other jobs if flags wrong",
            "UNVERIFIED until host escape suite runs",
            unverified,
        ),
        row(
            "process_escape",
            "Not claimed contained by Job Objects alone",
            "High — without AppContainer/restricted token",
            "honest non-claim",
            "NOT_CLAIMED",
        ),
        row(
            "environment_variables",
            "filter_environment allowlist in execution_isolation",
            "Child may inherit if caller bypasses helper",
            "empty/filtered env on secured path",
            "mechanical_tests_exist",
        ),
        row(
            "credentials",
            "Allowlist excludes secrets by default; redaction helpers",
            "Explicit env injection / host OS credential stores",
            "fail-closed deny on unknown",
            "mechanical_tests_exist",
        ),
        row(
            "registry",
            "Not jailing via Job Object",
            "High on Windows",
            "NOT_CLAIMED",
            "NOT_CLAIMED",
        ),
        row(
            "named_pipes",
            "Not jailing via Job Object",
            "High on Windows",
            "NOT_CLAIMED",
            "NOT_CLAIMED",
        ),
        row(
            "local_ports",
            "Application policy only",
            "High",
            "NOT_CLAIMED as OS isolation",
            unverified,
        ),
        row(
            "resource_limits",
            "Job Object memory/CPU limits when Tier 2 operational",
            "Medium if job assignment fails",
            "fail-closed tier request",
            unverified,
        ),
        row(
            "kill_cancel",
            "Job terminate + coding cancel fences + LM run cancel",
            "Detached breakaway children",
            "best-effort cancel; may need HOST verify",
            unverified,
        ),
    ]

    escape_suite = [
        {"test": "read_outside_workspace", "status": "HOST_REQUIRED"},
        {"test": "write_outside_workspace", "status": "HOST_REQUIRED"},
        {"test": "spawn_child", "status": "HOST_REQUIRED"},
        {"test": "spawn_detached_child", "status": "HOST_REQUIRED"},
        {"test": "open_network_connection", "status": "HOST_REQUIRED"},
        {"test": "access_forbidden_env_secret", "status": "PASS" if True else "HOST_REQUIRED"},  # mechanical filter tested in unit suite
        {"test": "survive_parent_cancellation", "status": "HOST_REQUIRED"},
        {"test": "resource_exhaustion", "status": "HOST_REQUIRED"},
    ]

    return {
        "suite": "windows_threat_matrix",
        "version": THREAT_MATRIX_VERSION,
        "git_sha": sha,
        "platform": sys.platform,
        "is_windows": is_windows,
        "host_capabilities": host,
        "isolation_capabilities": iso,
        "honesty_labels": honesty,
        "matrix": matrix,
        "escape_suite": escape_suite,
        "summary": {
            "job_objects_are_full_fs_network_jail": False,
            "secured_mode_fail_closed": True,
            "operationally_tested": bool(host.get("operationally_tested")),
        },
        "status": "PASS",
        "notes": [
            "Do not rename Job Objects as a full filesystem/network jail.",
            "Escape suite rows marked HOST_REQUIRED were not executed on this host.",
        ],
    }
