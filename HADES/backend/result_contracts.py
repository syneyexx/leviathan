"""Executable result contracts for missions and work tasks.

Separates desired outcome, current plan, and executed actions.
Exit code 0 / persuasive prose is never automatic proof of user-goal success.
"""

from __future__ import annotations

from typing import Any

from gen2.mission_control import (
    ACCEPTANCE_CHECK_TYPES,
    default_acceptance_checks,
    evaluate_acceptance_checks,
)

# Extended check types (backward-compatible union with mission_control set).
RESULT_CONTRACT_CHECK_TYPES = frozenset(ACCEPTANCE_CHECK_TYPES) | frozenset(
    {
        "content_structure",
        "test_suite_passed",
        "coverage_min",
        "claim_conflicts_visible",
        "plugin_output_and_status",
    }
)


DOMAIN_CONTRACTS: dict[str, dict[str, Any]] = {
    "coding": {
        "required_outputs": ["diff.patch", "test_results.json"],
        "checks": [
            {"type": "artifact_exists", "name": "diff.patch", "required": True, "min_bytes": 1},
            {"type": "artifact_exists", "name": "test_results.json", "required": True, "min_bytes": 1},
            {"type": "test_suite_passed", "required": True},
        ],
    },
    "research": {
        "required_outputs": ["research_report.md", "evidence_index.json"],
        "checks": [
            {"type": "artifact_exists", "name": "research_report.md", "required": True, "min_bytes": 1},
            {"type": "artifact_exists", "name": "evidence_index.json", "required": True, "min_bytes": 1},
            {"type": "claim_conflicts_visible", "required": True},
        ],
    },
    "file_processing": {
        "required_outputs": ["output.bin"],
        "checks": [
            {"type": "artifact_exists", "name": "output.bin", "required": True, "min_bytes": 1},
            {"type": "content_structure", "required": True},
        ],
    },
    "plugin_action": {
        "required_outputs": ["plugin_result.json"],
        "checks": [
            {"type": "artifact_exists", "name": "plugin_result.json", "required": True, "min_bytes": 1},
            {"type": "plugin_output_and_status", "required": True},
        ],
    },
}


