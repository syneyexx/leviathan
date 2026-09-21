"""Milestone 1: reliable judges, investigate strategy, background coding jobs."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding_investigate import InteractiveCodingInvestigator
from coding_jobs import reset_coding_job_store_for_tests
from evals.judges import NEGATIVE_JUDGE_FIXTURES, judge_scenario, run_negative_judge_fixtures
from evals.quality_suite import (
    LIVE_QUALITY_PROMPTS,
    run_hard_benchmark,
    run_live_quality_layer,
    run_quality_suite,
)


class LiveJudgeRegressionTests(unittest.TestCase):
    def test_string_false_ok_no_longer_passes(self) -> None:
        """Regression: {\"ok\":\"false\"} used to pass via bool(\"false\") truthiness."""
        scenario = next(item for item in LIVE_QUALITY_PROMPTS if item["id"] == "structured_yes_no")
        judged = judge_scenario(scenario, '{"ok": "false"}')
        self.assertEqual(judged["verdict"], "invalid")
        self.assertFalse(judged["passed"])
        self.assertEqual(judged["raw_output"], '{"ok": "false"}')

    def test_false_success_keyword_no_longer_passes(self) -> None:
        scenario = next(item for item in LIVE_QUALITY_PROMPTS if item["id"] == "refuse_tool_invention")
        judged = judge_scenario(scenario, "false_success")
        self.assertNotEqual(judged["verdict"], "correct")
        self.assertFalse(judged["passed"])

    def test_correct_structured_and_refusal(self) -> None:
        yes = next(item for item in LIVE_QUALITY_PROMPTS if item["id"] == "structured_yes_no")
        refuse = next(item for item in LIVE_QUALITY_PROMPTS if item["id"] == "refuse_tool_invention")
        self.assertTrue(judge_scenario(yes, '{"ok": true}')["passed"])
        self.assertTrue(judge_scenario(refuse, '{"claim_success": false}')["passed"])

    def test_all_negative_fixtures_rejected(self) -> None:
        report = run_negative_judge_fixtures()
        self.assertTrue(report["passed"], report)
        self.assertGreaterEqual(len(NEGATIVE_JUDGE_FIXTURES), 5)

    def test_live_layer_stores_raw_output(self) -> None:
        async def chat_fn(payload):  # noqa: ANN001
            prompt = payload["messages"][0]["content"]
            if "2+2" in prompt:
                return {"choices": [{"message": {"content": '{"ok": "false"}'}}]}
            return {"choices": [{"message": {"content": '{"claim_success": true}'}}]}

        report = run_live_quality_layer(chat_fn=chat_fn, model_id="sim-bad")
        self.assertEqual(report["status"], "measured")
        self.assertEqual(report["passed"], 0)
        for score in report["scores"]:
            self.assertIn("raw_output", score)
            self.assertIn("verdict", score)
            self.assertFalse(score["passed"])


class QualitySuiteAdditiveTests(unittest.TestCase):
    def test_existing_scenarios_preserved_and_extended(self) -> None:
        report = run_quality_suite()
        self.assertGreaterEqual(report["total"], 42)
        self.assertEqual(report["passed"], report["total"], [s for s in report["scores"] if not s["passed"]])
        self.assertEqual(report["dataset_version"], "quality_v1.1")

    def test_hard_benchmark_layer(self) -> None:
        report = run_hard_benchmark()
        self.assertEqual(report["suite"], "hard_benchmark_v1")
        self.assertGreaterEqual(report["total"], 3)
        self.assertEqual(report["passed"], report["total"], [s for s in report["scores"] if not s["passed"]])


class InvestigateStrategyTests(unittest.TestCase):
    def _hidden_bug(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="inv_"))
        pkg = root / "service"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "handler.py").write_text(
            "from service.core_math import combine\n\ndef handle(a, b):\n    return combine(a, b)\n",
            encoding="utf-8",
        )
        (pkg / "core_math.py").write_text("def combine(a, b):\n    return a - b\n", encoding="utf-8")
        (root / "test_handler.py").write_text(
            "import unittest\nfrom service.handler import handle\n"
            "class T(unittest.TestCase):\n"
            "    def test_handle(self):\n"
            "        self.assertEqual(handle(2, 3), 5)\n",
            encoding="utf-8",
        )
        return root

    def test_investigate_finds_import_target(self) -> None:
        root = self._hidden_bug()
        report = InteractiveCodingInvestigator(root).run(
            "Fix the failing handle API",
            max_steps=12,
            test_args=["test_handler.py"],
        )
        selected = set(report["selected_files"])
        self.assertTrue(any("core_math" in p for p in selected), selected)
        kinds = [a["kind"] for a in report["action_summary"]]
        self.assertIn("gather_missing_context", kinds)
        self.assertTrue(any(a["status"] in {"ok", "empty", "error"} for a in report["action_summary"]))

    def test_investigate_coding_run_verifies(self) -> None:
        from build_agent import BuildAgentService
        from coding_agent import CodingAgentService

        root = self._hidden_bug()
        coding = CodingAgentService(BuildAgentService(root.parent))
        result = coding.run_from_goal(
            root,
            "Fix the failing handle API so tests pass",
            test_args=["test_handler.py"],
            strategy="investigate",
            max_attempts=3,
        )
        self.assertEqual(result["status"], "verified")
        investigate = (result.get("coding") or {}).get("investigate") or {}
        self.assertTrue(
            any("core_math" in str(p) for p in (investigate.get("selected_files") or [])),
            investigate.get("selected_files"),
        )

    def test_fast_strategy_still_works_classic_fixture(self) -> None:
        from build_agent import BuildAgentService
        from coding_agent import CodingAgentService

        root = Path(tempfile.mkdtemp(prefix="fast_"))
        (root / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (root / "test_app.py").write_text(
            "import unittest\nfrom app import add\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        coding = CodingAgentService(BuildAgentService(root.parent))
        result = coding.run_from_goal(root, "Repareer de fout in add", strategy="fast", max_attempts=3)
        self.assertEqual(result["status"], "verified")
        self.assertEqual((result.get("coding") or {}).get("strategy"), "fast")


class CodingJobTests(unittest.TestCase):
    def test_background_job_persist_and_cancel_contract(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)
        started = {"go": False}

        def runner(params):  # noqa: ANN001
            # Wait until cancel or short work
            for _ in range(40):
                if store.get(params["job_id"]).get("cancel_requested"):
                    raise RuntimeError("cancel_requested")
                time.sleep(0.05)
            return {"status": "verified", "id": "run_x"}

        job = store.start(runner=runner, params={"goal": "x", "source_repo": str(tmp)})
        self.assertIn(job["status"], {"queued", "running"})
        # Persist survives re-read
        snap = store.get(job["id"])
        self.assertEqual(snap["id"], job["id"])
        cancelled = store.request_cancel(job["id"])
        self.assertTrue(cancelled.get("cancel_requested"))
        for _ in range(60):
            status = store.get(job["id"]).get("status")
            if status in {"cancelled", "failed", "verified"}:
                break
            time.sleep(0.05)
        final = store.get(job["id"])
        self.assertEqual(final["status"], "cancelled")
        events = [e["kind"] for e in final.get("events") or []]
        self.assertIn("CANCEL_REQUESTED", events)

    def test_redirect_persists(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = reset_coding_job_store_for_tests(tmp)

        def runner(params):  # noqa: ANN001
            return {"status": "verified", "id": "r1"}

        job = store.start(runner=runner, params={"goal": "g", "source_repo": str(tmp)})
        store.redirect(job["id"], "also fix the helper module")
        snap = store.get(job["id"])
        self.assertTrue(any("helper" in str(n.get("note")) for n in snap.get("redirect_notes") or []))


class PreservationSmokeTests(unittest.TestCase):
    def test_live_prompts_still_two(self) -> None:
        self.assertEqual(len(LIVE_QUALITY_PROMPTS), 2)
        ids = {p["id"] for p in LIVE_QUALITY_PROMPTS}
        self.assertEqual(ids, {"structured_yes_no", "refuse_tool_invention"})

    def test_inventory_file_exists(self) -> None:
        inv = Path(__file__).resolve().parents[2] / "docs/architecture/milestone1-preservation-inventory.json"
        self.assertTrue(inv.is_file())
        data = json.loads(inv.read_text(encoding="utf-8"))
        self.assertGreaterEqual(data.get("route_count", 0), 100)


if __name__ == "__main__":
    unittest.main()
