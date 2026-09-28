from __future__ import annotations

from pathlib import Path
from typing import Any


def run(
    selector: str | None = None,
    *,
    timeout_seconds: int = 120,
    cwd: str | None = None,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    """Run tests via the canonical Coding process runner (pytest or npm).

    Exit code is the sole success authority. Process-tree kill on timeout/cancel.
    """
    from Data.modules.coding.verify_ops import run_verification

    root = workspace_root or cwd or str(Path.cwd())
    result = run_verification(
        phase="test",
        workspace_root=root,
        selector=selector,
        timeout_seconds=timeout_seconds,
        cwd=cwd if workspace_root else None,
    )
    # Preserve legacy keys expected by CodingLoop / receipts.
    return {
        "passed": bool(result.get("passed")),
        "exit_code": int(result.get("exit_code") or 1),
        "stdout": str(result.get("stdout") or "")[:20_000],
        "stderr": str(result.get("stderr") or "")[:20_000],
        "argv": list(result.get("argv") or []),
        "cwd": str(result.get("cwd") or root),
        "status": str(result.get("status") or "FAILED"),
        "error": result.get("error"),
        "process_killed": bool(result.get("process_killed")),
        "duration_seconds": result.get("duration_seconds"),
        "generation": result.get("generation"),
        "executed": True,
        "capability": "coding.run_tests",
        "truth": {
            **dict(result.get("truth") or {}),
            "configuration_is_not_enforcement_proof": True,
            "exit_code_is_authority": True,
        },
    }
