#!/usr/bin/env python3
"""Offline verification harness for LEVIATHAN Frontier Reasoning Program.

Reads Data/backend/tests/frontier_reasoning_gates.json, runs configured checks,
prints a gate table, updates the completion report summary when requested, and
exits NON-ZERO unless every *required* program gate (R01–R30) is PASS.

F0 skeleton checks (docs/files/anti-duplicate-runtime) may PASS independently.
They do NOT satisfy Definition of Done.

Live LLM / GPU paths must stay NOT_TESTED_IN_CI or UNMEASURED — never fake PASS.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GATES_PATH = ROOT / "Data" / "backend" / "tests" / "frontier_reasoning_gates.json"
STATE_PATH = ROOT / "Data" / "docs" / "frontier_reasoning_program_state.md"
AUDIT_PATH = ROOT / "Data" / "docs" / "frontier_reasoning_f0_audit.md"
REPORT_MD = ROOT / "Data" / "docs" / "frontier_reasoning_completion_report.md"
REPORT_JSON = ROOT / "Data" / "docs" / "frontier_reasoning_completion_report.json"

# Owners that must remain present (preservation scan).
REQUIRED_MODULES = (
    "Data/modules/cognition/runtime.py",
    "Data/modules/reasoning/engine.py",
    "Data/modules/cognition/meta_controller.py",
    "Data/modules/cognition/planner.py",
    "Data/modules/cognition/action_selector.py",
    "Data/modules/cognition/working_memory.py",
    "Data/modules/cognition/belief_state.py",
    "Data/modules/cognition/perception.py",
    "Data/modules/cognition/context_v3.py",
    "Data/modules/context/builder.py",
    "Data/modules/brain/facade.py",
    "Data/modules/knowledge/retrieval.py",
    "Data/modules/memory/store.py",
    "Data/modules/neuro/advisor.py",
    "Data/modules/evidence/service.py",
    "Data/modules/execution/gateway.py",
    "Data/modules/agents/fleet.py",
    "Data/modules/models/control_plane.py",
    "Data/modules/jobs/runtime.py",
    "Data/modules/workers/supervisor.py",
    "Data/modules/settings/service.py",
    "Data/modules/training/service.py",
    "Data/modules/evaluation/harness.py",
    "Data/modules/cognition/experience.py",
    "Data/modules/verification/engine.py",
)


def _load_gates() -> dict[str, Any]:
    with GATES_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _check_file_exists(path: str) -> tuple[str, str]:
    p = ROOT / path
    if p.is_file():
        return "PASS", f"exists:{path}"
    return "FAIL", f"missing:{path}"


def _check_forbidden_symbols(symbols: list[str]) -> tuple[str, str]:
    """Scan Python sources for forbidden parallel-runtime class names."""
    hits: list[str] = []
    scan_roots = [
        ROOT / "Data" / "modules",
        ROOT / "Data" / "backend",
    ]
    for base in scan_roots:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for sym in symbols:
                if sym in text:
                    rel = str(path.relative_to(ROOT)).replace("\\", "/")
                    hits.append(f"{rel}:{sym}")
    if hits:
        return "FAIL", "forbidden:" + ";".join(hits[:8])
    return "PASS", "no_forbidden_runtime_classes"


def _check_preservation() -> tuple[str, str]:
    missing = [p for p in REQUIRED_MODULES if not (ROOT / p).is_file()]
    if missing:
        return "FAIL", "missing_owners:" + ",".join(missing[:6])
    return "PASS", f"owners_present:{len(REQUIRED_MODULES)}"


def _run_skeleton(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in manifest.get("f0_skeleton_checks") or []:
        check = item.get("check")
        status = "NOT_TESTED"
        evidence = ""
        if check == "file_exists":
            status, evidence = _check_file_exists(str(item.get("path") or ""))
        elif check == "forbidden_symbols_absent":
            status, evidence = _check_forbidden_symbols(list(item.get("symbols") or []))
        else:
            status, evidence = "FAIL", f"unknown_check:{check}"
        results.append(
            {
                "id": item.get("id"),
                "required": bool(item.get("required", True)),
                "status": status,
                "evidence": evidence,
                "kind": "f0_skeleton",
            }
        )
    # Always run preservation as an F0 structural check.
    st, ev = _check_preservation()
    results.append(
        {
            "id": "F0_PRESERVATION_OWNERS",
            "required": True,
            "status": st,
            "evidence": ev,
            "kind": "f0_skeleton",
        }
    )
    return results


def _run_program_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Program gates R01–R30: only PASS when manifest status is PASS with evidence.

    F0 leaves them NOT_STARTED → verifier fails (by design).
    """
    results: list[dict[str, Any]] = []
    for gate in manifest.get("gates") or []:
        declared = str(gate.get("status") or "NOT_STARTED").upper()
        evidence = str(gate.get("evidence") or gate.get("notes") or "—")
        # Automated PASS criteria grow in later phases; F0 never auto-promotes.
        if declared == "PASS" and evidence not in {"", "—", "None", "null"}:
            status = "PASS"
        elif declared == "PASS":
            status = "FAIL"
            evidence = "PASS_without_evidence"
        else:
            status = declared if declared in {"NOT_STARTED", "IN_PROGRESS", "FAIL", "NOT_TESTED"} else "NOT_STARTED"
        results.append(
            {
                "id": gate.get("id"),
                "title": gate.get("title"),
                "required": bool(gate.get("required", True)),
                "status": status,
                "evidence": evidence,
                "phase": gate.get("phase"),
                "kind": "program_gate",
            }
        )
    return results


