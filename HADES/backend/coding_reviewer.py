"""Independent coding reviewer — goal + diff + tests → concrete defects (Phase E4).

Does not replace executable tests; scores a structured review checklist.
"""

from __future__ import annotations

import re
from typing import Any


def review_coding_result(
    *,
    goal: str,
    diff_text: str | None = None,
    changed_files: list[str] | None = None,
    test_result: dict[str, Any] | None = None,
    propose_meta: dict[str, Any] | None = None,
    suggest_extra_checks: bool = False,
) -> dict[str, Any]:
    goal_clean = (goal or "").strip()
    diff = diff_text or ""
    files = list(changed_files or [])
    test = dict(test_result or {})
    defects: list[dict[str, Any]] = []
    criteria: list[dict[str, Any]] = []
    extra_checks: list[dict[str, Any]] = []

    criteria.append(
        {
            "id": "goal_present",
            "passed": bool(goal_clean),
            "detail": "goal recorded" if goal_clean else "missing goal",
        }
    )
    if not goal_clean:
        defects.append({"severity": "high", "code": "missing_goal", "message": "No goal recorded for review."})

    criteria.append(
        {
            "id": "diff_or_files",
            "passed": bool(diff.strip()) or bool(files),
            "detail": f"files={len(files)} diff_chars={len(diff)}",
        }
    )
    if not diff.strip() and not files:
        defects.append(
            {
                "severity": "high",
                "code": "empty_change_set",
                "message": "No diff or changed files for the stated goal.",
            }
        )

    # Refuse weakening tests — deterministic detector (regex + assertion/skip/mock heuristics).
    weaken = bool(re.search(r"^\-\s*(def test_|async def test_)", diff, re.M)) or bool(
        re.search(r"skip\s*=\s*True|@unittest\.skip|pytest\.mark\.skip", diff, re.I)
    )
    weaken_report: dict[str, Any] = {}
    try:
        from coding_verification import detect_test_weakening

        weaken_report = detect_test_weakening(diff)
        weaken = weaken or bool(weaken_report.get("weakened"))
    except Exception:
        weaken_report = {}
    criteria.append({"id": "tests_not_weakened", "passed": not weaken, "detail": "ok" if not weaken else "weakened"})
    if weaken:
        defects.append(
            {
                "severity": "critical",
                "code": "tests_weakened",
                "message": "Diff appears to remove or skip tests to go green.",
                "evidence": weaken_report.get("findings") or [],
            }
        )

    status = str(test.get("status") or test.get("result") or "").lower()
    passed_tests = status in {"passed", "ok", "success", "completed"} or test.get("passed") is True
    failed_tests = status in {"failed", "error"} or test.get("passed") is False
    criteria.append(
        {
            "id": "tests_executed",
            "passed": bool(test),
            "detail": status or ("present" if test else "missing"),
        }
    )
    if not test:
        defects.append(
            {
                "severity": "medium",
                "code": "tests_not_run",
                "message": "No test result attached; executable verification missing.",
            }
        )
    elif failed_tests:
        defects.append(
            {
                "severity": "high",
                "code": "tests_failed",
                "message": "Attached tests did not pass.",
            }
        )

    # Goal keyword coverage in diff/files (heuristic signal only).
    tokens = [t for t in re.findall(r"[a-zA-Z_]{4,}", goal_clean.lower()) if t not in {"fix", "repareer", "repair", "this", "that", "with", "from"}]
    blob = f"{diff}\n{' '.join(files)}".lower()
    hit = sum(1 for t in tokens[:8] if t in blob)
    coverage = (hit / max(1, min(8, len(tokens)))) if tokens else 1.0
    criteria.append(
        {
            "id": "goal_token_coverage",
            "passed": coverage >= 0.25 or not tokens,
            "detail": f"coverage={coverage:.2f}",
        }
    )
    if tokens and coverage < 0.25:
        defects.append(
            {
                "severity": "medium",
                "code": "low_goal_alignment",
                "message": "Diff/files share few tokens with the stated goal.",
            }
        )

    propose = dict(propose_meta or {})
    if propose.get("repeat_detected"):
        defects.append(
            {
                "severity": "medium",
                "code": "repeat_repair",
                "message": "Identical repair patches were detected; approach should change or stop honestly.",
            }
        )

    # Deterministic architecture / safety signals (suspicion until proven by tests).
    if re.search(r"shell\s*=\s*True", diff):
        defects.append(
            {
                "severity": "high",
                "code": "unsafe_shell",
                "message": "Diff enables shell=True; policy-controlled subprocesses must stay fail-closed.",
            }
        )
    if re.search(r"(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]+['\"]", diff, re.I):
        defects.append(
            {
                "severity": "high",
                "code": "credential_literal",
                "message": "Diff appears to introduce a credential literal.",
            }
        )
    if re.search(r"^\+\s*except Exception:\s*$", diff, re.M) and re.search(r"^\+\s+pass\s*$", diff, re.M):
        defects.append(
            {
                "severity": "medium",
                "code": "swallowed_exception",
                "message": "New catch-all Exception/pass may hide failures.",
            }
        )
    if any(p.endswith((".sql",)) or "migrat" in p.lower() or "schema" in p.lower() for p in files):
        extra_checks.append(
            {
                "id": "persistence_durability",
                "suspicion": "Persistence/schema change is not proven by a passing unit test alone",
                "proposed_test": "Migration rollback + concurrent access + partial-failure checks",
                "status": "suggested_not_proven",
            }
        )

    # Suggest additional checks for edge cases — not proven defects until executed.
    if suggest_extra_checks:
        if passed_tests and ("serialize" in goal_clean.lower() or "json" in blob or "dict" in blob):
            extra_checks.append(
                {
                    "id": "edge_empty_payload",
                    "suspicion": "Serialization edge case (empty/None payload) may still fail",
                    "proposed_test": "Assert round-trip for empty dict / None / missing keys",
                    "status": "suggested_not_proven",
                }
            )
        if passed_tests and any(x in goal_clean.lower() for x in ("async", "race", "concurrent", "timeout")):
            extra_checks.append(
                {
                    "id": "edge_async_race",
                    "suspicion": "Async/race edge may pass single-threaded tests but fail under concurrency",
                    "proposed_test": "Run concurrent callers against shared state",
                    "status": "suggested_not_proven",
                }
            )
        if passed_tests and any(f.endswith((".ts", ".tsx", ".js", ".jsx")) for f in files):
            extra_checks.append(
                {
                    "id": "edge_type_narrowing",
                    "suspicion": "TypeScript/JS type narrowing edge cases may escape unit tests",
                    "proposed_test": "tsc --noEmit + null/undefined caller paths",
                    "status": "suggested_not_proven",
                }
            )
        if passed_tests and any(x in goal_clean.lower() for x in ("ui", "form", "button", "browser", "click")):
            extra_checks.append(
                {
                    "id": "edge_user_flow",
                    "suspicion": "UI change may pass unit tests without exercising the user flow",
                    "proposed_test": "Fill form → activate control → assert visible result + console errors",
                    "status": "suggested_not_proven",
                }
            )
        # Only elevate to proven defect when evidence warrants (e.g. weakened tests already critical).

    # Guard: suggestions must never be silently promoted into proven defects.
    suggestion_ids = {c.get("id") for c in extra_checks}
    proven_defects: list[dict[str, Any]] = []
    for defect in defects:
        if defect.get("code") in suggestion_ids or defect.get("from_suggestion"):
            continue
        proven_defects.append(defect)
    critical = [d for d in proven_defects if d["severity"] == "critical"]
    high = [d for d in proven_defects if d["severity"] == "high"]
    overall = "reject" if critical or (high and failed_tests) else "needs_attention" if proven_defects else "accept"
    return {
        "status": overall,
        "defects": proven_defects,
        "criteria": criteria,
        "passed_criteria": sum(1 for c in criteria if c["passed"]),
        "total_criteria": len(criteria),
        "tests_passed": bool(passed_tests),
        "extra_checks": extra_checks,
        "suggestions_are_not_proof": True,
        "method": "independent_checklist_heuristic",
        "note": "Reviewer complements executable tests; model suggestions are not proven defects until checked.",
        "compliment_forbidden": True,
        "test_weakening": weaken_report,
        "generation_independent": True,
    }
