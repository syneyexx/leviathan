"""Tests for comparative sandboxed replay (work package N)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.flight_recorder import comparative_replay, compare_runs, record, replay_plan
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class ComparativeReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "flight.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _seed(self) -> str:
        run_id = "src_run"
        record(self.store, run_id, "RUN_CREATED", {"goal": "answer"}, component="test")
        record(
            self.store,
            run_id,
            "CONTEXT_SELECTED",
            {"source": "knowledge:doc1", "path": "/k/doc1"},
            component="test",
        )
        record(
            self.store,
            run_id,
            "MODEL_REQUEST",
            {"messages": [{"role": "user", "content": "hi"}], "tokens": 10},
            model_id="model-a",
            input_text="hi",
            duration_ms=25.0,
        )
        record(
            self.store,
            run_id,
            "MODEL_RESPONSE",
            {"output": "old-answer", "usage": {"total_tokens": 12}, "tokens": 12},
            model_id="model-a",
            output_text="old-answer",
            duration_ms=40.0,
        )
        record(
            self.store,
            run_id,
            "TOOL_RESULT",
            {"ok": True, "tool_name": "read_file", "path": "/tmp/x", "content": "fixture"},
            component="test",
        )
        record(self.store, run_id, "VERIFICATION", {"passed": True, "acceptance": "ok"})
        record(self.store, run_id, "RUN_COMPLETED", {"outcome": "success"})
        return run_id

    def test_inspect_replay_unchanged_and_not_presented_as_execution(self) -> None:
        run_id = self._seed()
        manifest = replay_plan(self.store, run_id, alternate_model="model-b")
        self.assertEqual(manifest["kind"], "inspection_not_replay")
        self.assertFalse(manifest["alternate_model_executed"])
        self.assertFalse(manifest["honesty"]["live_model_replay"])

    def test_comparative_executes_model_reuses_tools_stores_parent(self) -> None:
        run_id = self._seed()
        calls: list[dict] = []

        def chat_fn(req: dict) -> dict:
            calls.append(req)
            return {
                "output": "new-answer",
                "content": "new-answer",
                "tokens": 8,
                "usage": {"total_tokens": 8},
            }

        out = comparative_replay(
            self.store,
            run_id,
            alternate_model="model-b",
            implementation_id="impl-v2",
            chat_fn=chat_fn,
            source_versions={"prompt_pack": "v1", "tools": "frozen"},
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "comparative_sandbox")
        self.assertEqual(out["kind"], "comparative_replay")
        self.assertEqual(out["parent_run_id"], run_id)
        self.assertNotEqual(out["new_run_id"], run_id)
        self.assertEqual(out["newly_executed_model_calls"], 1)
        self.assertGreaterEqual(out["reused_tool_results"], 1)
        self.assertFalse(out["approvals_reused"])
        self.assertFalse(out["honesty"]["old_approvals_grant_new_effects"])
        self.assertTrue(out["honesty"]["runs_stored_separately"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model_id"], "model-b")

        events = self.store.list_run_events(out["new_run_id"])
        types = [e["event_type"] for e in events]
        self.assertIn("PARENT_RELATION", types)
        self.assertIn("MODEL_IO", types)
        aliases = {
            (e.get("payload") or {}).get("_event_type_alias")
            for e in events
            if e["event_type"] == "MODEL_IO"
        }
        self.assertTrue(aliases & {"MODEL_REQUEST", "MODEL_RESPONSE", None})
        parent = next(e for e in events if e["event_type"] == "PARENT_RELATION")
        self.assertEqual(parent["payload"]["parent_run_id"], run_id)

        # Tool provenance from recording
        tool = next(e for e in events if e["event_type"] == "TOOL")
        self.assertEqual(tool["payload"]["_comparative"]["provenance"], "from_recording")
        self.assertFalse(tool["payload"]["_comparative"]["approvals_reused"])

        comparison = out["comparison"]
        self.assertIn("model_calls", comparison)
        self.assertIn("regressions", comparison)
        self.assertIn("outcome_acceptance", comparison)

    def test_side_effects_require_isolated_adapter(self) -> None:
        run_id = self._seed()
        denied = comparative_replay(
            self.store,
            run_id,
            reexecute_side_effects=True,
            tool_adapter=None,
            chat_fn=lambda r: {"output": "x", "tokens": 1},
        )
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"], "isolated_adapter_required_for_side_effects")

        adapted: list[dict] = []

        def adapter(event: dict) -> dict:
            adapted.append(event)
            self.assertFalse(event["approvals_from_recording_honored"])
            return {"ok": True, "isolated": True, "echo": event["payload"]}

        ok = comparative_replay(
            self.store,
            run_id,
            reexecute_side_effects=True,
            tool_adapter=adapter,
            chat_fn=lambda r: {"output": "y", "tokens": 2, "usage": {"total_tokens": 2}},
        )
        self.assertTrue(ok["ok"])
        self.assertGreaterEqual(ok["isolated_adapter_side_effects"], 1)
        self.assertTrue(adapted)
        self.assertFalse(ok["approvals_reused"])

    def test_compare_includes_tokens_duration_regressions(self) -> None:
        a = "run_a"
        b = "run_b"
        record(self.store, a, "MODEL_RESPONSE", {"tokens": 10, "_diagnostics": {"duration_ms": 5}}, model_id="m1")
        record(self.store, a, "CONTEXT_SELECTED", {"source": "ev1"})
        record(self.store, a, "VERIFICATION", {"passed": True})
        record(self.store, b, "MODEL_RESPONSE", {"tokens": 3, "_diagnostics": {"duration_ms": 9}}, model_id="m2")
        diff = compare_runs(self.store, a, b)
        self.assertEqual(diff["model_calls"]["tokens"]["a"], 10)
        self.assertEqual(diff["model_calls"]["tokens"]["b"], 3)
        self.assertIn("verification_missing_in_b", diff["regressions"])
        self.assertIn("ev1", diff["missing_evidence"])

    def test_services_facade(self) -> None:
        svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        run_id = self._seed()
        out = svc.comparative_replay(
            run_id,
            alternate_model="m-x",
            chat_fn=lambda r: {"output": "z", "tokens": 1, "usage": {"total_tokens": 1}},
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["parent_run_id"], run_id)


if __name__ == "__main__":
    unittest.main()
