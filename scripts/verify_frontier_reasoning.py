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


def _structured_state_scan() -> tuple[str, str]:
    """R09 structural: public structured reasoning state persist contract."""
    path = ROOT / "Data" / "modules" / "cognition" / "structured_state.py"
    runtime = ROOT / "Data" / "modules" / "cognition" / "runtime.py"
    if not path.is_file():
        return "FAIL", "missing:structured_state.py"
    text = path.read_text(encoding="utf-8")
    rt = runtime.read_text(encoding="utf-8") if runtime.is_file() else ""
    if "class StructuredReasoningState" not in text:
        return "FAIL", "missing_StructuredReasoningState"
    if "candidate_summaries" not in text:
        return "FAIL", "missing_candidate_summaries"
    if "persistable_public_contract" not in text:
        return "FAIL", "missing_persistable_public_contract_flag"
    if "no_private_cot" not in text:
        return "FAIL", "missing_no_private_cot_flag"
    if "reasoning_state" not in rt or "structured_state_from_mapping" not in rt:
        return "FAIL", "runtime_missing_reasoning_state_wire"
    if 'checkpoint["reasoning_state"]' not in rt:
        return "FAIL", "persist_missing_reasoning_state_in_result_json"
    return "PASS", "structured_reasoning_state_contract_ok"


def _neural_advisor_scan() -> tuple[str, str]:
    """R10/R11 structural: advisors validated; builders remain owners."""
    path = ROOT / "Data" / "modules" / "cognition" / "neural_advisors.py"
    task = ROOT / "Data" / "modules" / "cognition" / "task_model.py"
    planner = ROOT / "Data" / "modules" / "cognition" / "planner.py"
    if not path.is_file():
        return "FAIL", "missing:neural_advisors.py"
    text = path.read_text(encoding="utf-8")
    task_text = task.read_text(encoding="utf-8") if task.is_file() else ""
    plan_text = planner.read_text(encoding="utf-8") if planner.is_file() else ""
    if "def validate_task_advice" not in text or "def validate_plan_advice" not in text:
        return "FAIL", "missing_advice_validators"
    if "advice_is_not_task_authority" not in text:
        return "FAIL", "missing_task_advice_authority_flag"
    if "template_plan_remains_owner" not in text:
        return "FAIL", "missing_plan_owner_flag"
    if "hard_constraints" not in text or "risk_class" not in text:
        return "FAIL", "missing_forbidden_field_guards"
    if "_apply_advisor" not in task_text:
        return "FAIL", "task_builder_missing_advisor_hook"
    if "_apply_advisor" not in plan_text:
        return "FAIL", "planner_missing_advisor_hook"
    return "PASS", "neural_advisors_validated_non_owning"


def _adaptive_compute_scan() -> tuple[str, str]:
    """R08 structural: expected_gain calibration adapts neural axis."""
    path = ROOT / "Data" / "modules" / "cognition" / "adaptive_compute.py"
    meta = ROOT / "Data" / "modules" / "cognition" / "meta_controller.py"
    if not path.is_file():
        return "FAIL", "missing:adaptive_compute.py"
    text = path.read_text(encoding="utf-8")
    meta_text = meta.read_text(encoding="utf-8") if meta.is_file() else ""
    if "def calibrate_expected_gain" not in text:
        return "FAIL", "missing_calibrate_expected_gain"
    if "def adapt_neural_budget" not in text:
        return "FAIL", "missing_adapt_neural_budget"
    if "calibrated_for_neural_axis" not in text:
        return "FAIL", "missing_neural_axis_calibration_flag"
    if "calibrate_expected_gain" not in meta_text or "adapt_neural_budget" not in meta_text:
        return "FAIL", "meta_controller_missing_adaptive_wire"
    if "neural_axis_adapts_on_expected_gain" not in meta_text:
        return "FAIL", "missing_meta_decision_adaptive_truth"
    return "PASS", "adaptive_compute_neural_axis_ok"


