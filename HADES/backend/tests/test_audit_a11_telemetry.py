"""A11 — correlation telemetry, honest tokens, reproducible exports."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.correlation_telemetry import (
    ExperimentMeta,
    config_hash,
    export_reproducible_bundle,
    human_run_summary,
    inspect_vs_replay_modes,
    normalize_token_usage,
    record_correlated,
    register_experiment_relation,
)
from gen2.flight_recorder import replay_plan
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class A11CorrelationTelemetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "a11.db"))
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_stable_correlation_across_surfaces(self) -> None:
        corr = "corr_stable_1"
        surfaces = [
            ("PLAN", {"plan_revision": 1}, {"step_id": "s1"}),
            ("TOOL", {"ok": True}, {"toolcall_id": "tc1", "step_id": "s1"}),
            ("APPROVAL", {"approved": True}, {"approval_id": "ap1"}),
            ("ARTIFACT", {"bytes": 12}, {"artifact_version": "v1"}),
            ("TERMINAL", {"ok": True, "status": "completed"}, {}),
        ]
        for et, payload, extra in surfaces:
            record_correlated(
                self.store,
                run_id="run_corr",
                event_type=et,
                payload=payload,
                correlation={
                    "correlation_id": corr,
                    "conversation_id": "c1",
                    "task_id": "t1",
                    "mission_id": "m1",
                    "workflow_id": "w1",
                    "run_id": "run_corr",
                    **extra,
                },
                model_id="software-test",
                effective_model_config={"model": "software-test", "temp": 0},
                source_versions={"repo": "hades", "rev": "test"},
                context_ids=["ctx_a"],
                budget_decision={"kept": 2, "dropped": 0},
                acceptance_evidence={"checks_passed": True} if et == "TERMINAL" else None,
                token_usage={"total_tokens": 4, "kind": "exact", "source": "provider"}
                if et == "TOOL"
                else {"tokens_missing": True},
            )
        summary = human_run_summary(self.store, "run_corr")
        self.assertEqual(summary["correlation_ids"], [corr])
        self.assertGreaterEqual(summary["event_count"], 5)
        self.assertEqual(summary["token_usage"]["exact_total"], 4)

    def test_token_usage_never_fakes_fixed_totals(self) -> None:
        exact = normalize_token_usage({"usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}})
        self.assertEqual(exact.kind, "exact")
        self.assertEqual(exact.total_tokens, 5)
        estimate = normalize_token_usage({"total_tokens": 9, "estimated": True})
        self.assertEqual(estimate.kind, "estimate")
        missing = normalize_token_usage({})
        self.assertEqual(missing.kind, "missing")
        self.assertIsNone(missing.total_tokens)

        ev = record_correlated(
            self.store,
            run_id="tok1",
            event_type="MODEL_IO",
            payload={},
            correlation={"correlation_id": "c_tok", "run_id": "tok1"},
            token_usage={},
        )
        self.assertEqual(ev["payload"]["token_usage"]["kind"], "missing")
        self.assertTrue(ev["payload"].get("tokens_missing"))
        self.assertNotIn("tokens", ev["payload"])

    def test_export_and_human_summary_keep_failures_visible(self) -> None:
        record_correlated(
            self.store,
            run_id="failrun",
            event_type="TOOL",
            payload={"ok": False, "error": "tool boom"},
            correlation={"correlation_id": "c_fail", "run_id": "failrun"},
            tool_outcome={"ok": False, "error": "tool boom"},
        )
        record_correlated(
            self.store,
            run_id="failrun",
            event_type="TERMINAL",
            payload={"ok": False, "status": "aborted", "aborted": True, "infra_issue": "lm_unavailable"},
            correlation={"correlation_id": "c_fail", "run_id": "failrun"},
        )
        bundle = export_reproducible_bundle(
            self.store,
            "failrun",
            experiment=ExperimentMeta(
                experiment_id="exp1",
                dataset_version="a11_v1",
                grader_version="g1",
                config={"recovery": True},
                label="software",
            ),
        )
        self.assertTrue(bundle["ok"])
        self.assertTrue(bundle["inspection_not_replay"])
        self.assertTrue(bundle["honesty"]["tokens_not_fabricated"])
        self.assertTrue(bundle["visible_issues"]["failures"])
        self.assertTrue(bundle["visible_issues"]["aborted"])
        self.assertTrue(bundle["visible_issues"]["infra_issues"])
        self.assertIn("Failures visible", bundle["human_summary"])
        self.assertEqual(bundle["experiment"]["config_hash"], config_hash({"recovery": True}))

    def test_inspect_vs_replay_separation(self) -> None:
        record_correlated(
            self.store,
            run_id="src",
            event_type="MODEL_IO",
            payload={"prompt": "x"},
            correlation={"correlation_id": "c_src", "run_id": "src"},
            model_id="software-test",
            token_usage={"total_tokens": 2, "kind": "exact"},
        )
        record_correlated(
            self.store,
            run_id="src",
            event_type="TOOL",
            payload={"tool_name": "write", "ok": True, "wrote": "out.txt"},
            correlation={"correlation_id": "c_src", "run_id": "src", "toolcall_id": "tc"},
        )
        manifest = replay_plan(self.store, "src")
        self.assertEqual(manifest["kind"], "inspection_not_replay")
        self.assertFalse(manifest.get("live_side_effects_executed"))
        modes = inspect_vs_replay_modes()
        self.assertFalse(modes["inspect"]["reexecutes_model"])
        self.assertTrue(modes["comparative_replay"]["reexecutes_model"])
        self.assertFalse(modes["comparative_replay"]["reexecutes_tools"])

    def test_experiment_parent_relation(self) -> None:
        record_correlated(
            self.store,
            run_id="parent",
            event_type="TERMINAL",
            payload={"ok": True, "status": "completed"},
            correlation={"correlation_id": "c_p", "run_id": "parent"},
        )
        record_correlated(
            self.store,
            run_id="child",
            event_type="TERMINAL",
            payload={"ok": True, "status": "completed"},
            correlation={"correlation_id": "c_c", "run_id": "child"},
        )
        rel = register_experiment_relation(
            self.store,
            parent_run_id="parent",
            child_run_id="child",
            experiment={
                "experiment_id": "exp_ab",
                "dataset_version": "ds1",
                "grader_version": "gr1",
                "config": {"recovery": False},
            },
        )
        self.assertTrue(rel["ok"])
        self.assertEqual(rel["experiment"]["config_hash"], config_hash({"recovery": False}))
        parent_events = self.store.list_run_events("parent")
        self.assertTrue(any(e["event_type"] == "PARENT_RELATION" for e in parent_events))

    def test_services_export_wrapper(self) -> None:
        self.svc.record_correlated(
            "svc_run",
            "MODEL_IO",
            {"io": "req"},
            correlation={"correlation_id": "c_svc", "run_id": "svc_run"},
            token_usage={"estimated": True, "total_tokens": 11},
            effective_model_config={"model": "software-test"},
        )
        summary = self.svc.human_run_summary("svc_run")
        self.assertEqual(summary["token_usage"]["estimate_total"], 11)
        bundle = self.svc.export_reproducible_bundle("svc_run")
        self.assertTrue(bundle["ok"])
        self.assertEqual(bundle["mode"], "inspection_export")


if __name__ == "__main__":
    unittest.main()
