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
import re
import subprocess
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


def _run_unittest(module: str) -> tuple[str, str]:
    code, out = _run(
        [sys.executable, "-m", "unittest", module, "-v"],
        timeout=180,
    )
    if code == 0:
        return "PASS", f"unittest:{module}"
    snippet = " ".join(out.strip().splitlines()[-6:])[:400]
    return "FAIL", f"unittest_failed:{module}:{snippet}"


def _run(cmd: list[str], *, timeout: int = 600) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, f"TIMEOUT: {exc}"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def _anti_fold_scan() -> tuple[str, str]:
    """R02 structural: ContextBuilderV3 must not fold all non-system into system."""
    path = ROOT / "Data" / "modules" / "cognition" / "context_v3.py"
    if not path.is_file():
        return "FAIL", "missing:context_v3.py"
    text = path.read_text(encoding="utf-8")
    if "serialize_reference_block" not in text:
        return "FAIL", "missing_serialize_reference_block"
    if "knowledge_in_system_role" not in text:
        return "FAIL", "missing_knowledge_in_system_role_flag"
    # Forbidden regression: fold all non-system sections into system_prompt.
    if re.search(
        r"data_sections\s*=\s*\[s for s in sections if s\.kind != [\"']system[\"']\]",
        text,
    ):
        return "FAIL", "regress_fold_all_into_system"
    if "authority_separation" not in text:
        return "FAIL", "missing_authority_separation_flag"
    return "PASS", "context_v3_authority_serialization_ok"


def _behavior_identity_scan() -> tuple[str, str]:
    """R03 structural: Cognition accepts BehaviorProfile; does not hard-require SEED only."""
    runtime = (ROOT / "Data" / "modules" / "cognition" / "runtime.py").read_text(encoding="utf-8")
    v3 = (ROOT / "Data" / "modules" / "cognition" / "context_v3.py").read_text(encoding="utf-8")
    main = (ROOT / "Data" / "backend" / "main.py").read_text(encoding="utf-8")
    if "behavior_profile_prompt" not in runtime:
        return "FAIL", "runtime_missing_behavior_profile_prompt"
    if "behavior_resolver" not in runtime:
        return "FAIL", "runtime_missing_behavior_resolver"
    if "behavior_profile_prompt" not in v3:
        return "FAIL", "context_v3_missing_behavior_profile_prompt"
    if "behavior_profile_prompt=behavior_snapshot.system_prompt" not in main:
        return "FAIL", "chat_does_not_pass_behavior_snapshot"
    return "PASS", "behavior_profile_wired_chat_and_cognition"


def _native_reasoning_scan() -> tuple[str, str]:
    """R06 structural: InferenceComputeController + native maps; no second runtime."""
    ctrl = ROOT / "Data" / "modules" / "cognition" / "inference_compute.py"
    native = ROOT / "Data" / "modules" / "models" / "native_reasoning.py"
    adapter = ROOT / "Data" / "modules" / "models" / "providers" / "openai_compatible.py"
    if not ctrl.is_file():
        return "FAIL", "missing:inference_compute.py"
    if not native.is_file():
        return "FAIL", "missing:native_reasoning.py"
    ctrl_text = ctrl.read_text(encoding="utf-8")
    native_text = native.read_text(encoding="utf-8")
    adapter_text = adapter.read_text(encoding="utf-8")
    if "class InferenceComputeController" not in ctrl_text:
        return "FAIL", "missing_InferenceComputeController"
    if "build_native_reasoning_hints" not in native_text:
        return "FAIL", "missing_build_native_reasoning_hints"
    if "generic_provider_family — no_unknown_reasoning_parameters" not in native_text:
        return "FAIL", "missing_generic_no_unknown_knobs"
    if "def reasoning_capability_profile" not in adapter_text:
        return "FAIL", "openai_adapter_missing_reasoning_capability_profile"
    if '"supports_native_reasoning": False' not in adapter_text:
        return "FAIL", "openai_adapter_must_default_native_false"
    return "PASS", "native_reasoning_controller_and_maps_ok"


def _cot_leakage_scan() -> tuple[str, str]:
    """R29 structural: private CoT fields stripped on public path."""
    native = ROOT / "Data" / "modules" / "models" / "native_reasoning.py"
    runtime_llm = ROOT / "Data" / "modules" / "model_runtime" / "openai_compatible.py"
    if not native.is_file():
        return "FAIL", "missing:native_reasoning.py"
    text = native.read_text(encoding="utf-8")
    llm_text = runtime_llm.read_text(encoding="utf-8") if runtime_llm.is_file() else ""
    if "def strip_private_reasoning_fields" not in text:
        return "FAIL", "missing_strip_private_reasoning_fields"
    if "reasoning_content" not in text or "thinking" not in text:
        return "FAIL", "strip_missing_private_field_names"
    if "strip_private_reasoning_fields" not in llm_text:
        return "FAIL", "llm_transport_does_not_strip_private_cot"
    return "PASS", "private_cot_strip_wired"