def _hypothesis_board_scan() -> tuple[str, str]:
    """R12 structural: HypothesisBoard deep-branched and wired into runtime."""
    path = ROOT / "Data" / "modules" / "cognition" / "hypotheses.py"
    runtime = ROOT / "Data" / "modules" / "cognition" / "runtime.py"
    if not path.is_file():
        return "FAIL", "missing:hypotheses.py"
    text = path.read_text(encoding="utf-8")
    rt = runtime.read_text(encoding="utf-8") if runtime.is_file() else ""
    if "class HypothesisBoard" not in text:
        return "FAIL", "missing_HypothesisBoard"
    if "def branch" not in text:
        return "FAIL", "missing_hypothesis_branch"
    if "hypothesis_board_is_public" not in text:
        return "FAIL", "missing_public_board_truth"
    if "deep_branched" not in text:
        return "FAIL", "missing_deep_branched_flag"
    if "hypothesis_board" not in rt or "hypothesis_board_from_mapping" not in rt:
        return "FAIL", "runtime_missing_hypothesis_board_wire"
    if 'checkpoint["hypothesis_board"]' not in rt:
        return "FAIL", "persist_missing_hypothesis_board"
    return "PASS", "hypothesis_board_deep_branched_wired"


def _critic_mesh_scan() -> tuple[str, str]:
    """R13 structural: named domain CriticMesh replaces monolithic critic."""
    path = ROOT / "Data" / "modules" / "cognition" / "critic_mesh.py"
    runtime = ROOT / "Data" / "modules" / "cognition" / "runtime.py"
    if not path.is_file():
        return "FAIL", "missing:critic_mesh.py"
    text = path.read_text(encoding="utf-8")
    rt = runtime.read_text(encoding="utf-8") if runtime.is_file() else ""
    if "class CriticMesh" not in text:
        return "FAIL", "missing_CriticMesh"
    if "EvidenceCoverageCritic" not in text or "RiskGateCritic" not in text:
        return "FAIL", "missing_named_domain_critics"
    if "critic_mesh_is_named_domain_critics" not in text:
        return "FAIL", "missing_named_mesh_truth"
    if "self.critic_mesh" not in rt or "CriticMesh" not in rt:
        return "FAIL", "runtime_missing_critic_mesh"
    if "_critic_context" not in rt:
        return "FAIL", "runtime_missing_critic_context"
    return "PASS", "critic_mesh_named_domain_wired"


def _independent_verification_scan() -> tuple[str, str]:
    """R14 structural: research/file/receipt evidence + verification bridge."""
    evidence_types = ROOT / "Data" / "modules" / "evidence" / "types.py"
    service = ROOT / "Data" / "modules" / "evidence" / "service.py"
    bridge = ROOT / "Data" / "modules" / "cognition" / "verification_bridge.py"
    runtime = ROOT / "Data" / "modules" / "cognition" / "runtime.py"
    if not evidence_types.is_file():
        return "FAIL", "missing:evidence/types.py"
    if not bridge.is_file():
        return "FAIL", "missing:verification_bridge.py"
    et = evidence_types.read_text(encoding="utf-8")
    svc = service.read_text(encoding="utf-8") if service.is_file() else ""
    br = bridge.read_text(encoding="utf-8")
    rt = runtime.read_text(encoding="utf-8") if runtime.is_file() else ""
    if "CAPABILITY_RECEIPT" not in et or "RESEARCH_SOURCE" not in et:
        return "FAIL", "missing_receipt_research_evidence_kinds"
    if "claim_capability_receipt" not in svc or "claim_research_source" not in svc:
        return "FAIL", "missing_evidence_claim_helpers"
    if "build_verification_plan" not in br or "materialize_evidence_claims" not in br:
        return "FAIL", "missing_verification_bridge_api"
    if "research_and_file_receipts_covered" not in br:
        return "FAIL", "missing_receipt_coverage_truth"
    if "build_verification_plan" not in rt or "evidence_service" not in rt:
        return "FAIL", "runtime_missing_verification_bridge_wire"
    return "PASS", "independent_verification_research_file_receipts_ok"


