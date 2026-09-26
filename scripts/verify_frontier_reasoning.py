#!/usr/bin/env python3
"""Offline verification harness for the LEVIATHAN Frontier Reasoning Program.

Human architecture/program documentation is consolidated into the two canonical
Data/docs files. Machine gate state stays in Data/backend/tests.

Exit NON-ZERO unless every required R01-R30 gate is PASS, except when
--allow-f0-skeleton-only is explicitly requested.
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
BACKEND_DOC = ROOT / "Data" / "docs" / "Leviathan_system_backend.md"
FRONTEND_DOC = ROOT / "Data" / "docs" / "Leviathan_system_frontend.md"
REPORT_JSON = ROOT / "Data" / "backend" / "tests" / "frontier_reasoning_completion_report.json"

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
    return ("PASS", f"exists:{path}") if p.is_file() else ("FAIL", f"missing:{path}")


def _check_forbidden_symbols(symbols: list[str]) -> tuple[str, str]:
    hits: list[str] = []
    for base in (ROOT / "Data" / "modules", ROOT / "Data" / "backend"):
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for symbol in symbols:
                if symbol in text:
                    hits.append(f"{path.relative_to(ROOT)}:{symbol}")
    return (
        ("FAIL", "forbidden:" + ";".join(hits[:8]))
        if hits
        else ("PASS", "no_forbidden_runtime_classes")
    )


def _check_preservation() -> tuple[str, str]:
    missing = [path for path in REQUIRED_MODULES if not (ROOT / path).is_file()]
    return (
        ("FAIL", "missing_owners:" + ",".join(missing[:6]))
        if missing
        else ("PASS", f"owners_present:{len(REQUIRED_MODULES)}")
    )


def _run_skeleton(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in manifest.get("f0_skeleton_checks") or []:
        check = item.get("check")
        if check == "file_exists":
            status, evidence = _check_file_exists(str(item.get("path") or ""))
        elif check == "forbidden_symbols_absent":
            status, evidence = _check_forbidden_symbols(list(item.get("symbols") or []))
        else:
            status, evidence = "FAIL", f"unknown_check:{check}"
        results.append({
            "id": item.get("id"),
            "required": bool(item.get("required", True)),
            "status": status,
            "evidence": evidence,
            "kind": "f0_skeleton",
        })
    status, evidence = _check_preservation()
    results.append({
        "id": "F0_PRESERVATION_OWNERS",
        "required": True,
        "status": status,
        "evidence": evidence,
        "kind": "f0_skeleton",
    })
    return results


def _run_program_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for gate in manifest.get("gates") or []:
        declared = str(gate.get("status") or "NOT_STARTED").upper()
        evidence = str(gate.get("evidence") or gate.get("notes") or "—")
        if declared == "PASS" and evidence not in {"", "—", "None", "null"}:
            status = "PASS"
        elif declared == "PASS":
            status, evidence = "FAIL", "PASS_without_evidence"
        else:
            allowed = {
                "NOT_STARTED",
                "IN_PROGRESS",
                "FAIL",
                "NOT_TESTED",
                "NOT_TESTED_IN_CI",
                "UNMEASURED",
                "FEATURE_GATED",
                "PARTIAL",
            }
            status = declared if declared in allowed else "NOT_STARTED"
        results.append({
            "id": gate.get("id"),
            "title": gate.get("title"),
            "required": bool(gate.get("required", True)),
            "status": status,
            "evidence": evidence,
            "phase": gate.get("phase"),
            "kind": "program_gate",
        })
    return results


def _print_table(rows: list[dict[str, Any]], *, title: str) -> None:
    print(f"\n=== {title} ===")
    print(f"{'ID':<28} {'STATUS':<18} EVIDENCE")
    print("-" * 92)
    for row in rows:
        print(f"{str(row.get('id') or ''):<28} {str(row.get('status') or ''):<18} {row.get('evidence')}")


def _write_report_json(*, skeleton: list[dict[str, Any]], gates: list[dict[str, Any]], exit_code: int) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps({
        "program": "frontier_reasoning",
        "generated_at": _utcnow(),
        "exit_code": exit_code,
        "definition_of_done": exit_code == 0,
        "canonical_backend_doc": str(BACKEND_DOC.relative_to(ROOT)),
        "canonical_frontend_doc": str(FRONTEND_DOC.relative_to(ROOT)),
        "skeleton": skeleton,
        "gates": gates,
        "truth": {
            "f0_skeleton_pass_is_not_program_done": True,
            "unmeasured_is_not_passed": True,
            "required_gate_not_pass_exits_nonzero": True,
        },
    }, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-f0-skeleton-only", action="store_true",
                        help="Exit 0 when structural F0 checks pass even while R01-R30 remain open.")
    parser.add_argument("--write-report", action="store_true",
                        help="Write Data/backend/tests/frontier_reasoning_completion_report.json")
    args = parser.parse_args(argv)

    if not GATES_PATH.is_file():
        print(f"FAIL: missing gates manifest {GATES_PATH}", file=sys.stderr)
        return 2

    manifest = _load_gates()
    skeleton = _run_skeleton(manifest)
    gates = _run_program_gates(manifest)
    _print_table(skeleton, title="F0 structural checks")
    _print_table(gates, title="Program gates R01-R30")

    skel_fail = [r for r in skeleton if r.get("required") and r.get("status") != "PASS"]
    gate_fail = [r for r in gates if r.get("required") and r.get("status") != "PASS"]

    print(f"\nCanonical backend doc: {'OK' if BACKEND_DOC.is_file() else 'MISSING'}")
    print(f"Canonical frontend doc: {'OK' if FRONTEND_DOC.is_file() else 'MISSING'}")
    print(f"Structural failures: {len(skel_fail)}")
    print(f"Required program gates not PASS: {len(gate_fail)}")

    if skel_fail:
        exit_code = 1
        reason = "structural checks failed"
    elif gate_fail and not args.allow_f0_skeleton_only:
        exit_code = 1
        reason = "required program gates R01-R30 not all PASS"
    else:
        exit_code = 0
        reason = "structural baseline PASS" if gate_fail else "all required gates PASS"
    print(f"Result: exit={exit_code} — {reason}")

    if args.write_report:
        _write_report_json(skeleton=skeleton, gates=gates, exit_code=exit_code)
        print(f"Wrote {REPORT_JSON.relative_to(ROOT)}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
