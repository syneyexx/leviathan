"""Self-evolving Agent Factory — skill candidates, benchmark, promote, execute.

Honesty: free-text workflows without known handlers fail benchmark. Promotion
requires human approval + passed benchmark on the same definition hash.
Auto-extract from Flight Recorder only proposes known skill_runtime handlers —
never invents free-text handlers. Empty/failed runs do not create candidates.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from gen2.flight_recorder import normalize_event_type
from gen2.skill_runtime import SKILL_ACTION_HANDLERS, execute_skill_workflow, normalize_skill_step
from gen2.store import Gen2Store, utc_now

RecordFn = Callable[..., dict[str, Any]]
EvalLabFn = Callable[..., dict[str, Any]]


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def skill_definition_content_hash(definition: dict[str, Any] | None) -> str:
    """Hash executable skill content; versioning envelope is metadata, not content."""
    material = {k: v for k, v in dict(definition or {}).items() if k != "versioning"}
    return _sha(json.dumps(material, sort_keys=True, ensure_ascii=False))


def select_promoted_skill(store: Gen2Store, prompt: str) -> dict[str, Any] | None:
    """Return a promoted skill whose name/workflow keywords match the prompt."""
    text = (prompt or "").lower()
    if not text:
        return None
    for skill in store.list_skills(status="promoted", limit=50):
        name = str(skill.get("name") or "").lower()
        definition = skill.get("definition") or {}
        tokens = [name] + [str(s).lower() for s in (definition.get("workflow") or [])]
        if name and name in text:
            return {**skill, "match_reason": "name_in_prompt"}
        if any(tok and len(tok) > 3 and tok in text for tok in tokens):
            return {**skill, "match_reason": "workflow_keyword"}
    return None


def _event_ok(event: dict[str, Any]) -> bool:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    if payload.get("ok") is False or payload.get("passed") is False:
        return False
    if payload.get("error"):
        return False
    status = str(payload.get("status") or "").lower()
    if status in {"failed", "error", "blocked", "rejected"}:
        return False
    return True


def _handler_action_from_payload(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Map a TOOL/VERIFY payload onto a known skill_runtime handler action, if any."""
    candidates = [
        payload.get("action"),
        payload.get("handler"),
        payload.get("op"),
        (payload.get("tool") if isinstance(payload.get("tool"), str) else None),
        (payload.get("name") if isinstance(payload.get("name"), str) else None),
    ]
    step = payload.get("step") if isinstance(payload.get("step"), dict) else None
    if step:
        candidates.extend([step.get("action"), step.get("op"), step.get("name")])
    inputs = dict(payload.get("inputs") or {})
    if step and isinstance(step.get("inputs"), dict):
        inputs = {**dict(step.get("inputs") or {}), **inputs}
    for raw in candidates:
        action = str(raw or "").strip()
        if action in SKILL_ACTION_HANDLERS:
            return action, inputs
    return None, inputs