def _capability_state_scan() -> tuple[str, str]:
    """R15 structural: cognitive CapabilityState matrix wired into runtime."""
    path = ROOT / "Data" / "modules" / "cognition" / "capability_state.py"
    runtime = ROOT / "Data" / "modules" / "cognition" / "runtime.py"
    selector = ROOT / "Data" / "modules" / "cognition" / "action_selector.py"
    if not path.is_file():
        return "FAIL", "missing:capability_state.py"
    text = path.read_text(encoding="utf-8")
    rt = runtime.read_text(encoding="utf-8") if runtime.is_file() else ""
    sel = selector.read_text(encoding="utf-8") if selector.is_file() else ""
    if "class CapabilityState" not in text:
        return "FAIL", "missing_CapabilityState"
    if "def derive_capability_state" not in text:
        return "FAIL", "missing_derive_capability_state"
    if "capability_state_is_cognition_matrix" not in text:
        return "FAIL", "missing_cognition_matrix_truth"
    if "not_provider_capability_probe" not in text:
        return "FAIL", "missing_not_provider_probe_flag"
    if "generate" not in text or "execute" not in text or "network" not in text:
        return "FAIL", "missing_matrix_axes"
    if "capability_state" not in rt or "derive_capability_state" not in rt:
        return "FAIL", "runtime_missing_capability_state_wire"
    if "_capability_block_observation" not in rt:
        return "FAIL", "runtime_missing_capability_enforcement"
    if 'checkpoint["capability_state"]' not in rt:
        return "FAIL", "persist_missing_capability_state"
    if "capability_state" not in sel:
        return "FAIL", "action_selector_missing_capability_state"
    return "PASS", "cognitive_capability_state_matrix_wired"


def _cognition_advance_scan() -> tuple[str, str]:
    """R17 structural: cognition.advance externalization + worker pool."""
    advance = ROOT / "Data" / "modules" / "cognition" / "advance.py"
    entry = ROOT / "Data" / "modules" / "workers" / "entrypoints" / "cognition.py"
    pools = ROOT / "Data" / "modules" / "workers" / "pools.py"
    builtins = ROOT / "Data" / "modules" / "execution" / "builtins.py"
    jobs = ROOT / "Data" / "modules" / "jobs" / "runtime.py"
    runtime = ROOT / "Data" / "modules" / "cognition" / "runtime.py"
    types = ROOT / "Data" / "modules" / "cognition" / "types.py"
    if not advance.is_file():
        return "FAIL", "missing:cognition/advance.py"
    if not entry.is_file():
        return "FAIL", "missing:workers/entrypoints/cognition.py"
    adv = advance.read_text(encoding="utf-8")
    pools_t = pools.read_text(encoding="utf-8") if pools.is_file() else ""
    builtins_t = builtins.read_text(encoding="utf-8") if builtins.is_file() else ""
    jobs_t = jobs.read_text(encoding="utf-8") if jobs.is_file() else ""
    rt = runtime.read_text(encoding="utf-8") if runtime.is_file() else ""
    ty = types.read_text(encoding="utf-8") if types.is_file() else ""
    if "cognition.advance" not in adv or "enqueue_cognition_advance" not in adv:
        return "FAIL", "missing_cognition_advance_api"
    if '"cognition"' not in pools_t or "cognition.advance" not in pools_t:
        return "FAIL", "missing_cognition_worker_pool"
    if 'cap_id="cognition.advance"' not in builtins_t:
        return "FAIL", "missing_cognition_advance_capability"
    if "cognition.advance" not in jobs_t:
        return "FAIL", "missing_external_worker_capability_guard"
    if "advance_external" not in rt or "enqueue_advance" not in rt:
        return "FAIL", "runtime_missing_advance_external_wire"
    if "WAITING_WORKER" not in ty:
        return "FAIL", "missing_WAITING_WORKER_status"
    if "cognition_advance_is_externalized" not in adv:
        return "FAIL", "missing_externalized_truth"
    return "PASS", "cognition_advance_worker_externalization_ok"