def _ttc_scan() -> tuple[str, str]:
    """R07 structural: TTC executor present; no unknown knobs on TTC path."""
    ttc = ROOT / "Data" / "modules" / "cognition" / "ttc.py"
    ctrl = ROOT / "Data" / "modules" / "cognition" / "inference_compute.py"
    adapter = ROOT / "Data" / "modules" / "cognition" / "model_adapter.py"
    if not ttc.is_file():
        return "FAIL", "missing:ttc.py"
    if not ctrl.is_file():
        return "FAIL", "missing:inference_compute.py"
    ttc_text = ttc.read_text(encoding="utf-8")
    ctrl_text = ctrl.read_text(encoding="utf-8")
    adapter_text = adapter.read_text(encoding="utf-8")
    if "class TTCExecutor" not in ttc_text:
        return "FAIL", "missing_TTCExecutor"
    if "def select_ttc_candidate" not in ttc_text:
        return "FAIL", "missing_select_ttc_candidate"
    if "async def execute_ttc" not in ctrl_text:
        return "FAIL", "controller_missing_execute_ttc"
    if "ttc_candidate_budget" not in adapter_text:
        return "FAIL", "model_adapter_missing_ttc_fanout"
    if "provider_hints=None" not in adapter_text:
        return "FAIL", "ttc_path_must_clear_provider_hints"
    return "PASS", "ttc_multi_candidate_wired"


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
    """Evaluate R01–R30. PASS requires evidence; unittest/structural checks re-verified."""
    results: list[dict[str, Any]] = []
    for gate in manifest.get("gates") or []:
        gid = str(gate.get("id") or "")
        declared = str(gate.get("status") or "NOT_STARTED").upper()
        evidence = str(gate.get("evidence") or gate.get("notes") or "—")
        check = str(gate.get("check") or "manual")
        status = declared

        if check == "unittest" and declared == "PASS":
            module = str(gate.get("module") or "")
            if not module:
                status, evidence = "FAIL", "PASS_without_unittest_module"
            else:
                status, evidence = _run_unittest(module)
                # Also enforce structural invariants for F1 authority gates.
                if status == "PASS" and gid == "R02":
                    st2, ev2 = _anti_fold_scan()
                    if st2 != "PASS":
                        status, evidence = st2, ev2
                    else:
                        evidence = f"{evidence};{ev2}"
                if status == "PASS" and gid == "R03":
                    st3, ev3 = _behavior_identity_scan()
                    if st3 != "PASS":
                        status, evidence = st3, ev3
                    else:
                        evidence = f"{evidence};{ev3}"
                if status == "PASS" and gid == "R28":
                    st2, ev2 = _anti_fold_scan()
                    if st2 != "PASS":
                        status, evidence = st2, ev2
                if status == "PASS" and gid in {"R04", "R05", "R27"}:
                    # Structural presence of two-axis types.
                    neural_path = ROOT / "Data" / "modules" / "cognition" / "neural_compute.py"
                    if not neural_path.is_file():
                        status, evidence = "FAIL", "missing:neural_compute.py"
                    else:
                        text = neural_path.read_text(encoding="utf-8")
                        if "class NeuralComputeBudget" not in text or "class ReasoningCapabilityProfile" not in text:
                            status, evidence = "FAIL", "missing_two_axis_types"
                        elif "never_guess_capability_from_model_name_alone" not in text:
                            status, evidence = "FAIL", "missing_no_name_guess_invariant"
                        else:
                            evidence = f"{evidence};neural_compute_types_ok"
                if status == "PASS" and gid == "R06":
                    st6, ev6 = _native_reasoning_scan()
                    if st6 != "PASS":
                        status, evidence = st6, ev6
                    else:
                        evidence = f"{evidence};{ev6}"
                if status == "PASS" and gid == "R07":
                    st7, ev7 = _ttc_scan()
                    if st7 != "PASS":
                        status, evidence = st7, ev7
                    else:
                        evidence = f"{evidence};{ev7}"
                if status == "PASS" and gid == "R29":
                    st29, ev29 = _cot_leakage_scan()
                    if st29 != "PASS":
                        status, evidence = st29, ev29
                    else:
                        evidence = f"{evidence};{ev29}"
        elif declared == "PASS" and evidence in {"", "—", "None", "null"}:
            status, evidence = "FAIL", "PASS_without_evidence"
        elif declared == "PASS":
            status = "PASS"
        else:
            status = (
                declared
                if declared in {"NOT_STARTED", "IN_PROGRESS", "FAIL", "NOT_TESTED"}
                else "NOT_STARTED"
            )

        results.append(
            {
                "id": gid,
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