def build_result_contract(
    *,
    domain: str,
    goal: str,
    required_outputs: list[str] | None = None,
    acceptance_checks: list[dict[str, Any]] | None = None,
    budgets: dict[str, Any] | None = None,
    permissions: list[str] | None = None,
    cancel_policy: dict[str, Any] | None = None,
    stop_criteria: list[str] | None = None,
    escalate_criteria: list[str] | None = None,
    inputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a typed result contract separating outcome from plan/execution."""
    domain_key = str(domain or "general").strip().lower()
    template = DOMAIN_CONTRACTS.get(domain_key, {})
    outputs = list(required_outputs or template.get("required_outputs") or [])
    checks = list(acceptance_checks or [])
    if not checks:
        base = default_acceptance_checks(domain=domain_key, artifacts=outputs)
        extra = list(template.get("checks") or [])
        # Avoid duplicating artifact_exists already emitted by default_acceptance_checks.
        existing_names = {
            str(c.get("name") or "")
            for c in base
            if isinstance(c, dict) and c.get("type") == "artifact_exists"
        }
        for check in extra:
            if check.get("type") == "artifact_exists" and str(check.get("name") or "") in existing_names:
                continue
            checks.append({**check, "id": check.get("id") or f"rc_{check.get('type')}_{len(checks)}"})
        checks = base + checks
    return {
        "contract_version": "result_contract_v1",
        "domain": domain_key,
        "desired_outcome": {
            "goal": (goal or "").strip()[:4000],
            "required_outputs": outputs,
        },
        "inputs": list(inputs or []),
        "acceptance_checks": checks,
        "permissions": list(permissions or []),
        "budgets": dict(budgets or {}),
        "cancel_policy": dict(
            cancel_policy
            or {
                "on_cancel": "stop_new_work",
                "preserve_completed": True,
                "leave_consistent_status": True,
            }
        ),
        "stop_criteria": list(stop_criteria or ["acceptance_passed", "budget_exhausted", "user_cancel"]),
        "escalate_criteria": list(
            escalate_criteria or ["permission_required", "irreconcilable_conflict", "max_replans"]
        ),
        # Plan and execution are separate layers — never rewrite history when replanning.
        "execution_plan": None,
        "executed_actions": [],
        "plan_revisions": [],
    }


def evaluate_result_contract(
    contract: dict[str, Any] | None,
    *,
    status: str,
    verification: dict[str, Any] | None = None,
    step_summary: dict[str, Any] | None = None,
    mission: dict[str, Any] | None = None,
    artifact_service: Any | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate contract checks. Missing required artifacts block completion."""
    contract = dict(contract or {})
    checks = list(contract.get("acceptance_checks") or [])
    # Split known mission_control types from extended types.
    core_checks = [c for c in checks if isinstance(c, dict) and c.get("type") in ACCEPTANCE_CHECK_TYPES]
    extended = [c for c in checks if isinstance(c, dict) and c.get("type") not in ACCEPTANCE_CHECK_TYPES]

    core = evaluate_acceptance_checks(
        core_checks,
        status=status,
        verification=verification,
        step_summary=step_summary,
        mission=mission,
        artifact_service=artifact_service,
    )
    results = list(core.get("results") or [])
    blockers = list(core.get("blockers") or [])
    extras = dict(extras or {})

    for index, raw in enumerate(extended):
        check_type = str(raw.get("type") or "")
        check_id = str(raw.get("id") or f"ext_{index}")
        required = bool(raw.get("required", True))
        passed = False
        detail = ""
        evidence: dict[str, Any] = {}

        if check_type == "test_suite_passed":
            tr = extras.get("test_results") or (verification or {}).get("test_results") or {}
            passed = bool(tr.get("passed") or tr.get("ok") or str(tr.get("status") or "").lower() == "passed")
            detail = "tests_passed" if passed else "tests_failed_or_missing"
            evidence = {"test_results": tr}

        elif check_type == "content_structure":
            structure = extras.get("content_structure") or {}
            required_keys = list(raw.get("required_keys") or structure.get("required_keys") or [])
            actual = structure.get("keys") or extras.get("output_keys") or []
            missing = [k for k in required_keys if k not in set(actual)]
            passed = not missing and (bool(actual) or not required_keys)
            if not required_keys and not actual:
                # Without declared structure, require artifact presence via other checks.
                passed = True
                detail = "structure_not_declared"
            else:
                detail = "structure_ok" if passed else f"missing_keys:{missing}"
            evidence = {"required_keys": required_keys, "actual_keys": list(actual), "missing": missing}

        elif check_type == "coverage_min":
            min_cov = float(raw.get("min") or 0.0)
            coverage = float(extras.get("coverage") or (verification or {}).get("coverage") or 0.0)
            passed = coverage >= min_cov
            detail = "coverage_ok" if passed else f"coverage_{coverage}<{min_cov}"
            evidence = {"coverage": coverage, "min": min_cov}

        elif check_type == "claim_conflicts_visible":
            conflicts = extras.get("conflicts") or []
            # Pass when conflicts are either absent or explicitly surfaced (not silently resolved).
            hidden = bool(extras.get("conflicts_silenced"))
            passed = not hidden
            detail = "conflicts_visible_or_none" if passed else "conflicts_silenced"
            evidence = {"conflict_count": len(conflicts), "silenced": hidden}

        elif check_type == "plugin_output_and_status":
            plugin = extras.get("plugin_result") or {}
            status_ok = str(plugin.get("status") or "").lower() in {"completed", "ok", "success"}
            has_output = bool(plugin.get("stdout") or plugin.get("output") or plugin.get("result"))
            passed = status_ok and has_output
            detail = "plugin_ok" if passed else "plugin_status_or_output_missing"
            evidence = {"status": plugin.get("status"), "has_output": has_output}

        else:
            passed = False
            detail = f"unknown_extended_check:{check_type}"

        results.append(
            {
                "id": check_id,
                "type": check_type,
                "passed": passed,
                "detail": detail,
                "required": required,
                "evidence": evidence,
            }
        )
        if required and not passed:
            blockers.append(f"{check_type}:{check_id}")

    # Hard rule: required artifact_exists failures always block.
    missing_artifacts = [
        r
        for r in results
        if r.get("type") == "artifact_exists" and r.get("required") and not r.get("passed")
    ]
    passed = len(blockers) == 0 and not missing_artifacts
    return {
        "passed": passed,
        "results": results,
        "blockers": blockers,
        "missing_artifacts": [r.get("id") for r in missing_artifacts],
        "contract_version": contract.get("contract_version") or "result_contract_v1",
        "may_complete": passed and str(status) == "completed",
    }


def reverify_after_artifact_fix(
    contract: dict[str, Any],
    *,
    artifact_service: Any,
    mission: dict[str, Any] | None = None,
    verification: dict[str, Any] | None = None,
    step_summary: dict[str, Any] | None = None,
    status: str = "completed",
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Targeted re-evaluation after a corrected artifact — does not rewrite history."""
    return evaluate_result_contract(
        contract,
        status=status,
        verification=verification,
        step_summary=step_summary,
        mission=mission,
        artifact_service=artifact_service,
        extras=extras,
    )