def _steering_resume_scan() -> tuple[str, str]:
    """R18/R19 structural: scoped steer invalidation + restart-safe resume."""
    steering = ROOT / "Data" / "modules" / "cognition" / "steering.py"
    store = ROOT / "Data" / "modules" / "cognition" / "store.py"
    runtime = ROOT / "Data" / "modules" / "cognition" / "runtime.py"
    if not steering.is_file():
        return "FAIL", "missing:steering.py"
    st = steering.read_text(encoding="utf-8")
    store_t = store.read_text(encoding="utf-8") if store.is_file() else ""
    rt = runtime.read_text(encoding="utf-8") if runtime.is_file() else ""
    if "class InvalidationScope" not in st:
        return "FAIL", "missing_InvalidationScope"
    if "invalidation_is_scoped" not in st:
        return "FAIL", "missing_scoped_invalidation_truth"
    if "def invalidation_scope_for" not in st:
        return "FAIL", "missing_invalidation_scope_for"
    if "_apply_steer_invalidation" not in rt:
        return "FAIL", "runtime_missing_steer_invalidation"
    if "pending_worker_superseded" not in rt:
        return "FAIL", "runtime_missing_pending_worker_supersede"
    if "restart_safe" not in store_t or "WAITING_WORKER" not in store_t:
        return "FAIL", "reconcile_missing_waiting_worker_preserve"
    if "resumable" not in store_t:
        return "FAIL", "reconcile_missing_resumable_flag"
    if "restart_safe_waiting_worker" not in rt:
        return "FAIL", "resume_missing_waiting_worker_path"
    return "PASS", "steering_scoped_invalidation_and_restart_safe_resume_ok"


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
                if status == "PASS" and gid == "R09":
                    st9, ev9 = _structured_state_scan()
                    if st9 != "PASS":
                        status, evidence = st9, ev9
                    else:
                        evidence = f"{evidence};{ev9}"
                if status == "PASS" and gid in {"R10", "R11"}:
                    stA, evA = _neural_advisor_scan()
                    if stA != "PASS":
                        status, evidence = stA, evA
                    else:
                        evidence = f"{evidence};{evA}"
                if status == "PASS" and gid == "R08":
                    st8, ev8 = _adaptive_compute_scan()
                    if st8 != "PASS":
                        status, evidence = st8, ev8
                    else:
                        evidence = f"{evidence};{ev8}"
                if status == "PASS" and gid == "R12":
                    st12, ev12 = _hypothesis_board_scan()
                    if st12 != "PASS":
                        status, evidence = st12, ev12
                    else:
                        evidence = f"{evidence};{ev12}"
                if status == "PASS" and gid == "R13":
                    st13, ev13 = _critic_mesh_scan()
                    if st13 != "PASS":
                        status, evidence = st13, ev13
                    else:
                        evidence = f"{evidence};{ev13}"
                if status == "PASS" and gid == "R14":
                    st14, ev14 = _independent_verification_scan()
                    if st14 != "PASS":
                        status, evidence = st14, ev14
                    else:
                        evidence = f"{evidence};{ev14}"
                if status == "PASS" and gid == "R15":
                    st15, ev15 = _capability_state_scan()
                    if st15 != "PASS":
                        status, evidence = st15, ev15
                    else:
                        evidence = f"{evidence};{ev15}"
                if status == "PASS" and gid == "R17":
                    st17, ev17 = _cognition_advance_scan()
                    if st17 != "PASS":
                        status, evidence = st17, ev17
                    else:
                        evidence = f"{evidence};{ev17}"
                if status == "PASS" and gid in {"R18", "R19"}:
                    stSR, evSR = _steering_resume_scan()
                    if stSR != "PASS":
                        status, evidence = stSR, evSR
                    else:
                        evidence = f"{evidence};{evSR}"
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
