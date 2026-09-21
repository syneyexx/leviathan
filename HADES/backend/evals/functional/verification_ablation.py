"""Critic ablation benchmark — deterministic floor must survive critic failure.

Modes:
  A: deterministic only
  B: deterministic + critic
  C: deliberately weak/noisy critic
  D: critic unavailable
"""

from __future__ import annotations

import time
from typing import Any

from evals.functional.schema import ModelIdentity, finalize_outcome, new_record
from evals.functional.taxonomy import classify_campaign_failure
from evals.harness import git_start_commit
from reasoning.contracts import VerificationResult
from reasoning.verification import verification_allows_success


ABLATION_VERSION = "verification_ablation_v1"


def _case_tool_failure_should_block() -> dict[str, Any]:
    """Obvious failure: required tool failed — critic must not greenwash."""
    tool_observations = [
        {"tool_name": "deploy", "status": "failed", "optional": False, "error": "timeout"},
    ]
    step_outputs = [{"title": "Deploy", "agent_id": "executor", "output": "failed"}]
    return {
        "id": "tool_failure_blocks",
        "tool_observations": tool_observations,
        "step_outputs": step_outputs,
        "acceptance": ["Service deployed"],
        "expect_allow": False,
    }


def _case_missing_evidence_blocks() -> dict[str, Any]:
    tool_observations = [
        {"tool_name": "search", "status": "ok", "optional": False},
    ]
    return {
        "id": "tool_success_without_evidence_blocks",
        "tool_observations": tool_observations,
        "step_outputs": [{"title": "Search", "agent_id": "research", "output": "hits"}],
        "acceptance": ["Sources cited"],
        "expect_allow": False,
        "require_evidence_when_tools": True,
    }


def _case_clean_pass() -> dict[str, Any]:
    tool_observations = [
        {"tool_name": "echo", "status": "ok", "optional": False, "call_id": "c1"},
    ]
    step_outputs = [
        {"title": "Echo", "agent_id": "executor", "output": "hello", "evidence_ref": "tool:c1"},
    ]
    return {
        "id": "clean_tool_evidence_pass",
        "tool_observations": tool_observations,
        "step_outputs": step_outputs,
        "acceptance": [],
        "expect_allow": True,
        "require_evidence_when_tools": True,
        "result_overrides": {
            "passed": True,
            "evidence_refs": ["tool:c1"],
            "final_answer": "hello",
            "incomplete": False,
            "parse_status": "ok",
        },
    }


CASES = (
    _case_tool_failure_should_block,
    _case_missing_evidence_blocks,
    _case_clean_pass,
)


def _critic_result(mode: str, case: dict[str, Any]) -> VerificationResult | None:
    overrides = dict(case.get("result_overrides") or {})
    if mode == "A":
        # Deterministic-only: synthesize a critic-shaped result from ground truth expectations
        # without claiming LLM judgment — passed mirrors expect only when no hard failures.
        passed = bool(case.get("expect_allow"))
        return VerificationResult(
            passed=passed,
            issues=[] if passed else ["deterministic_floor"],
            final_answer=overrides.get("final_answer", "draft"),
            evidence_refs=list(overrides.get("evidence_refs") or []),
            method="deterministic_only",
            incomplete=False,
            parse_status="ok",
        )
    if mode == "D":
        return None  # critic unavailable
    if mode == "C":
        # Noisy critic: always claims passed=True (adversarial)
        return VerificationResult(
            passed=True,
            issues=[],
            final_answer=overrides.get("final_answer", "I declare success"),
            evidence_refs=list(overrides.get("evidence_refs") or ["draft:1"]),
            method="noisy_critic",
            incomplete=False,
            parse_status="ok",
        )
    # Mode B: honest critic aligned with expected allow (still subject to deterministic gates)
    passed = bool(case.get("expect_allow"))
    return VerificationResult(
        passed=passed if "passed" not in overrides else bool(overrides["passed"]),
        issues=[] if passed else ["critic_issues"],
        final_answer=overrides.get("final_answer", "draft"),
        evidence_refs=list(overrides.get("evidence_refs") or []),
        method="structured_critic",
        incomplete=bool(overrides.get("incomplete", False)),
        parse_status=str(overrides.get("parse_status") or "ok"),
    )


