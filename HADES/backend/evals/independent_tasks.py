"""Known regression fixtures E01–E08 + honesty helpers.

These tasks are **known fixtures** used for Coding Agent regression coverage.
They are NOT independent quality proof / generalization evidence. For holdout
generalization scoring use ``evals.generalization_dataset`` (generalization_v1)
and ``evals.holdout_judges``.

Dev and eval variants remain separated within each fixture factory.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any


EVAL_DATASET_VERSION = "independent_fixtures_v1"
# Back-compat alias — still the E01–E08 fixture pack, not generalization.
INDEPENDENT_EVAL_DATASET_VERSION = EVAL_DATASET_VERSION
FIXTURE_KIND = "known_regression_fixtures"
QUALITY_PROOF = False  # Explicit: E01–E08 must not be cited as independent quality proof.


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture_bad_serialization(*, variant: str = "eval") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"eval_ser_{variant}_"))
    _write(
        root / "codec.py",
        "import json\n\ndef dumps(obj):\n    # Bug: uses str() instead of json for nested types\n    return str(obj)\n\ndef loads(text):\n    return json.loads(text)\n",
    )
    _write(
        root / "test_codec.py",
        "import unittest\nfrom codec import dumps, loads\n"
        "class T(unittest.TestCase):\n"
        "    def test_roundtrip_dict(self):\n"
        "        raw = dumps({'a': 1})\n"
        "        self.assertEqual(loads(raw), {'a': 1})\n",
    )
    _write(root / "README.md", f"variant={variant}\n")
    return root


def fixture_config_not_applied(*, variant: str = "eval") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"eval_cfg_{variant}_"))
    _write(root / "config.json", json.dumps({"mode": "safe", "limit": 3}))
    _write(
        root / "app.py",
        "import json\nfrom pathlib import Path\n\n"
        "DEFAULT = {'mode': 'fast', 'limit': 99}\n\n"
        "def load_config():\n"
        "    # Bug: ignores config.json\n"
        "    return dict(DEFAULT)\n",
    )
    _write(
        root / "test_config.py",
        "import unittest\nfrom app import load_config\n"
        "class T(unittest.TestCase):\n"
        "    def test_reads_file(self):\n"
        "        cfg = load_config()\n"
        "        self.assertEqual(cfg.get('mode'), 'safe')\n"
        "        self.assertEqual(cfg.get('limit'), 3)\n",
    )
    return root


def fixture_async_race(*, variant: str = "eval") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"eval_race_{variant}_"))
    _write(
        root / "counter.py",
        "class Counter:\n"
        "    def __init__(self):\n"
        "        self.value = 0\n"
        "        self._inflight = False\n"
        "    def inc(self):\n"
        "        # Bug: concurrent callers drop increments (lost update; no Lock)\n"
        "        if self._inflight:\n"
        "            return\n"
        "        self._inflight = True\n"
        "        cur = self.value\n"
        "        self.value = cur + 1\n"
        "        self._inflight = False\n",
    )
    _write(
        root / "test_counter.py",
        "import threading\nimport unittest\nfrom pathlib import Path\nfrom counter import Counter\n"
        "class T(unittest.TestCase):\n"
        "    def test_uses_lock(self):\n"
        "        # Deterministic baseline fail: agent must add locking (GIL may mask races).\n"
        "        src = Path('counter.py').read_text(encoding='utf-8')\n"
        "        self.assertIn('threading.Lock', src)\n"
        "    def test_threaded_incs(self):\n"
        "        c = Counter()\n"
        "        def work():\n"
        "            for _ in range(200):\n"
        "                c.inc()\n"
        "        threads = [threading.Thread(target=work) for _ in range(8)]\n"
        "        for t in threads: t.start()\n"
        "        for t in threads: t.join()\n"
        "        self.assertEqual(c.value, 1600)\n",
    )
    return root


def fixture_ts_type_conflict(*, variant: str = "eval") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"eval_ts_{variant}_"))
    _write(
        root / "math_util.ts",
        "export function add(a: number, b: number): number {\n  return a - b;\n}\n",
    )
    _write(
        root / "test_math_util.py",
        "# Python stand-in judge for TS logic when tsc unavailable\n"
        "import unittest\nfrom pathlib import Path\n"
        "class T(unittest.TestCase):\n"
        "    def test_source_has_plus(self):\n"
        "        text = Path('math_util.ts').read_text(encoding='utf-8')\n"
        "        self.assertIn('return a + b', text)\n",
    )
    return root


def fixture_api_ui_inconsistency(*, variant: str = "eval") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"eval_apiui_{variant}_"))
    _write(root / "api.py", "def create_user(name):\n    return {'user_name': name}\n")
    _write(
        root / "ui.js",
        "export function label(user) {\n  return user.name; // expects API field `name`\n}\n",
    )
    _write(
        root / "test_contract.py",
        "import unittest\nfrom api import create_user\n"
        "class T(unittest.TestCase):\n"
        "    def test_api_field_matches_ui(self):\n"
        "        user = create_user('ada')\n"
        "        self.assertIn('name', user)\n"
        "        self.assertEqual(user['name'], 'ada')\n",
    )
    return root


def fixture_user_flow_bug(*, variant: str = "eval") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"eval_flow_{variant}_"))
    _write(
        root / "form.py",
        "def submit(payload):\n"
        "    # Bug: drops email\n"
        "    return {'ok': True, 'name': payload.get('name')}\n",
    )
    _write(
        root / "test_form.py",
        "import unittest\nfrom form import submit\n"
        "class T(unittest.TestCase):\n"
        "    def test_keeps_email(self):\n"
        "        out = submit({'name': 'a', 'email': 'a@x.com'})\n"
        "        self.assertEqual(out.get('email'), 'a@x.com')\n",
    )
    return root


def fixture_bad_source_ref(*, variant: str = "eval") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"eval_ref_{variant}_"))
    _write(root / "docs" / "guide.md", "See `helper.compute` for totals.\n")
    _write(root / "helper.py", "def total(a, b):\n    return a + b\n")
    _write(
        root / "test_docs.py",
        "import unittest\nfrom pathlib import Path\n"
        "class T(unittest.TestCase):\n"
        "    def test_doc_symbol_exists(self):\n"
        "        text = Path('docs/guide.md').read_text(encoding='utf-8')\n"
        "        self.assertIn('helper.total', text)\n",
    )
    return root


def fixture_context_loss_after_redirect(*, variant: str = "eval") -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"eval_ctx_{variant}_"))
    pkg = root / "svc"
    pkg.mkdir()
    _write(pkg / "__init__.py", "")
    _write(pkg / "entry.py", "from svc.hidden import run\n\ndef main(x):\n    return run(x)\n")
    _write(pkg / "hidden.py", "def run(x):\n    return x - 1\n")
    _write(
        root / "test_main.py",
        "import unittest\nfrom svc.entry import main\n"
        "class T(unittest.TestCase):\n"
        "    def test_main(self):\n"
        "        self.assertEqual(main(3), 3)\n",
    )
    return root


INDEPENDENT_TASKS: list[dict[str, Any]] = [
    {
        "id": "E01_serialization",
        "title": "Incorrect serialization",
        "fixture": fixture_bad_serialization,
        "goal": "Fix dumps/loads round-trip for dict payloads",
        "test_args": ["test_codec.py"],
        "kind": FIXTURE_KIND,
        "quality_proof": False,
        "note": "Known regression fixture — not independent quality proof.",
    },
    {
        "id": "E02_config",
        "title": "Config that does not apply",
        "fixture": fixture_config_not_applied,
        "goal": "Make load_config read config.json so mode=safe and limit=3",
        "test_args": ["test_config.py"],
        "kind": FIXTURE_KIND,
        "quality_proof": False,
        "note": "Known regression fixture — not independent quality proof.",
    },
    {
        "id": "E03_async_race",
        "title": "Async/thread race",
        "fixture": fixture_async_race,
        "goal": "Fix Counter.inc so concurrent increments are correct",
        "test_args": ["test_counter.py"],
        "kind": FIXTURE_KIND,
        "quality_proof": False,
        "note": "Known regression fixture — not independent quality proof.",
    },
    {
        "id": "E04_ts_type",
        "title": "TypeScript type/logic conflict",
        "fixture": fixture_ts_type_conflict,
        "goal": "Fix add in math_util.ts to return a + b",
        "test_args": ["test_math_util.py"],
        "kind": FIXTURE_KIND,
        "quality_proof": False,
        "note": "Known regression fixture — not independent quality proof. Prefer generalization G05 for Node runtime proof.",
    },
    {
        "id": "E05_api_ui",
        "title": "API/UI inconsistency",
        "fixture": fixture_api_ui_inconsistency,
        "goal": "Align create_user response field with UI expecting name",
        "test_args": ["test_contract.py"],
        "kind": FIXTURE_KIND,
        "quality_proof": False,
        "note": "Known regression fixture — not independent quality proof.",
    },
    {
        "id": "E06_user_flow",
        "title": "User-flow form bug",
        "fixture": fixture_user_flow_bug,
        "goal": "Preserve email when submitting the form payload",
        "test_args": ["test_form.py"],
        "kind": FIXTURE_KIND,
        "quality_proof": False,
        "note": "Known regression fixture — not independent quality proof.",
    },
    {
        "id": "E07_source_ref",
        "title": "Incorrect source reference",
        "fixture": fixture_bad_source_ref,
        "goal": "Fix docs/guide.md to reference helper.total",
        "test_args": ["test_docs.py"],
        "kind": FIXTURE_KIND,
        "quality_proof": False,
        "note": "Known regression fixture — not independent quality proof.",
    },
    {
        "id": "E08_context_redirect",
        "title": "Context loss after redirect",
        "fixture": fixture_context_loss_after_redirect,
        "goal": "Fix failing main so it returns identity; hidden impl may need edit",
        "test_args": ["test_main.py"],
        "redirect": "Look in svc/hidden.py not only entry.py",
        "kind": FIXTURE_KIND,
        "quality_proof": False,
        "note": "Known regression fixture — not independent quality proof.",
    },
]


def _run_unittest(root: Path, test_args: list[str], *, timeout: int = 30) -> dict[str, Any]:
    import subprocess
    import sys

    cmd = [sys.executable, "-m", "unittest", *test_args]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=timeout)
    return {
        "returncode": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-2000:],
    }


def verify_fixture_honesty(task: dict[str, Any], *, variant: str = "eval") -> dict[str, Any]:
    """Prove each fixture starts failing (not pre-baked green) and is runnable."""
    root = task["fixture"](variant=variant)
    test_args = list(task.get("test_args") or [])
    baseline = _run_unittest(root, test_args)
    return {
        "task_id": task["id"],
        "title": task["title"],
        "work_root": str(root),
        "baseline_tests_passed": baseline["passed"],
        "baseline_returncode": baseline["returncode"],
        "solution_prebaked": False,
        # Honesty: a green baseline means the fixture is invalid for this eval.
        "honest": baseline["passed"] is False,
        "evidence": {
            "stderr_tail": baseline["stderr"][-400:],
            "stdout_tail": baseline["stdout"][-400:],
        },
        "note": "Fixture must fail before agent work; passing baseline is a false-success risk.",
    }


def run_independent_eval_honesty_suite(*, limit: int | None = None) -> dict[str, Any]:
    """Runnable honesty gate for E01–E08 known fixtures (not quality proof)."""
    tasks = INDEPENDENT_TASKS[: limit or len(INDEPENDENT_TASKS)]
    rows = [verify_fixture_honesty(task) for task in tasks]
    honest_count = sum(1 for r in rows if r["honest"])
    return {
        "suite": "independent_fixtures_honesty_v1",
        "dataset_version": EVAL_DATASET_VERSION,
        "fixture_kind": FIXTURE_KIND,
        "quality_proof": QUALITY_PROOF,
        "task_ids": [t["id"] for t in tasks],
        "total": len(rows),
        "honest": honest_count,
        "all_fixtures_honest": honest_count == len(rows) and len(rows) > 0,
        "claimed_all_green": False,
        "scores": rows,
        "note": (
            "Per-task honesty only for known regression fixtures E01–E08. "
            "Not independent quality proof — use generalization_v1 holdout for that. "
            "This suite does not claim agent PASS/all-green."
        ),
    }


def run_independent_eval_task(
    task: dict[str, Any],
    *,
    strategy: str = "investigate",
    selector_mode: str = "deterministic",
    chat_fn: Any | None = None,
) -> dict[str, Any]:
    from build_agent import BuildAgentService
    from coding_agent import CodingAgentService

    started = time.perf_counter()
    root = task["fixture"](variant="eval")
    # Baseline evidence: task must start red.
    baseline = _run_unittest(root, list(task.get("test_args") or []))
    coding = CodingAgentService(BuildAgentService(root.parent))
    redirect_notes = []
    if task.get("redirect"):
        redirect_notes = [{"note": task["redirect"], "status": "received", "version": 1}]
    result = coding.run_from_goal(
        root,
        task["goal"],
        test_args=list(task.get("test_args") or []),
        strategy=strategy,
        selector_mode=selector_mode,
        chat_fn=chat_fn,
        redirect_notes=redirect_notes,
        max_attempts=3,
    )
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    coding_meta = result.get("coding") or {}
    status = result.get("status")
    passed = status == "verified"
    # Re-run tests as independent evidence — do not trust status alone.
    final_tests = _run_unittest(Path(result.get("work_root") or root), list(task.get("test_args") or []))
    evidence_backed = bool(passed and final_tests["passed"] and not baseline["passed"])
    return {
        "task_id": task["id"],
        "title": task["title"],
        "passed": passed and evidence_backed,
        "status": status,
        "strategy": strategy,
        "selector_mode": selector_mode,
        "duration_ms": duration_ms,
        "selected_files": (coding_meta.get("investigate") or {}).get("selected_files")
        or (coding_meta.get("explore") or {}).get("selected_files"),
        "actions": (coding_meta.get("investigate") or {}).get("action_summary"),
        "repair_attempts": len(result.get("test_results") or []),
        "model_invoked": bool((coding_meta.get("propose") or {}).get("model_invoked")),
        "dataset_version": EVAL_DATASET_VERSION,
        "solution_prebaked": False,
        "work_root": result.get("work_root"),
        "evidence": {
            "baseline_failed": not baseline["passed"],
            "final_tests_passed": final_tests["passed"],
            "result_status": status,
            "evidence_backed": evidence_backed,
        },
        "claimed_without_evidence": bool(passed and not evidence_backed),
    }


def run_independent_eval_suite(
    *,
    strategies: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    strategies = strategies or ["fast", "investigate"]
    tasks = INDEPENDENT_TASKS[: limit or len(INDEPENDENT_TASKS)]
    rows: list[dict[str, Any]] = []
    for task in tasks:
        for strategy in strategies:
            rows.append(run_independent_eval_task(task, strategy=strategy))
    passed = sum(1 for r in rows if r["passed"])
    evidence_backed = sum(1 for r in rows if (r.get("evidence") or {}).get("evidence_backed"))
    # Never advertise all-green without per-task evidence.
    all_green = passed == len(rows) and evidence_backed == len(rows) and len(rows) > 0
    return {
        "suite": "independent_fixtures_agent_v1",
        "dataset_version": EVAL_DATASET_VERSION,
        "fixture_kind": FIXTURE_KIND,
        "quality_proof": QUALITY_PROOF,
        "task_ids": [t["id"] for t in tasks],
        "total": len(rows),
        "passed": passed,
        "evidence_backed_passed": evidence_backed,
        "all_green": all_green,
        "claimed_all_green": all_green,
        "scores": rows,
        "per_task": {
            r["task_id"] + ":" + r["strategy"]: {
                "passed": r["passed"],
                "status": r["status"],
                "evidence": r.get("evidence"),
            }
            for r in rows
        },
        "note": (
            "E01–E08 known regression fixtures. Solutions are not pre-inserted; "
            "agent must investigate. Not independent quality / generalization proof. "
            "Per-task honesty required — suite does not claim all-green without evidence_backed passes."
        ),
    }


def compare_strategies_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, dict[str, Any]] = {}
    for row in rows:
        slot = by_task.setdefault(row["task_id"], {"title": row["title"], "strategies": {}})
        slot["strategies"][row["strategy"]] = {
            "passed": row["passed"],
            "duration_ms": row["duration_ms"],
            "selected_files": row.get("selected_files"),
            "actions": len(row.get("actions") or []),
            "repair_attempts": row.get("repair_attempts"),
            "model_invoked": row.get("model_invoked"),
            "evidence": row.get("evidence"),
        }
    return {
        "by_task": by_task,
        "note": "Do not generalize quality from a few easy successes; compare per task type with evidence.",
    }
