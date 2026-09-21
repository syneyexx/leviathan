"""Characterization tests for Gen2 Flight Recorder extraction + side-effect-safe replay."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.flight_recorder import (
    compare_runs,
    flight_log,
    record,
    replay_plan,
)
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class FlightRecorderModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "flight.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_record_and_flight_log_sequence(self) -> None:
        e1 = record(self.store, "run1", "RUN_CREATED", {"x": 1}, component="test")
        e2 = record(
            self.store,
            "run1",
            "MODEL_REQUEST",
            {"prompt": "hi"},
            model_id="m1",
            input_text="hi",
            severity="info",
            duration_ms=12.5,
        )
        self.assertEqual(e1["sequence"], 1)
        self.assertEqual(e2["sequence"], 2)
        self.assertEqual(e2["model_id"], "m1")
        self.assertIsNotNone(e2["input_hash"])
        self.assertIn("_diagnostics", e2["payload"])
        self.assertEqual(e2["payload"]["_diagnostics"]["severity"], "info")

        all_events = flight_log(self.store, "run1")
        self.assertEqual(len(all_events), 2)
        after = flight_log(self.store, "run1", after_sequence=1)
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["event_type"], "MODEL_IO")

    def test_compare_runs_model_and_context_diff(self) -> None:
        record(self.store, "run_a", "RUN_CREATED", {})
        record(self.store, "run_a", "MODEL_REQUEST", {}, model_id="m1")
        record(self.store, "run_a", "CONTEXT_SELECTED", {"source": "k1", "path": "/a"})
        record(self.store, "run_a", "TOOL_RESULT", {"ok": True, "tool_name": "read"})
        record(self.store, "run_b", "RUN_CREATED", {})
        record(self.store, "run_b", "MODEL_REQUEST", {}, model_id="m2")
        record(self.store, "run_b", "CONTEXT_SELECTED", {"source": "k2"})
        record(self.store, "run_b", "VERIFICATION", {"passed": True})

        diff = compare_runs(self.store, "run_a", "run_b")
        self.assertIn("m1", diff["model_diff"]["a"])
        self.assertIn("m2", diff["model_diff"]["b"])
        self.assertIn("TOOL", diff["type_diff"]["only_a"])
        self.assertIn("VERIFY", diff["type_diff"]["only_b"])
        self.assertIn("k1", diff["context_diff"]["only_a"])
        self.assertIn("k2", diff["context_diff"]["only_b"])
        self.assertEqual(diff["event_count"]["a"], 4)
        self.assertEqual(diff["event_count"]["b"], 4)

    def test_replay_blocks_side_effects_by_default(self) -> None:
        record(self.store, "src", "RUN_CREATED", {})
        record(self.store, "src", "MODEL_REQUEST", {"prompt": "x"}, model_id="m1")
        record(self.store, "src", "TOOL_RESULT", {"ok": True, "wrote": "/tmp/x"})
        record(self.store, "src", "tool_status", {"status": "done"})

        manifest = replay_plan(self.store, "src", alternate_model="m-alt")
        self.assertTrue(manifest["ok"])
        self.assertEqual(manifest["mode"], "inspect_manifest")
        self.assertEqual(manifest["kind"], "inspection_not_replay")
        self.assertFalse(manifest["alternate_model_executed"])
        self.assertFalse(manifest.get("permit_side_effects", True))
        self.assertEqual(manifest["side_effect_policy"], "block")
        self.assertIn("replay_run_id", manifest)

        tool_steps = [s for s in manifest["steps"] if s["event_type"] in {"TOOL", "tool_status"} or "TOOL" in s["event_type"].upper()]
        self.assertGreaterEqual(len(tool_steps), 2)
        for step in tool_steps:
            self.assertFalse(step["executed"])
            self.assertEqual(step["side_effects"], "blocked")
            self.assertIn(step["action"], {"block_side_effect", "reuse_recorded_tool_result"})

        model_steps = [s for s in manifest["steps"] if s["event_type"] == "MODEL_IO" or "MODEL" in s["event_type"].upper()]
        self.assertTrue(model_steps)
        for step in model_steps:
            self.assertFalse(step["executed"])
            self.assertEqual(step["action"], "inspect_model_io")
            self.assertEqual(step["suggested_alternate_model"], "m-alt")

        # Replay itself only appends inspect events — no live tool I/O.
        replay_events = flight_log(self.store, manifest["replay_run_id"])
        types = {e["event_type"] for e in replay_events}
        self.assertIn("REPLAY_MANIFEST", types)
        self.assertNotIn("TOOL_STARTED", types)

    def test_replay_permit_side_effects_simulates_only(self) -> None:
        record(self.store, "src", "TOOL_RESULT", {"path": "/out", "action": "write"})
        manifest = replay_plan(self.store, "src", permit_side_effects=True)
        self.assertTrue(manifest["ok"])
        self.assertTrue(manifest["permit_side_effects"])
        self.assertEqual(manifest["side_effect_policy"], "simulate")
        step = manifest["steps"][0]
        self.assertEqual(step["side_effects"], "simulated")
        self.assertFalse(step["executed"])
        self.assertEqual(step["action"], "simulate_side_effect")
        self.assertIn("not re-executed", step["note"].lower())

    def test_replay_empty_run(self) -> None:
        out = replay_plan(self.store, "missing")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "no_events")

    def test_services_delegate_public_api(self) -> None:
        svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        svc.record("r", "RUN_CREATED", {"via": "svc"})
        self.assertEqual(len(svc.flight_log("r")), 1)
        svc.record("r2", "MODEL_REQUEST", {}, model_id="x")
        diff = svc.compare_runs("r", "r2")
        self.assertEqual(diff["event_count"]["a"], 1)
        replay = svc.replay_plan("r", alternate_model="y")
        self.assertTrue(replay["ok"])
        self.assertFalse(replay["permit_side_effects"])


if __name__ == "__main__":
    unittest.main()