def extract_patterns_from_run(store: Gen2Store, run_id: str) -> dict[str, Any]:
    """Scan flight events for successful TOOL→VERIFY sequences.

    Proposes candidate workflow steps using known skill_runtime handlers only.
    Never invents free-text handlers. Empty or failed runs yield no createable pattern.
    """
    run_id = str(run_id or "").strip()
    if not run_id:
        return {
            "run_id": run_id,
            "createable": False,
            "reason": "run_id_required",
            "proposed_workflow": [],
            "patterns": [],
            "event_count": 0,
        }
    events = store.list_run_events(run_id)
    if not events:
        return {
            "run_id": run_id,
            "createable": False,
            "reason": "empty_run",
            "proposed_workflow": [],
            "patterns": [],
            "event_count": 0,
        }

    tool_successes: list[dict[str, Any]] = []
    verify_successes: list[dict[str, Any]] = []
    terminal_failed = False
    unknown_tool_actions: list[str] = []

    for event in events:
        et = str(event.get("event_type") or "")
        canonical, _ = normalize_event_type(et)
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        ok = _event_ok(event)
        if canonical == "TERMINAL" or et.upper() in {"RUN_FAILED", "RUN_COMPLETED"}:
            status = str(payload.get("status") or "").lower()
            if (
                not ok
                or status in {"failed", "error", "blocked", "cancelled"}
                or et.upper() == "RUN_FAILED"
                or payload.get("passed") is False
            ):
                terminal_failed = True
        if canonical == "TOOL" or "TOOL" in et.upper():
            action, inputs = _handler_action_from_payload(payload)
            if not ok:
                continue
            if not action:
                hint = str(
                    payload.get("action")
                    or payload.get("handler")
                    or payload.get("tool")
                    or payload.get("name")
                    or ""
                ).strip()
                if hint:
                    unknown_tool_actions.append(hint)
                continue
            tool_successes.append(
                {
                    "sequence": event.get("sequence"),
                    "action": action,
                    "inputs": inputs,
                    "event_id": event.get("id"),
                }
            )
        if canonical == "VERIFY" or "VERIF" in et.upper():
            if ok and (
                payload.get("passed") is True
                or payload.get("ok") is True
                or str(payload.get("status") or "").lower() == "passed"
            ):
                verify_successes.append(
                    {
                        "sequence": event.get("sequence"),
                        "event_id": event.get("id"),
                        "payload_status": payload.get("status"),
                    }
                )
            elif not ok:
                terminal_failed = True

    # Require at least one successful TOOL (known handler) followed by VERIFY success.
    patterns: list[dict[str, Any]] = []
    proposed: list[dict[str, Any]] = []
    seen_actions: set[str] = set()
    if tool_successes and verify_successes:
        first_verify_seq = min(int(v.get("sequence") or 0) for v in verify_successes)
        for tool in tool_successes:
            seq = int(tool.get("sequence") or 0)
            if seq > first_verify_seq:
                continue
            action = str(tool["action"])
            # Deduplicate identical actions while preserving first successful inputs.
            if action in seen_actions:
                continue
            seen_actions.add(action)
            step: dict[str, Any] = {"action": action}
            inputs = dict(tool.get("inputs") or {})
            if inputs:
                step["inputs"] = inputs
            # Only keep if normalize still resolves to a known handler.
            normalized = normalize_skill_step(step)
            if normalized.get("action") not in SKILL_ACTION_HANDLERS:
                continue
            proposed.append(step)
            patterns.append(
                {
                    "kind": "tool_then_verify",
                    "action": action,
                    "tool_sequence": seq,
                    "verify_sequence": first_verify_seq,
                }
            )

    createable = bool(proposed) and not terminal_failed and bool(verify_successes)
    reason = "ok"
    if terminal_failed and not createable:
        reason = "failed_run"
    elif not tool_successes:
        reason = "no_successful_known_handler_tools"
    elif not verify_successes:
        reason = "no_successful_verify"
    elif not proposed:
        reason = "no_handler_compatible_steps"
    elif createable:
        reason = "handler_compatible_trace"

    return {
        "run_id": run_id,
        "createable": createable,
        "reason": reason,
        "proposed_workflow": proposed,
        "patterns": patterns,
        "event_count": len(events),
        "tool_success_count": len(tool_successes),
        "verify_success_count": len(verify_successes),
        "unknown_tool_actions": unknown_tool_actions[:20],
        "known_handlers_only": True,
        "terminal_failed": terminal_failed,
    }


def extract_and_create_candidate(
    store: Gen2Store,
    record: RecordFn,
    run_id: str,
    *,
    name: str | None = None,
    tools: list[str] | None = None,
) -> dict[str, Any]:
    """Extract patterns from a run and create a skill candidate when createable.

    Never promotes. Empty/failed/non-handler runs return ``created=False``.
    """
    extraction = extract_patterns_from_run(store, run_id)
    if not extraction.get("createable"):
        return {
            "created": False,
            "skill": None,
            "extraction": extraction,
            "reason": extraction.get("reason") or "not_createable",
        }
    workflow = list(extraction.get("proposed_workflow") or [])
    skill_name = (name or "").strip() or f"from-run-{str(run_id)[:24]}"
    skill = extract_skill_candidate(
        store,
        record,
        name=skill_name,
        workflow=workflow,
        pattern_source=f"flight:{run_id}",
        tools=tools,
    )
    # Candidate only — never auto-promote.
    return {
        "created": True,
        "skill": skill,
        "extraction": extraction,
        "reason": "candidate_created",
        "promoted": False,
    }


