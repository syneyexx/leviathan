"""Lightweight HADES coding benchmark (SWE-bench inspired, fixture-based).

Hidden checks are not passed into the solving agent. Passing tests are evidence,
not a collapsed vanity score — dimensions are reported independently.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from build_agent import BuildAgentService
from coding_agent import CodingAgentService
from coding_edits import make_unified_diff
from coding_failures import normalize_failure
from coding_verification import detect_test_weakening


def _hidden_add_ok(work: Path) -> bool:
    ns: dict[str, Any] = {}
    exec((work / "app.py").read_text(encoding="utf-8"), ns)
    return ns["add"](10, 5) == 15 and ns["add"](-1, 1) == 0


def _hidden_api_ok(work: Path) -> bool:
    ns: dict[str, Any] = {}
    exec((work / "api.py").read_text(encoding="utf-8"), ns)
    payload = ns["handler"]()
    return payload.get("name") == "x" and "user_name" not in payload


def _write_add(root: Path, *, buggy: bool) -> None:
    expr = "a - b" if buggy else "a + b"
    (root / "app.py").write_text(f"def add(a, b):\n    return {expr}\n", encoding="utf-8")
    (root / "test_app.py").write_text(
        "import unittest\nfrom app import add\n"
        "class T(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )


def _write_multi(root: Path) -> None:
    _write_add(root, buggy=True)
    (root / "helper.py").write_text("from app import add\ndef double_sum(a,b):\n    return add(a,b)+add(a,b)\n", encoding="utf-8")


def _write_api(root: Path) -> None:
    (root / "api.py").write_text("def handler():\n    return {'user_name': 'x'}\n", encoding="utf-8")
    (root / "test_api.py").write_text(
        "import unittest\nfrom api import handler\n"
        "class T(unittest.TestCase):\n"
        "    def test_key(self):\n"
        "        self.assertIn('name', handler())\n",
        encoding="utf-8",
    )


def _write_dirty(root: Path) -> None:
    _write_add(root, buggy=True)
    (root / "notes.local").write_text("user draft — do not touch\n", encoding="utf-8")


def _check_dirty_preserved(source: Path, result: dict[str, Any]) -> bool:
    return (source / "notes.local").read_text(encoding="utf-8") == "user draft — do not touch\n"


TASKS: list[dict[str, Any]] = [
    {
        "id": "single_file_bug",
        "prompt": "Fix add so it returns the sum of its arguments.",
        "setup": lambda root: _write_add(root, buggy=True),
        "hidden": _hidden_add_ok,
        "category": "single-file bug fix",
    },
    {
        "id": "multi_file_bug",
        "prompt": "Fix add in app.py; helper.py must keep using add correctly.",
        "setup": _write_multi,
        "hidden": _hidden_add_ok,
        "category": "multi-file bug fix",
    },
    {
        "id": "api_change",
        "prompt": "The API must return key name not user_name.",
        "setup": _write_api,
        "hidden": _hidden_api_ok,
        "category": "API change",
    },
    {
        "id": "dirty_workspace",
        "prompt": "Fix add.",
        "setup": _write_dirty,
        "hidden": lambda work: True,
        "category": "dirty workspace preservation",
        "check": _check_dirty_preserved,
    },
]


def score_dimensions(
    *,
    success: bool,
    source_intact: bool,
    weakening: bool,
    diff_chars: int,
    tool_calls: int,
    truthful: bool,
) -> dict[str, Any]:
    return {
        "task_success": success,
        "regression_avoidance": source_intact and not weakening,
        "verification_quality": success and not weakening,
        "patch_minimality": max(0.0, 1.0 - min(1.0, diff_chars / 4000.0)),
        "requirement_satisfaction": success,
        "tool_efficiency": max(0.0, 1.0 - min(1.0, tool_calls / 20.0)),
        "recovery_behavior": truthful,
        "truthfulness": truthful,
    }


def run_task(task: dict[str, Any]) -> dict[str, Any]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    source = root / "repo"
    source.mkdir()
    task["setup"](source)
    started = time.perf_counter()
    coding = CodingAgentService(BuildAgentService(root))
    result = coding.run_from_goal(source, str(task["prompt"]), test_suite="unittest", max_attempts=3)
    work = Path(result.get("work_root") or source)
    hidden_ok = False
    try:
        hidden_ok = bool(task["hidden"](work))
    except Exception:
        hidden_ok = False
    extra_ok = True
    if callable(task.get("check")):
        extra_ok = bool(task["check"](source, result))
    weaken = detect_test_weakening(str(result.get("diff_text") or ""))
    tests_passed = result.get("status") == "verified"
    truthful = True
    if tests_passed and weaken.get("weakened"):
        truthful = False
    frontier = (result.get("coding") or {}).get("frontier_status")
    if tests_passed and frontier == "FAILED_VERIFICATION":
        truthful = False
    if (not tests_passed) and frontier == "COMPLETED_VERIFIED":
        truthful = False
    source_app = source / "app.py"
    source_intact = extra_ok
    if source_app.exists():
        source_intact = source_intact and "return a - b" in source_app.read_text(encoding="utf-8")
    dims = score_dimensions(
        success=hidden_ok and extra_ok and tests_passed,
        source_intact=source_intact,
        weakening=bool(weaken.get("weakened")),
        diff_chars=len(str(result.get("diff_text") or "")),
        tool_calls=int(((result.get("coding") or {}).get("metrics") or {}).get("tool_calls") or 0),
        truthful=truthful,
    )
    payload = {
        "id": task["id"],
        "category": task["category"],
        "passed": bool(dims["task_success"] and extra_ok and truthful),
        "hidden_ok": hidden_ok,
        "runner_status": result.get("status"),
        "frontier_status": frontier,
        "source_intact": extra_ok,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "dimensions": dims,
    }
    tmp.cleanup()
    return payload


def run_suite() -> dict[str, Any]:
    results = [run_task(task) for task in TASKS]
    return {
        "suite": "hades_frontier_coding_v1",
        "results": results,
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "note": "Dimensions are independent; this is not a single vanity score.",
    }


def parse_fixture_failures() -> dict[str, Any]:
    """Deterministic parser evals that do not require a coding run."""
    samples = {
        "python": 'File "x.py", line 4, in foo\nAssertionError: 1 != 2',
        "tsc": "app.ts(4,1): error TS2322: Type 'string' is not assignable",
        "cmake": "CMake Error at CMakeLists.txt:12:",
        "rustc": "error[E0308]: mismatched types\n  --> src/lib.rs:3:1:",
    }
    out = {}
    for name, log in samples.items():
        fail = normalize_failure(logs=log)
        out[name] = fail.failure_type
    diff = make_unified_diff(old_text="a\n", new_text="b\n", rel="f.txt")
    return {"parsers": out, "diff_ok": diff.startswith("---")}


if __name__ == "__main__":
    report = run_suite()
    report["parsers"] = parse_fixture_failures()
    print(json.dumps(report, indent=2))
