"""Portable coding benchmark case format (competitor-compatible).

Does not hardcode Aider/Continue logic. Cases can be exported as JSON for
external runners under fair conditions (same model, same attempt budget).
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from evals.functional.schema import ModelIdentity, finalize_outcome, new_record
from evals.functional.taxonomy import classify_campaign_failure
from evals.harness import git_start_commit

CODING_PORTABLE_VERSION = "coding_portable_v1"


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
    (root / "helper.py").write_text(
        "from app import add\ndef double_sum(a, b):\n    return add(a, b) + add(a, b)\n",
        encoding="utf-8",
    )


def _write_api(root: Path) -> None:
    (root / "api.py").write_text("def handler():\n    return {'user_name': 'x'}\n", encoding="utf-8")
    (root / "test_api.py").write_text(
        "import unittest\nfrom api import handler\n"
        "class T(unittest.TestCase):\n"
        "    def test_key(self):\n"
        "        self.assertIn('name', handler())\n",
        encoding="utf-8",
    )


def _write_concurrency(root: Path) -> None:
    (root / "worker.py").write_text(
        "import threading\n"
        "_state = {'n': 0}\n"
        "def bump():\n"
        "    # buggy: not thread-safe intentional for diagnosis tasks\n"
        "    cur = _state['n']\n"
        "    _state['n'] = cur + 1\n"
        "    return _state['n']\n",
        encoding="utf-8",
    )
    (root / "test_worker.py").write_text(
        "import unittest\nfrom worker import bump\n"
        "class T(unittest.TestCase):\n"
        "    def test_bump(self):\n"
        "        self.assertEqual(bump(), 1)\n",
        encoding="utf-8",
    )


def _hidden_add(work: Path) -> bool:
    ns: dict[str, Any] = {}
    exec((work / "app.py").read_text(encoding="utf-8"), ns)
    return ns["add"](10, 5) == 15 and ns["add"](-1, 1) == 0


def _hidden_api(work: Path) -> bool:
    ns: dict[str, Any] = {}
    exec((work / "api.py").read_text(encoding="utf-8"), ns)
    payload = ns["handler"]()
    return payload.get("name") == "x" and "user_name" not in payload


PORTABLE_CASES: list[dict[str, Any]] = [
    {
        "id": "simple_local_bug",
        "family": "simple_local_bug",
        "split": "regression",
        "prompt": "Fix add so it returns the sum of its arguments.",
        "setup": _write_add,
        "setup_kwargs": {"buggy": True},
        "visible_tests": ["test_app.py"],
        "hidden": _hidden_add,
        "max_attempts": 3,
        "time_budget_s": 120,
        "languages": ["python"],
    },
    {
        "id": "multi_file_bug",
        "family": "multi_file_bug",
        "split": "dev",
        "prompt": "Fix add used by helper.double_sum so sums are correct.",
        "setup": _write_multi,
        "setup_kwargs": {},
        "visible_tests": ["test_app.py"],
        "hidden": _hidden_add,
        "max_attempts": 3,
        "time_budget_s": 180,
        "languages": ["python"],
    },
    {
        "id": "api_contract_mismatch",
        "family": "api_contract_mismatch",
        "split": "regression",
        "prompt": "Fix handler to return key 'name' instead of 'user_name'.",
        "setup": _write_api,
        "setup_kwargs": {},
        "visible_tests": ["test_api.py"],
        "hidden": _hidden_api,
        "max_attempts": 3,
        "time_budget_s": 120,
        "languages": ["python"],
    },
    {
        "id": "test_failure_diagnosis",
        "family": "test_failure_diagnosis",
        "split": "dev",
        "prompt": "Diagnose and fix why test_add fails.",
        "setup": _write_add,
        "setup_kwargs": {"buggy": True},
        "visible_tests": ["test_app.py"],
        "hidden": _hidden_add,
        "max_attempts": 3,
        "time_budget_s": 120,
        "languages": ["python"],
    },
    {
        "id": "concurrency_lifecycle_bug",
        "family": "concurrency_lifecycle_bug",
        "split": "held_out",
        "prompt": "Make bump() safe for concurrent calls using a lock (keep single-thread tests green).",
        "setup": _write_concurrency,
        "setup_kwargs": {},
        "visible_tests": ["test_worker.py"],
        "hidden": None,  # structural — judge checks Lock presence when repaired
        "max_attempts": 3,
        "time_budget_s": 180,
        "languages": ["python"],
        "accept_lock": True,
    },
]


def export_portable_manifest() -> dict[str, Any]:
    """JSON-serializable manifest for external competitor runners."""
    cases = []
    for c in PORTABLE_CASES:
        cases.append(
            {
                "id": c["id"],
                "family": c["family"],
                "split": c["split"],
                "prompt": c["prompt"],
                "visible_tests": c["visible_tests"],
                "max_attempts": c["max_attempts"],
                "time_budget_s": c["time_budget_s"],
                "languages": c["languages"],
                "hidden_acceptance": "present" if c.get("hidden") or c.get("accept_lock") else "none",
                "notes": "Hidden checks are not provided to the solving agent.",
            }
        )
    return {
        "format": CODING_PORTABLE_VERSION,
        "fairness": {
            "same_repo_snapshot": True,
            "same_attempt_budget": True,
            "same_context_limits": "runner_configured",
            "same_base_model": "must_be_matched_externally",
        },
        "competitors_supported": ["aider", "continue", "other"],
        "cases": cases,
    }


def run_coding_portable_suite(*, use_agent: bool = True, limit: int | None = None) -> dict[str, Any]:
    """Run portable cases through HADES CodingAgent when available (fixture / no LM)."""
    started = time.time()
    sha = git_start_commit()
    cases = PORTABLE_CASES[: limit or len(PORTABLE_CASES)]
    records: list[dict[str, Any]] = []

    for case in cases:
        root = Path(tempfile.mkdtemp(prefix=f"hades_code_{case['id']}_"))
        setup: Callable[..., None] = case["setup"]
        setup(root, **(case.get("setup_kwargs") or {}))
        t0 = time.perf_counter()
        model_calls = 0
        files_touched = 0
        verified = False
        first_attempt = False
        notes = []
        outcome = "failure"

        if use_agent:
            try:
                from build_agent import BuildAgentService
                from coding_agent import CodingAgentService

                agent = CodingAgentService(BuildAgentService())
                # Deterministic path: no LM — heuristic repairs for simple add bugs.
                result = agent.run_from_goal(
                    root,
                    case["prompt"],
                    max_attempts=1,
                    auto_repair=True,
                    chat_fn=None,
                )
                if isinstance(result, dict):
                    model_calls = int(
                        (result.get("metrics") or {}).get("model_calls")
                        or result.get("model_calls")
                        or 0
                    )
                    changed = result.get("changed_files") or result.get("edits") or []
                    files_touched = len(changed) if isinstance(changed, list) else 0
                    notes.append(str(result.get("status") or result.get("summary") or "")[:200])
            except Exception as exc:  # noqa: BLE001
                notes.append(f"agent_error:{exc}")

        hidden = case.get("hidden")
        if callable(hidden):
            verified = bool(hidden(root))
        elif case.get("accept_lock"):
            text = (root / "worker.py").read_text(encoding="utf-8")
            verified = "Lock" in text or "lock" in text
            if not verified:
                # Without LM, mark blocked rather than false failure of intelligence
                outcome = "blocked"
                notes.append("BLOCKED_MODEL_UNAVAILABLE_or_no_edit")

        if verified:
            outcome = "success"
            first_attempt = True
        elif outcome != "blocked":
            # If visible unittest would pass, count partial
            try:
                import unittest

                loader = unittest.defaultTestLoader
                suite = loader.discover(str(root), pattern="test_*.py")
                res = unittest.TextTestRunner(verbosity=0).run(suite)
                if res.wasSuccessful() and hidden:
                    outcome = "partial"
                    notes.append("visible_tests_pass_hidden_fail")
            except Exception as exc:  # noqa: BLE001
                notes.append(f"test_runner:{exc}")

        tax = classify_campaign_failure(
            outcome=outcome if outcome != "blocked" else "blocked",
            family="coding",
            signals={
                "edit_failed": outcome == "failure",
                "tests_failed": outcome in {"failure", "partial"},
                "provider_unavailable": outcome == "blocked",
            },
        )
        rec = new_record(
            task_id=case["id"],
            task_family="coding",
            git_sha=sha,
            eval_layer="B_deterministic" if model_calls == 0 else "C_real_model",
            task_split=case.get("split") or "dev",
            synthetic=True,
            model=ModelIdentity(
                model_id=None,
                model_runtime="hades_coding_agent" if use_agent else "export_only",
            ),
            input={"prompt": case["prompt"], "family": case["family"]},
            ground_truth={"hidden": "callable"},
            acceptance_criteria=[f"hidden acceptance for {case['id']}"],
            result={"files_touched": files_touched, "notes": notes},
            verified_result={"verified_repair": verified, "first_attempt": first_attempt},
            outcome=outcome,
            latency_ms=round((time.perf_counter() - t0) * 1000, 3),
            model_calls=model_calls,
            failure_class=tax["failure_class"],
            notes="; ".join(notes),
        )
        if outcome == "blocked":
            rec.status = "BLOCKED_MODEL_UNAVAILABLE"
        finalize_outcome(rec)
        records.append(rec.to_dict())

    successes = sum(1 for r in records if r.get("success"))
    return {
        "suite": "coding_portable",
        "version": CODING_PORTABLE_VERSION,
        "git_sha": sha,
        "duration_seconds": round(time.time() - started, 3),
        "manifest": export_portable_manifest(),
        "metrics": {
            "verified_repair_rate": round(successes / max(1, len(records)), 4),
            "sample_size": len(records),
            "successes": successes,
            "blocked": sum(1 for r in records if r.get("outcome") == "blocked"),
        },
        "records": records,
        "honesty": [
            "Fixture success without a live model is mechanical/agent-wiring evidence only.",
            "Layer C coding quality requires a configured local model.",
        ],
    }


def write_manifest(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(export_portable_manifest(), indent=2), encoding="utf-8")
    return target