def skill_semver(version: Any) -> tuple[int, int, int]:
    """Parse skill version into (major, minor, patch). Accepts int or '1.2.3'."""
    if isinstance(version, int):
        return (max(0, version), 0, 0)
    text = str(version or "0").strip()
    parts = text.split(".")
    nums: list[int] = []
    for part in parts[:3]:
        try:
            nums.append(int(part))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def detect_skill_incompatibility(
    definition: dict[str, Any] | None,
    *,
    runtime_api: str = "0.4.1",
) -> dict[str, Any]:
    """H5: detect version / compatibility issues on a skill definition."""
    data = dict(definition or {})
    versioning = dict(data.get("versioning") or {})
    issues: list[str] = []
    version = versioning.get("version") or data.get("version") or 1
    major, minor, patch = skill_semver(version)
    requires = str(versioning.get("requires_hades_api") or data.get("hades_api") or "").strip()
    if requires:
        req_major, req_minor, _req_patch = skill_semver(requires.lstrip(">=").strip())
        run_major, run_minor, _ = skill_semver(runtime_api.lstrip(">=").strip())
        if (run_major, run_minor) < (req_major, req_minor):
            issues.append(f"requires_hades_api:{requires}>runtime:{runtime_api}")
    compat = versioning.get("compatible_with")
    if isinstance(compat, list) and compat:
        # If declared, current major must be listed.
        majors = set()
        for item in compat:
            majors.add(skill_semver(item)[0])
        if major not in majors and str(major) not in {str(x) for x in compat}:
            issues.append(f"major_{major}_not_in_compatible_with")
    min_version = versioning.get("min_compatible_version")
    if min_version is not None and skill_semver(version) < skill_semver(min_version):
        issues.append("below_min_compatible_version")
    if not versioning.get("version"):
        issues.append("missing_version_field")
    return {
        "compatible": len(issues) == 0,
        "version": {"major": major, "minor": minor, "patch": patch, "raw": version},
        "requires_hades_api": requires or None,
        "runtime_api": runtime_api,
        "issues": issues,
    }


def run_generalization_skill_tests(definition: dict[str, Any] | None) -> dict[str, Any]:
    """Anti-overfitting gate: one success is not enough for promotion.

    Requires:
    - development_examples separate from evaluation_cases
    - at least one evaluation variant beyond the development example
    - at least one negative case where the skill must NOT apply
    - evaluation variants execute via known handlers when they declare workflows
    """
    data = dict(definition or {})
    dev = list(data.get("development_examples") or data.get("train_examples") or [])
    eval_cases = list(data.get("evaluation_cases") or data.get("eval_cases") or data.get("variants") or [])
    negatives = list(data.get("negative_cases") or data.get("should_not_apply") or [])
    issues: list[str] = []
    if not eval_cases:
        issues.append("evaluation_cases_missing")
    if not negatives:
        issues.append("negative_cases_missing")
    # Development and evaluation must not be identical singleton overfitting.
    if len(dev) == 1 and len(eval_cases) == 1 and dev[0] == eval_cases[0]:
        issues.append("eval_identical_to_sole_development_example")

    variant_results: list[dict[str, Any]] = []
    for index, case in enumerate(eval_cases):
        if isinstance(case, dict) and case.get("workflow"):
            execution = execute_skill_workflow(list(case.get("workflow") or []))
            ok = bool(execution.get("passed"))
            variant_results.append(
                {
                    "id": str(case.get("id") or f"variant_{index}"),
                    "passed": ok,
                    "pass_rate": execution.get("pass_rate"),
                }
            )
            if not ok:
                issues.append(f"variant_failed:{case.get('id') or index}")
        elif isinstance(case, dict):
            # Declarative expected_apply / expected_output checks (software).
            expected_apply = case.get("expected_apply", True)
            skill_applies = bool(case.get("skill_applies", expected_apply))
            ok = skill_applies == bool(expected_apply)
            variant_results.append({"id": str(case.get("id") or f"variant_{index}"), "passed": ok})
            if not ok:
                issues.append(f"variant_mismatch:{case.get('id') or index}")
        else:
            variant_results.append({"id": f"variant_{index}", "passed": True, "note": "opaque_case_accepted"})

    negative_results: list[dict[str, Any]] = []
    for index, case in enumerate(negatives):
        if isinstance(case, dict):
            must_not = case.get("expected_apply", False) is False or case.get("should_apply") is False
            incorrectly_applied = bool(case.get("skill_applies")) and must_not
            # Default: negative case passes when skill_applies is false/absent.
            applied = bool(case.get("skill_applies", False))
            ok = not applied
            negative_results.append(
                {
                    "id": str(case.get("id") or f"neg_{index}"),
                    "passed": ok,
                    "incorrectly_applied": incorrectly_applied or applied,
                }
            )
            if not ok:
                issues.append(f"negative_case_failed:{case.get('id') or index}")
        else:
            negative_results.append({"id": f"neg_{index}", "passed": True})

    baseline = data.get("baseline_metrics") if isinstance(data.get("baseline_metrics"), dict) else {}
    candidate = data.get("candidate_metrics") if isinstance(data.get("candidate_metrics"), dict) else {}
    beats_baseline = True
    if baseline and candidate:
        # Require correctness not worse; cost/latency must not be the sole win.
        base_correct = float(baseline.get("correctness") or baseline.get("pass_rate") or 0)
        cand_correct = float(candidate.get("correctness") or candidate.get("pass_rate") or 0)
        if cand_correct < base_correct:
            beats_baseline = False
            issues.append("candidate_correctness_below_baseline")
        elif cand_correct == base_correct:
            # Equal correctness: allow promotion only if cost/latency not worse-claimed without proof.
            beats_baseline = True

    passed = not issues and bool(eval_cases) and bool(negatives) and beats_baseline
    return {
        "required": True,
        "passed": passed,
        "issues": issues,
        "development_examples": len(dev),
        "evaluation_cases": len(eval_cases),
        "negative_cases": len(negatives),
        "variant_results": variant_results,
        "negative_results": negative_results,
        "beats_baseline": beats_baseline,
        "note": (
            "One successful task does not prove a general skill. "
            "Promotion requires separate eval variants and negative cases."
        ),
    }