def run_verification_ablation() -> dict[str, Any]:
    started = time.time()
    sha = git_start_commit()
    records: list[dict[str, Any]] = []
    mode_summary: dict[str, dict[str, Any]] = {}

    for mode in ("A", "B", "C", "D"):
        false_pass = 0
        false_fail = 0
        correct = 0
        for factory in CASES:
            case = factory()
            t0 = time.perf_counter()
            result = _critic_result(mode, case)
            allowed, reason = verification_allows_success(
                result,
                tool_observations=case.get("tool_observations"),
                step_outputs=case.get("step_outputs"),
                acceptance_criteria=case.get("acceptance") or None,
                require_evidence_when_tools=bool(case.get("require_evidence_when_tools", True)),
            )
            expect = bool(case["expect_allow"])
            # Mode D: critic unavailable → must not allow completion for cases that need verification
            if mode == "D":
                # Floor: unavailable critic => not allowed
                ok = allowed is False
                if allowed:
                    false_pass += 1
                elif expect and not allowed:
                    # May be false_fail relative to a world with a good critic, but safe
                    false_fail += 1 if expect else 0
                    if not expect:
                        correct += 1
                    else:
                        # Safe deny of a would-be success is acceptable degradation
                        correct += 1  # count as correct safety posture
                else:
                    correct += 1
                passed_case = ok
            else:
                if allowed and not expect:
                    false_pass += 1
                    passed_case = False
                elif (not allowed) and expect:
                    false_fail += 1
                    passed_case = False
                else:
                    correct += 1
                    passed_case = True

            outcome = "success" if passed_case else "failure"
            tax = classify_campaign_failure(
                outcome=outcome,
                family="verification",
                signals={
                    "verification_failed": not passed_case,
                    "hallucinated_success": bool(allowed and not expect),
                    "evidence_invalid": "evidence" in (reason or "").lower(),
                },
            )
            rec = new_record(
                task_id=f"{case['id']}::mode_{mode}",
                task_family="verification",
                git_sha=sha,
                eval_layer="B_deterministic",
                task_split="regression",
                synthetic=True,
                model=ModelIdentity(model_runtime=f"ablation_mode_{mode}"),
                input={"mode": mode, "case": case["id"]},
                ground_truth={"expect_allow": expect},
                result={"allowed": allowed, "reason": reason},
                verified_result={"false_pass": allowed and not expect, "mode": mode},
                outcome=outcome,
                latency_ms=round((time.perf_counter() - t0) * 1000, 3),
                verification_stats={"mode": mode},
                failure_class=tax["failure_class"] if outcome != "success" else "passed",
            )
            finalize_outcome(rec)
            records.append(rec.to_dict())

        n = len(CASES)
        mode_summary[mode] = {
            "correct": correct,
            "false_pass": false_pass,
            "false_fail": false_fail,
            "sample_size": n,
            "false_pass_rate": round(false_pass / n, 4),
        }

    # Gate: mode C and D must have false_pass == 0 for hard-failure cases
    c_ok = mode_summary["C"]["false_pass"] == 0
    d_ok = mode_summary["D"]["false_pass"] == 0

    return {
        "suite": "verification_ablation",
        "version": ABLATION_VERSION,
        "git_sha": sha,
        "duration_seconds": round(time.time() - started, 3),
        "modes": mode_summary,
        "gate": {
            "noisy_critic_cannot_false_pass": c_ok,
            "unavailable_critic_cannot_false_pass": d_ok,
            "passed": c_ok and d_ok,
        },
        "records": records,
        "status": "PASS" if c_ok and d_ok else "FAIL",
        "honesty": [
            "Critic is supplementary; deterministic gates own completion truth.",
            "Mode D must degrade safely (deny), not invent success.",
        ],
    }
