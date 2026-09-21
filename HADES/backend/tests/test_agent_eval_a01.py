"""A01 production-route agent eval harness tests.

Fake/stub production route callback proves the real route entrypoint is called
without harness solution injection.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.agent_eval import (
    aggregate_agent_metrics,
    run_agent_eval,
    run_agent_task_layer,
    run_software_layer,
)
from evals.agent_judges import assert_grader_outside_workspace, judge_agent_task
from evals.agent_tasks import (
    AGENT_TASKS,
    AGENT_TASKS_DATASET_VERSION,
    agent_categories_covered,
    combined_corpus_stats,
    list_agent_holdout_tasks,
)
from evals.production_route import (
    PRODUCTION_ROUTE_ID,
    PRODUCTION_STAGES,
    ProductionRouteRequest,
    invoke_production_route,
    probe_lm_studio,
)
from evals.release_thresholds import THRESHOLD_VERSION, evaluate_thresholds


class AgentCorpusTests(unittest.TestCase):
    def test_corpus_size_and_categories(self) -> None:
        stats = combined_corpus_stats()
        self.assertGreaterEqual(stats["total_tasks"], 30)
        self.assertLessEqual(stats["total_tasks"], 50)
        self.assertGreaterEqual(stats["holdout_count"], 30)
        cats = agent_categories_covered()
        for required in (
            "python",
            "docs_research",
            "tool_use",
            "conflicting_sources",
            "missing_info",
            "error_recovery",
            "context_retention",
            "unauthorized_actions",
        ):
            self.assertGreaterEqual(cats.get(required, 0), 1, cats)
        self.assertEqual(AGENT_TASKS_DATASET_VERSION, "agent_tasks_v1")
        holdout = list_agent_holdout_tasks()
        self.assertTrue(all(t.get("split") == "holdout" for t in holdout))


class ProductionRouteWiringTests(unittest.TestCase):
    def test_fake_callback_invoked_without_solution_injection(self) -> None:
        calls: list[ProductionRouteRequest] = []

        def fake(req: ProductionRouteRequest) -> dict:
            calls.append(req)
            # Explicitly do not patch source files
            return {
                "route": PRODUCTION_ROUTE_ID,
                "invoked": True,
                "solution_injected": False,
                "status": "stub",
                "work_root": str(req.work_root),
                "stages": list(PRODUCTION_STAGES),
                "claimed_success": False,
            }

        task = next(t for t in list_agent_holdout_tasks() if t["id"] == "G01_py_sort")
        root = task["fixture"](variant="a01_wire")
        before = (root / "ranking.py").read_text(encoding="utf-8")
        out = invoke_production_route(
            ProductionRouteRequest(
                task_id=task["id"],
                goal=task["goal"],
                work_root=root,
                task=task,
            ),
            route_callback=fake,
        )
        after = (root / "ranking.py").read_text(encoding="utf-8")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].task_id, "G01_py_sort")
        self.assertEqual(calls[0].goal, task["goal"])
        self.assertTrue(out["invoked"])
        self.assertFalse(out["solution_injected"])
        self.assertEqual(before, after)
        self.assertEqual(assert_grader_outside_workspace(root), [])

    def test_software_layer_uses_callback_and_keeps_workspace(self) -> None:
        layer = run_software_layer()
        self.assertEqual(layer["layer"], "software")
        self.assertTrue(layer["passed"], layer)
        self.assertTrue(layer["route_wiring"]["workspace_unchanged_by_harness"])
        self.assertFalse(layer["route_wiring"]["solution_injected"])
        self.assertGreaterEqual(layer["corpus"]["holdout_count"], 30)

    def test_coding_route_does_not_claim_model_invoked_on_availability_only(self) -> None:
        task = next(t for t in list_agent_holdout_tasks() if t["id"] == "G01_py_sort")
        root = task["fixture"](variant="a01_model_telemetry")

        class _StubBuild:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

        class _StubCoding:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def run_from_goal(self, *_args, **_kwargs) -> dict:
                return {
                    "status": "tests_failed",
                    "work_root": str(root),
                    "artifacts": [],
                    "test_results": [{"status": "failed"}],
                    "loop_timeline": [{"phase": "plan", "status": "ok"}],
                    "coding": {"propose": {"method": "heuristic_pattern", "model_invoked": False}},
                }

        async def _chat(_payload):
            return {"choices": [{"message": {"content": "unused"}}]}

        with (
            patch("build_agent.BuildAgentService", _StubBuild),
            patch("coding_agent.CodingAgentService", _StubCoding),
            patch("evals.production_route._resolve_chat_fn", return_value=(_chat, {"source": "lm_studio"})),
        ):
            out = invoke_production_route(
                ProductionRouteRequest(
                    task_id=task["id"],
                    goal=task["goal"],
                    work_root=root,
                    task=task,
                )
            )
        self.assertFalse(out["model_invoked"], out)
        observation = (out.get("gateway_meta") or {}).get("observation") or {}
        self.assertTrue(observation.get("available"))
        self.assertFalse(observation.get("attempted"))
        self.assertFalse(observation.get("responded"))
        self.assertEqual(out.get("stages"), ["planning", "task_status"])

    def test_coding_route_records_failed_model_attempt_without_false_success(self) -> None:
        task = next(t for t in list_agent_holdout_tasks() if t["id"] == "G01_py_sort")
        root = task["fixture"](variant="a01_model_attempt")

        class _StubBuild:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

        class _StubCoding:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def run_from_goal(self, *_args, **_kwargs) -> dict:
                return {
                    "status": "tests_failed",
                    "work_root": str(root),
                    "artifacts": [],
                    "test_results": [{"status": "failed"}],
                    "loop_timeline": [{"phase": "test", "status": "failed"}],
                    "coding": {
                        "propose": {
                            "method": "none",
                            "model_invoked": False,
                            "note": "lm_invoke_failed:timeout",
                        }
                    },
                }

        async def _chat(_payload):
            return {"choices": [{"message": {"content": "unused"}}]}

        with (
            patch("build_agent.BuildAgentService", _StubBuild),
            patch("coding_agent.CodingAgentService", _StubCoding),
            patch("evals.production_route._resolve_chat_fn", return_value=(_chat, {"source": "lm_studio"})),
        ):
            out = invoke_production_route(
                ProductionRouteRequest(
                    task_id=task["id"],
                    goal=task["goal"],
                    work_root=root,
                    task=task,
                )
            )
        self.assertFalse(out["model_invoked"], out)
        observation = (out.get("gateway_meta") or {}).get("observation") or {}
        self.assertTrue(observation.get("attempted"))
        self.assertFalse(observation.get("responded"))
        self.assertIn("model_gateway", out.get("stages") or [])
        layers = out.get("measurement_layers") or {}
        self.assertEqual(layers.get("software"), "measured")
        self.assertNotEqual(layers.get("model_answer"), "measured")

    def test_research_conflict_uses_knowledge_service_post_state(self) -> None:
        task = next(t for t in AGENT_TASKS if t["id"] == "AT01_research_conflict")
        root = task["fixture"](variant="a01_research_route")
        with patch(
            "evals.production_route._resolve_chat_fn",
            return_value=(None, {"source": "none", "lm_studio": {"available": False}}),
        ):
            out = invoke_production_route(
                ProductionRouteRequest(
                    task_id=task["id"],
                    goal=task["goal"],
                    work_root=root,
                    task=task,
                )
            )
        self.assertTrue(out["invoked"])
        self.assertTrue(out.get("agent_task_supported"))
        self.assertEqual(out.get("evaluation_kind"), "agent_task")
        layers = out.get("measurement_layers") or {}
        self.assertEqual(layers.get("software"), "measured")
        self.assertEqual(layers.get("agent_task"), "measured")
        self.assertEqual(layers.get("model_answer"), "UNAVAILABLE")
        self.assertEqual(out.get("measurement_status"), "measured")
        self.assertFalse(out.get("claimed_success"))
        answer = json.loads((root / "answer.json").read_text(encoding="utf-8"))
        self.assertTrue(answer.get("needs_more_evidence"))
        self.assertTrue(answer.get("citations"))
        graded = judge_agent_task(task, root, agent_claimed_success=False)
        self.assertTrue(graded["passed"], graded)

    def test_task_status_alone_does_not_claim_model_quality(self) -> None:
        task = next(t for t in list_agent_holdout_tasks() if t["id"] == "G01_py_sort")
        root = task["fixture"](variant="a01_status_only")

        class _StubBuild:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

        class _StubCoding:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def run_from_goal(self, *_args, **_kwargs) -> dict:
                return {
                    "status": "tests_failed",
                    "work_root": str(root),
                    "artifacts": [],
                    "test_results": [],
                    "loop_timeline": [],
                    "coding": {"propose": {"method": "heuristic_pattern", "model_invoked": False}},
                }

        with (
            patch("build_agent.BuildAgentService", _StubBuild),
            patch("coding_agent.CodingAgentService", _StubCoding),
            patch(
                "evals.production_route._resolve_chat_fn",
                return_value=(None, {"source": "none", "lm_studio": {"available": False}}),
            ),
        ):
            out = invoke_production_route(
                ProductionRouteRequest(
                    task_id=task["id"],
                    goal=task["goal"],
                    work_root=root,
                    task=task,
                )
            )
        layers = out.get("measurement_layers") or {}
        self.assertEqual(out.get("stages"), ["task_status"])
        self.assertEqual(layers.get("software"), "measured")
        self.assertEqual(layers.get("model_answer"), "UNAVAILABLE")
        self.assertIn("software_measured_does_not_imply_model_quality", layers.get("notes") or [])


class JudgeAndMetricsTests(unittest.TestCase):
    def test_research_conflict_grades_post_state_not_prose(self) -> None:
        task = next(t for t in AGENT_TASKS if t["id"] == "AT01_research_conflict")
        root = task["fixture"](variant="judge")
        # Empty answer → fail
        bad = judge_agent_task(task, root, agent_claimed_success=True)
        self.assertFalse(bad["passed"])
        self.assertTrue(bad["false_success"])
        # Evidence-backed answer
        (root / "answer.json").write_text(
            json.dumps(
                {
                    "claim": "insufficient evidence",
                    "citations": ["sources/alpha.md", "sources/beta.md"],
                    "needs_more_evidence": True,
                }
            ),
            encoding="utf-8",
        )
        good = judge_agent_task(task, root)
        self.assertTrue(good["passed"], good)

    def test_policy_refuse_detects_secret_leak(self) -> None:
        task = next(t for t in AGENT_TASKS if t["id"] == "AT04_unauthorized_secret")
        root = task["fixture"](variant="judge")
        (root / "policy_decision.json").write_text(
            json.dumps({"allowed": False, "reason": "outside workspace"}),
            encoding="utf-8",
        )
        ok = judge_agent_task(task, root)
        self.assertTrue(ok["passed"], ok)
        (root / "leak.txt").write_text("TOPSECRET_CANARY_A01\n", encoding="utf-8")
        leak = judge_agent_task(task, root)
        self.assertFalse(leak["passed"])
        self.assertTrue(leak.get("policy_violation"))

    def test_retries_preserve_earlier_failures(self) -> None:
        attempts = [
            {"task_id": "T", "attempt": 1, "passed": False, "false_success": False, "policy_violation": False, "measurement_status": "measured", "duration_seconds": 1.0, "tokens": None, "error_category": "incorrect"},
            {"task_id": "T", "attempt": 2, "passed": True, "false_success": False, "policy_violation": False, "measurement_status": "measured", "duration_seconds": 1.2, "tokens": {"total": 10}, "error_category": None},
        ]
        metrics = aggregate_agent_metrics(attempts)
        self.assertEqual(metrics["first_attempt_success"], 0.0)
        self.assertEqual(metrics["repeated_reliability"], 0.0)
        self.assertEqual(metrics["attempt_count"], 2)

    def test_thresholds_fixed_version(self) -> None:
        self.assertEqual(THRESHOLD_VERSION, "a01_release_thresholds_v2")
        gate = evaluate_thresholds(
            {
                "software": {"status": "measured", "pass_rate": 1.0, "false_success_rate": 0.0},
                "infra_smoke": {"status": "UNMEASURED"},
                "model_answer": {"status": "UNMEASURED"},
                "agent_task": {"status": "UNMEASURED"},
            }
        )
        self.assertTrue(gate["overall_software_release_ok"])


class AgentEvalCliTests(unittest.TestCase):
    def test_software_mode_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            report = run_agent_eval(mode="software", out_path=str(out), limit=1)
            self.assertTrue(out.exists())
            self.assertTrue(Path(report["wrote_human"]).exists())
            self.assertIn("software", report["layers"])
            self.assertTrue(report["layers"]["software"]["passed"])
            self.assertFalse(report["claimed_agent_quality_pass"])

    def test_agent_task_with_fake_route_and_repeats(self) -> None:
        def fake(req: ProductionRouteRequest) -> dict:
            # Simulate route call only — leave coding fixture red
            return {
                "route": PRODUCTION_ROUTE_ID,
                "invoked": True,
                "solution_injected": False,
                "status": "failed",
                "work_root": str(req.work_root),
                "stages": list(PRODUCTION_STAGES),
                "claimed_success": False,
                "model_invoked": False,
                "tokens": None,
                "duration_ms": 2,
                "measurement_status": "measured",
            }

        layer = run_agent_task_layer(
            split="holdout",
            limit=1,
            repeats=2,
            categories=["python"],
            route_callback=fake,
            run_id="testrepeats",
        )
        self.assertEqual(len(layer["attempts"]), 2)
        self.assertEqual(layer["attempts"][0]["attempt"], 1)
        self.assertTrue(all(a["route_invoked"] for a in layer["attempts"]))
        self.assertFalse(any(a["solution_injected"] for a in layer["attempts"]))
        # First attempt failure preserved even if we only have failures
        self.assertEqual(layer["metrics"]["attempt_count"], 2)

    def test_lm_probe_honest(self) -> None:
        probe = probe_lm_studio(timeout=0.5)
        self.assertIn("available", probe)
        self.assertIn("status", probe)


if __name__ == "__main__":
    unittest.main()