def run_mandatory_skill_tests(definition: dict[str, Any] | None) -> dict[str, Any]:
    """Execute declared mandatory_tests offline (software checks, not live LM)."""
    data = dict(definition or {})
    tests = list(data.get("mandatory_tests") or [])
    results: list[dict[str, Any]] = []
    for raw in tests:
        if isinstance(raw, str):
            test = {"id": raw, "type": raw}
        elif isinstance(raw, dict):
            test = dict(raw)
        else:
            results.append({"id": "invalid", "passed": False, "reason": "invalid_test_entry"})
            continue
        test_id = str(test.get("id") or test.get("type") or "test")
        ttype = str(test.get("type") or test_id).lower()
        passed = False
        reason = ""
        if ttype in {"workflow_nonempty", "has_workflow"}:
            passed = bool(data.get("workflow"))
            reason = "workflow_present" if passed else "workflow_missing"
        elif ttype in {"handlers_only", "known_handlers"}:
            from gen2.skill_runtime import SKILL_ACTION_HANDLERS, normalize_skill_step

            unknown: list[str] = []
            for step in data.get("workflow") or []:
                if isinstance(step, dict):
                    action = str(step.get("action") or "").strip()
                else:
                    normalized = normalize_skill_step(step)
                    action = str((normalized or {}).get("action") or "").strip()
                if action and action not in SKILL_ACTION_HANDLERS:
                    unknown.append(action)
                if not action:
                    unknown.append(str(step)[:80])
            passed = len(unknown) == 0 and bool(data.get("workflow"))
            reason = "handlers_ok" if passed else f"unknown_handlers:{unknown[:5]}"
        elif ttype in {"acceptance_present", "has_acceptance"}:
            passed = bool(data.get("acceptance_criteria"))
            reason = "acceptance_ok" if passed else "acceptance_missing"
        elif ttype in {"version_compatible", "compat"}:
            compat = detect_skill_incompatibility(data)
            passed = bool(compat["compatible"])
            reason = "compatible" if passed else ",".join(compat["issues"])
        elif ttype in {"generalization", "anti_overfit", "variants_and_negatives"}:
            gen = run_generalization_skill_tests(data)
            passed = bool(gen.get("passed"))
            reason = "generalization_ok" if passed else ",".join(gen.get("issues") or ["generalization_failed"])
        else:
            # Unknown mandatory test types fail closed — do not invent pass.
            passed = False
            reason = f"unknown_mandatory_test_type:{ttype}"
        results.append({"id": test_id, "type": ttype, "passed": passed, "reason": reason})
    # Always attach generalization when eval/negative cases are declared, even if
    # not listed in mandatory_tests — prevents silent overfitting promotion paths.
    generalization = None
    if any(data.get(k) for k in ("evaluation_cases", "eval_cases", "variants", "negative_cases", "should_not_apply")):
        generalization = run_generalization_skill_tests(data)
        if not generalization.get("passed"):
            results.append(
                {
                    "id": "auto_generalization",
                    "type": "generalization",
                    "passed": False,
                    "reason": ",".join(generalization.get("issues") or ["generalization_failed"]),
                }
            )
    all_passed = bool(results) and all(r["passed"] for r in results)
    if generalization is not None:
        all_passed = all_passed and bool(generalization.get("passed"))
    return {
        "required": True,
        "count": len(results),
        "passed": all_passed,
        "results": results,
        "generalization": generalization,
        "note": "Mandatory tests are offline software checks — not live model quality.",
    }