def _print_table(rows: list[dict[str, Any]], *, title: str) -> None:
    print()
    print(f"=== {title} ===")
    print(f"{'ID':<28} {'STATUS':<14} EVIDENCE")
    print("-" * 88)
    for row in rows:
        print(f"{str(row.get('id') or ''):<28} {str(row.get('status') or ''):<14} {row.get('evidence')}")


def _write_report_json(
    *,
    skeleton: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    exit_code: int,
) -> None:
    payload = {
        "program": "frontier_reasoning",
        "generated_at": _utcnow(),
        "phase": "F0",
        "exit_code": exit_code,
        "definition_of_done": exit_code == 0,
        "skeleton": skeleton,
        "gates": gates,
        "truth": {
            "f0_skeleton_pass_is_not_program_done": True,
            "unmeasured_is_not_passed": True,
            "required_gate_not_pass_exits_nonzero": True,
        },
    }
    REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-f0-skeleton-only",
        action="store_true",
        help="Exit 0 if F0 skeleton checks PASS even when R01–R30 are NOT_STARTED. "
        "Default: exit non-zero until all required program gates PASS (program contract).",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write Data/docs/frontier_reasoning_completion_report.json",
    )
    args = parser.parse_args(argv)

    if not GATES_PATH.is_file():
        print(f"FAIL: missing gates manifest {GATES_PATH}", file=sys.stderr)
        return 2

    manifest = _load_gates()
    skeleton = _run_skeleton(manifest)
    gates = _run_program_gates(manifest)

    _print_table(skeleton, title="F0 skeleton checks")
    _print_table(gates, title="Program gates R01–R30")

    skel_fail = [r for r in skeleton if r.get("required") and r.get("status") != "PASS"]
    gate_fail = [r for r in gates if r.get("required") and r.get("status") != "PASS"]

    print()
    print(f"Audit doc: {'OK' if AUDIT_PATH.is_file() else 'MISSING'} ({AUDIT_PATH})")
    print(f"Program state: {'OK' if STATE_PATH.is_file() else 'MISSING'} ({STATE_PATH})")
    print(f"Skeleton failures: {len(skel_fail)}")
    print(f"Required program gates not PASS: {len(gate_fail)}")

    if skel_fail:
        exit_code = 1
        reason = "F0 skeleton checks failed"
    elif gate_fail and not args.allow_f0_skeleton_only:
        exit_code = 1
        reason = "required program gates R01–R30 not all PASS (expected until F18)"
    else:
        exit_code = 0
        reason = (
            "F0 skeleton PASS (--allow-f0-skeleton-only); program gates still open"
            if gate_fail
            else "all required gates PASS"
        )

    print(f"Result: exit={exit_code} — {reason}")

    if args.write_report:
        _write_report_json(skeleton=skeleton, gates=gates, exit_code=exit_code)
        print(f"Wrote {REPORT_JSON}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
