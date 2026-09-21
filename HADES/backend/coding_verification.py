"""Test impact analysis, verification matrix, and stronger test-weakening detection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

VERIFICATION_CATEGORIES = (
    "syntax",
    "type_check",
    "lint",
    "unit",
    "integration",
    "build",
    "native",
    "api_contract",
    "database_migration",
    "security",
    "ui_flow",
    "runtime_smoke",
    "regression",
)

_SKIP_MARKERS = (
    r"@unittest\.skip",
    r"pytest\.mark\.skip",
    r"skip\s*=\s*True",
    r"xit\(",
    r"xdescribe\(",
    r"it\.skip\(",
    r"describe\.skip\(",
    r"@Ignore\b",
    r"self\.skipTest\(",
)
_WEAK_ASSERT = (
    r"assert\s+True\b",
    r"assert True\b",
    r"self\.assertTrue\(\s*True\s*\)",
    r"pytest\.fail\s*=",
    r"pass\s*#\s*(?:skip|later|todo)",
)
_CATCHALL = (
    r"except\s+Exception\s*:\s*(?:pass|return)",
    r"except\s*:\s*pass",
    r"catch\s*\(\s*Exception\s+\w*\s*\)\s*\{\s*\}",
)


def plan_verification_matrix(
    *,
    changed_files: list[str],
    languages: list[str] | None = None,
    build_systems: list[str] | None = None,
    risk_level: str = "medium",
    task_type: str = "bugfix",
) -> dict[str, Any]:
    files = [p.replace("\\", "/") for p in changed_files]
    langs = set(languages or [])
    builds = set(build_systems or [])
    cats: list[dict[str, Any]] = []

    def add(category: str, reason: str, *, required: bool = False, suite: str | None = None) -> None:
        cats.append({"category": category, "reason": reason, "required": required, "suite": suite, "status": "planned"})

    py = any(p.endswith(".py") for p in files) or "python" in langs
    ts = any(p.endswith((".ts", ".tsx", ".js", ".jsx")) for p in files) or "typescript" in langs
    native = any(p.endswith((".c", ".cc", ".cpp", ".h", ".hpp")) for p in files) or "cpp" in langs or "c" in langs
    if py:
        add("syntax", "Python sources changed", required=True, suite="unittest")
        add("unit", "Python unit tests", required=True, suite="unittest")
        if "pytest" in builds:
            add("unit", "pytest configured", required=False, suite="pytest")
        add("lint", "ruff if installed", required=False, suite="ruff")
        add("type_check", "mypy if installed", required=False, suite="mypy")
    if ts:
        add("type_check", "TypeScript/JS sources changed", required=False, suite="tsc")
        add("lint", "frontend lint if configured", required=False)
        add("unit", "frontend unit tests", required=False, suite="npm_test")
        add("build", "frontend build is not implied by tsc", required=False)
        add("ui_flow", "UI correctness is not proven by compilation", required=False)
    if native or "cmake" in builds:
        add("native", "C/C++ or CMake project", required=False, suite="ctest")
        add("build", "native compilation", required=risk_level == "high")
    if any("migrat" in p.lower() or "schema" in p.lower() for p in files) or task_type in {"database_migration"}:
        add("database_migration", "persistence/schema files changed", required=True)
    if any(re.search(r"route|api|openapi|schema", p, re.I) for p in files):
        add("api_contract", "public contract surface may have changed", required=True)
    if any(re.search(r"auth|policy|permission|exec|shell|plugin", p, re.I) for p in files):
        add("security", "trust-boundary files changed", required=True)
    if risk_level in {"high", "critical"}:
        add("regression", "high-risk change needs broader tests", required=True)
    else:
        add("regression", "broader suite optional unless foundational", required=False)

    # Always keep unit verification when any tests exist conceptually.
    if not any(c["category"] == "unit" for c in cats):
        add("unit", "default executable check", required=True, suite="unittest")

    return {
        "risk_level": risk_level,
        "categories": cats,
        "required": [c["category"] for c in cats if c["required"]],
        "optional": [c["category"] for c in cats if not c["required"]],
        "note": "Passing tests are evidence, not proof. Categories not run stay unverified.",
    }


def select_impacted_tests(
    *,
    changed_files: list[str],
    index: dict[str, Any] | None = None,
    named_tests: list[str] | None = None,
    historical_failures: list[str] | None = None,
) -> dict[str, Any]:
    from repo_intelligence import tests_covering

    changed = [p.replace("\\", "/") for p in changed_files]
    selected: list[str] = list(named_tests or [])
    method = "name_and_graph"
    if index:
        selected.extend(tests_covering(index, changed))
    for path in changed:
        stem = Path(path).stem
        if not stem:
            continue
        # Conventional mirrors: test_foo.py for foo.py
        selected.append(f"test_{stem}.py")
        selected.append(f"{stem}_test.py")
        selected.append(f"{stem}.test.ts")
        selected.append(f"{stem}.test.js")
    selected.extend(historical_failures or [])
    # Keep only unique relative-looking names; actual existence is checked by caller.
    unique = list(dict.fromkeys(p.replace("\\", "/") for p in selected if p))
    return {
        "tests": unique,
        "method": method,
        "changed_files": changed,
        "sequence": ["syntax", "direct_tests", "subsystem", "regression"],
        "note": "Do not treat missing optional tests as success.",
    }


def detect_test_weakening(diff_text: str) -> dict[str, Any]:
    """Stronger than a single regex. Suspicious ≠ malicious; justification still required."""
    diff = diff_text or ""
    findings: list[dict[str, Any]] = []

    removed_defs = len(re.findall(r"^\-\s*(?:def|async def) test_", diff, re.M))
    added_defs = len(re.findall(r"^\+\s*(?:def|async def) test_", diff, re.M))
    if removed_defs > added_defs:
        findings.append({"code": "removed_tests", "severity": "critical", "detail": f"removed={removed_defs} added={added_defs}"})

    removed_asserts = len(re.findall(r"^\-\s*(?:self\.)?assert", diff, re.M))
    added_asserts = len(re.findall(r"^\+\s*(?:self\.)?assert", diff, re.M))
    if removed_asserts > added_asserts + 1:
        findings.append({"code": "removed_assertions", "severity": "high", "detail": f"removed={removed_asserts} added={added_asserts}"})

    for pat in _SKIP_MARKERS:
        if re.search(rf"^\+.*(?:{pat})", diff, re.M):
            findings.append({"code": "skip_marker_added", "severity": "critical", "detail": pat})
            break

    if re.search(r"^\+.*(?:pytest\.mark\.xfail|unittest\.expectedFailure)", diff, re.M):
        findings.append({"code": "expected_failure_added", "severity": "high", "detail": "xfail/expectedFailure added"})

    for pat in _WEAK_ASSERT:
        if re.search(rf"^\+.*{pat}", diff, re.M):
            findings.append({"code": "weak_assertion", "severity": "medium", "detail": pat})

    for pat in _CATCHALL:
        if re.search(rf"^\+.*{pat}", diff, re.M):
            findings.append({"code": "swallowed_error", "severity": "high", "detail": pat})

    if re.search(r"^\+.*timeout\s*=\s*(?:0|0\.0|1)\b", diff, re.M) and re.search(r"^\-.*timeout\s*=", diff, re.M):
        findings.append({"code": "timeout_reduced", "severity": "medium", "detail": "timeout lowered; may bypass behavior"})

    if re.search(r"^\+.*(?:MagicMock|mock\.|monkeypatch|jest\.fn)", diff, re.M) and re.search(r"test", diff, re.I):
        findings.append(
            {
                "code": "mock_added",
                "severity": "medium",
                "detail": "New mocks in tests; verify the feature under test is not mocked away.",
                "not_automatically_malicious": True,
            }
        )

    critical = [f for f in findings if f["severity"] == "critical"]
    return {
        "weakened": bool(critical) or any(f["severity"] == "high" for f in findings),
        "findings": findings,
        "requires_justification": bool(findings),
        "note": "Legitimate contract changes may modify tests; require requirement traceability.",
    }


def judge_verification_quality(
    *,
    test_results: list[dict[str, Any]],
    changed_files: list[str],
    weakening: dict[str, Any] | None = None,
    matrix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    executed = [t for t in test_results if t.get("executed") or t.get("status") in {"passed", "failed"}]
    passed = [t for t in executed if t.get("status") == "passed" or t.get("passed") is True]
    failed = [t for t in executed if t.get("status") == "failed" or t.get("passed") is False]
    cmd_blob = " ".join(" ".join(str(x) for x in (t.get("command") or [])) for t in executed)
    suite_blob = " ".join(str(t.get("suite") or "") for t in executed).lower()
    exercised = any(Path(p).name.split(".")[0] in cmd_blob or p in cmd_blob for p in changed_files)
    required_missing = []
    ran_cats = {str(t.get("category") or t.get("suite") or "") for t in executed}
    if executed and ("unittest" in suite_blob or "pytest" in suite_blob or "unittest" in ran_cats or "pytest" in ran_cats):
        ran_cats.update({"syntax", "unit"})
    if matrix:
        for cat in matrix.get("required") or []:
            if cat in ran_cats:
                continue
            if any(cat in str(t) for t in executed):
                continue
            required_missing.append(cat)
    weakened = bool((weakening or {}).get("weakened"))
    tests_passed = bool(passed) and not failed
    return {
        "tests_passed": tests_passed,
        "correct_tests_ran": bool(executed),
        "changed_code_likely_exercised": exercised or not changed_files,
        "tests_weakened": weakened,
        "required_categories_missing": required_missing,
        "proof": False,
        "status": (
            "failed"
            if failed or weakened
            else "partial"
            if tests_passed and required_missing
            else "passed_evidence"
            if tests_passed
            else "unverified"
        ),
        "note": "Passing tests are evidence, not proof of correctness.",
    }