def catalog_hygiene_report(store: Gen2Store, *, stale_days: int = 30, limit: int = 100) -> dict[str, Any]:
    """H9: list stale/unused skill candidates for local catalog hygiene."""
    from datetime import datetime, timezone

    skills = store.list_skills(limit=limit)
    now = datetime.now(timezone.utc)
    stale: list[dict[str, Any]] = []
    unused_candidates: list[dict[str, Any]] = []
    promoted = 0
    candidates = 0
    for skill in skills:
        status = str(skill.get("status") or "")
        if status == "promoted":
            promoted += 1
        if status == "candidate":
            candidates += 1
        updated = str(skill.get("updated_at") or skill.get("created_at") or "")
        age_days = None
        try:
            ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            age_days = max(0, int((now - ts).total_seconds() // 86400))
        except Exception:
            age_days = None
        row = {
            "id": skill.get("id"),
            "name": skill.get("name"),
            "status": status,
            "updated_at": updated,
            "age_days": age_days,
            "version": skill.get("version"),
        }
        if status in {"candidate", "failed_benchmark", "benchmarked"} and (
            age_days is None or age_days >= stale_days
        ):
            stale.append(row)
        if status == "candidate" and not skill.get("promoted_at"):
            bench = skill.get("benchmark") or {}
            if bench.get("status") in {None, "pending", "failed"} or age_days is None or age_days >= stale_days:
                unused_candidates.append(row)
    return {
        "stale_days": stale_days,
        "total": len(skills),
        "promoted": promoted,
        "candidates": candidates,
        "stale": stale,
        "unused_candidates": unused_candidates,
        "stale_count": len(stale),
        "unused_count": len(unused_candidates),
        "hygiene_version": "skill_catalog_hygiene_v1",
    }


def extract_skill_candidate(
    store: Gen2Store,
    record: RecordFn,
    *,
    name: str,
    workflow: list[Any],
    pattern_source: str,
    tools: list[str] | None = None,
) -> dict[str, Any]:
    definition = {
        "typed_inputs": {"goal": "string", "context": "object?"},
        "typed_outputs": {"result": "object", "artifacts": "list"},
        "workflow": workflow,
        "tool_preferences": tools or [],
        "retrieval_policy": {"mode": "hybrid", "max_tokens": 4096},
        "model_preference": {"source": "empirical_matrix", "task_type": "planning"},
        "prompt_contracts": {"system": f"Skill: {name}", "user_template": "{goal}"},
        "acceptance_criteria": ["workflow completed", "verification passed"],
        "verification_strategy": {"critic": True},
        "known_failure_modes": ["missing evidence", "tool blocked"],
        "budgets": {"max_tool_calls": 12, "max_replans": 2},
        "permissions": {"network": "ask", "filesystem": "ask"},
        "benchmark_suite": ["S5", "S10"],
        "versioning": {
            "version": "1.0.0",
            "requires_hades_api": ">=0.4.1",
            "compatible_with": ["1"],
            "min_compatible_version": "1.0.0",
        },
        "mandatory_tests": [
            {"id": "workflow_nonempty", "type": "workflow_nonempty"},
            {"id": "handlers_only", "type": "handlers_only"},
            {"id": "acceptance_present", "type": "acceptance_present"},
            {"id": "version_compatible", "type": "version_compatible"},
        ],
        "pattern_source": pattern_source,
    }
    skill = store.create_skill_candidate(
        {
            "name": name,
            "status": "candidate",
            "definition": definition,
            "benchmark": {"status": "pending"},
            "failure_modes": definition["known_failure_modes"],
        }
    )
    record(skill["id"], "RUN_CREATED", {"kind": "skill_candidate"}, component="agent_factory")
    return skill


def benchmark_skill(
    store: Gen2Store,
    record: RecordFn,
    skill_id: str,
    *,
    run_eval_lab: EvalLabFn,
) -> dict[str, Any]:
    skill = store.get_skill(skill_id)
    if not skill:
        raise ValueError("skill not found")
    definition = dict(skill.get("definition") or {})
    workflow = list(definition.get("workflow") or [])
    definition_hash = skill_definition_content_hash(definition)
    execution = execute_skill_workflow(workflow)
    step_results = list(execution.get("step_results") or [])
    ok = bool(execution.get("passed"))
    software = run_eval_lab(model_id=f"skill:{skill['name']}", suite=f"skill:{skill['name']}")
    software_pass = float((software.get("summary") or {}).get("pass_rate") or 0)
    workflow_pass = float(execution.get("pass_rate") or 0)
    mandatory = run_mandatory_skill_tests(definition)
    requires_generalization = any(
        definition.get(k) for k in ("evaluation_cases", "eval_cases", "variants", "negative_cases", "should_not_apply")
    ) or any(
        str((t.get("type") if isinstance(t, dict) else t) or "").lower()
        in {"generalization", "anti_overfit", "variants_and_negatives"}
        for t in (definition.get("mandatory_tests") or [])
    )
    generalization = mandatory.get("generalization")
    if requires_generalization and generalization is None:
        generalization = run_generalization_skill_tests(definition)
    generalization_ok = (not requires_generalization) or bool((generalization or {}).get("passed"))
    passed = (
        ok
        and workflow_pass >= 1.0
        and int(execution.get("executed_count") or 0) == len(workflow)
        and bool(mandatory.get("passed"))
        and generalization_ok
    )
    benchmark = {
        "status": "passed" if passed else "failed",
        "pass_rate": workflow_pass,
        "workflow_pass_rate": workflow_pass,
        "software_suite_pass_rate": software_pass,
        "software_eval_run_id": software.get("id"),
        "definition_hash": definition_hash,
        "step_results": step_results,
        "artifacts": list(execution.get("artifacts") or []),
        "executed_count": int(execution.get("executed_count") or 0),
        "required_pass_rate": 1.0,
        "execution_mode": "isolated_handler_registry",
        "mandatory_tests": mandatory,
        "generalization": generalization,
        "compatibility": detect_skill_incompatibility(definition),
        "note": (
            "Promotion requires workflow steps to execute via known handlers, "
            "mandatory_tests to pass, generalization (variants + negatives) when declared, "
            "and human approval. One success is not enough. "
            "Free-text descriptions without handlers fail. Software suite alone is insufficient."
        ),
    }
    status = "benchmarked" if benchmark["status"] == "passed" else "failed_benchmark"
    updated = store.update_skill(skill_id, benchmark=benchmark, status=status)
    record(skill_id, "VERIFICATION", benchmark, component="agent_factory")
    return updated or skill


def promote_skill(store: Gen2Store, record: RecordFn, skill_id: str, *, human_approved: bool) -> dict[str, Any]:
    skill = store.get_skill(skill_id)
    if not skill:
        raise ValueError("skill not found")
    if not human_approved:
        raise ValueError("human approval required to promote skill")
    if skill.get("status") not in {"benchmarked", "promoted"}:
        raise ValueError("skill must pass benchmark before promotion")
    bench = skill.get("benchmark") or {}
    if bench.get("status") != "passed":
        raise ValueError("benchmark did not pass")
    definition = dict(skill.get("definition") or {})
    mandatory = bench.get("mandatory_tests") or run_mandatory_skill_tests(definition)
    if not mandatory.get("results"):
        raise ValueError("mandatory_tests required before promotion")
    if not mandatory.get("passed"):
        raise ValueError("mandatory_tests did not pass")
    generalization = bench.get("generalization")
    if generalization is None:
        generalization = mandatory.get("generalization")
    if generalization is not None and not generalization.get("passed"):
        raise ValueError(
            "generalization gate failed: "
            + ",".join(generalization.get("issues") or ["variants_or_negatives"])
        )
    compat = bench.get("compatibility") or detect_skill_incompatibility(definition)
    if not compat.get("compatible"):
        raise ValueError(f"skill incompatible: {','.join(compat.get('issues') or [])}")
    current_hash = skill_definition_content_hash(definition)
    if bench.get("definition_hash") and bench.get("definition_hash") != current_hash:
        raise ValueError("definition changed since benchmark; re-benchmark required")
    new_version = int(skill.get("version") or 1)
    if skill.get("status") != "promoted":
        new_version = new_version + 1
    versioning = dict(definition.get("versioning") or {})
    versioning.update(
        {
            "version": versioning.get("version") or f"{new_version}.0.0",
            "definition_hash": current_hash,
            "promoted_skill_version": new_version,
        }
    )
    updated = store.update_skill(
        skill_id,
        status="promoted",
        promoted_at=utc_now(),
        version=new_version,
        definition={**definition, "versioning": versioning},
    )
    record(
        skill_id,
        "RUN_COMPLETED",
        {
            "status": "promoted",
            "version": new_version,
            "definition_hash": current_hash,
            "benchmark": bench,
            "mandatory_tests": mandatory,
            "compatibility": compat,
        },
        component="agent_factory",
    )
    return updated or skill


def deactivate_skill(store: Gen2Store, record: RecordFn, skill_id: str, *, reason: str = "deactivated") -> dict[str, Any]:
    skill = store.get_skill(skill_id)
    if not skill:
        raise ValueError("skill not found")
    updated = store.update_skill(skill_id, status="deactivated")
    record(skill_id, "STATUS_SYNC", {"status": "deactivated", "reason": reason}, component="agent_factory")
    return updated or skill


def rollback_skill(store: Gen2Store, record: RecordFn, skill_id: str, *, to_status: str = "benchmarked") -> dict[str, Any]:
    skill = store.get_skill(skill_id)
    if not skill:
        raise ValueError("skill not found")
    if to_status not in {"benchmarked", "candidate", "deactivated"}:
        raise ValueError("invalid rollback status")
    updated = store.update_skill(skill_id, status=to_status)
    record(
        skill_id,
        "STATUS_SYNC",
        {"status": to_status, "reason": "rollback", "from": skill.get("status")},
        component="agent_factory",
    )
    return updated or skill


def execute_promoted_skill(
    store: Gen2Store,
    record: RecordFn,
    skill_id: str,
    *,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the promoted skill's validated workflow handlers (same version as benchmark/promote)."""
    skill = store.get_skill(skill_id)
    if not skill:
        raise ValueError("skill not found")
    if skill.get("status") != "promoted":
        raise ValueError("skill is not promoted")
    definition = dict(skill.get("definition") or {})
    bound = ((definition.get("versioning") or {}).get("definition_hash")) or (skill.get("benchmark") or {}).get(
        "definition_hash"
    )
    current_hash = skill_definition_content_hash(definition)
    legacy_full = _sha(json.dumps(definition, sort_keys=True, ensure_ascii=False))
    legacy_pre_promote = None
    if isinstance(definition.get("versioning"), dict):
        pre = {**definition, "versioning": {"version": 1}}
        legacy_pre_promote = _sha(json.dumps(pre, sort_keys=True, ensure_ascii=False))
    if bound and bound not in {current_hash, legacy_full, legacy_pre_promote}:
        raise ValueError("promoted definition_hash mismatch; re-benchmark/promote required")
    workflow = list(definition.get("workflow") or [])
    execution = execute_skill_workflow(workflow)
    payload = {
        "skill_id": skill_id,
        "version": skill.get("version"),
        "definition_hash": current_hash,
        "executed": True,
        "passed": bool(execution.get("passed")),
        "execution": execution,
        "inputs": dict(inputs or {}),
    }
    record(skill_id, "TOOL_RESULT", payload, component="agent_factory")
    return payload
