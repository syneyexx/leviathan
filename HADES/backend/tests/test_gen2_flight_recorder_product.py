"""Product-depth tests for Gen2 Flight Recorder (E1–E10)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.flight_recorder import (
    CANONICAL_EVENT_TYPES,
    classify_failure_taxonomy,
    compare_runs,
    emit_run_lifecycle,
    export_audit_bundle,
    normalize_event_type,
    record,
    replay_plan,
)
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class FlightRecorderProductTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "flight.db"))
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_normalize_aliases_on_write(self) -> None:
        self.assertEqual(normalize_event_type("MODEL_REQUEST")[0], "MODEL_IO")
        self.assertEqual(normalize_event_type("TOOL_RESULT")[0], "TOOL")
        self.assertEqual(normalize_event_type("VERIFICATION")[0], "VERIFY")
        e = record(self.store, "r1", "MODEL_REQUEST", {"prompt": "hi"}, model_id="m1", input_text="hi")
        self.assertEqual(e["event_type"], "MODEL_IO")
        self.assertEqual(e["payload"].get("_event_type_alias"), "MODEL_REQUEST")
        self.assertTrue({"MODEL_IO", "TOOL", "VERIFY", "TERMINAL"} <= set(CANONICAL_EVENT_TYPES))

    def test_failure_taxonomy_classifier(self) -> None:
        perm = record(
            self.store,
            "r2",
            "TOOL",
            {"error": "permission denied", "ok": False},
        )
        self.assertEqual(perm["payload"].get("failure_taxonomy"), "permission")
        self.assertEqual(classify_failure_taxonomy(perm), "permission")

        budget = classify_failure_taxonomy(
            {"event_type": "TERMINAL", "payload": {"error": "budget exhausted", "ok": False}}
        )
        self.assertEqual(budget, "budget")

        schema = classify_failure_taxonomy(
            {"event_type": "MODEL_IO", "payload": {"error": "schema validation failed", "ok": False}}
        )
        self.assertEqual(schema, "schema")

    def test_export_audit_bundle(self) -> None:
        record(
            self.store,
            "audit1",
            "PLAN",
            {"steps": 1},
            config_fingerprint="cfg_abc",
        )
        record(
            self.store,
            "audit1",
            "MODEL_IO",
            {"io_kind": "request"},
            model_id="m",
            input_text="q",
            model_snapshot={"model_id": "m", "provider": "local", "snapshot_kind": "model_id_record"},
        )
        record(self.store, "audit1", "TERMINAL", {"ok": True, "status": "completed"})
        bundle = export_audit_bundle(self.store, "audit1")
        self.assertTrue(bundle["ok"])
        self.assertEqual(bundle["run_id"], "audit1")
        self.assertGreaterEqual(len(bundle["events"]), 3)
        self.assertIn("cfg_abc", bundle["config_fingerprints"])
        self.assertIn("bundle_hash", bundle["manifest"])
        self.assertTrue(bundle["manifest"]["honesty"]["bundle_is_inspection_export"])
        self.assertTrue(bundle["hashes"]["payload"])
        self.assertTrue(bundle["model_snapshots"])
        self.assertTrue(any(e.get("payload_hash") for e in bundle["events"]))
        model_ev = next(e for e in bundle["events"] if e.get("model_id") == "m")
        self.assertTrue(model_ev.get("model_snapshot"))
        self.assertEqual(model_ev["model_snapshot"]["model_id"], "m")

    def test_record_always_stores_payload_hash_and_model_snapshot(self) -> None:
        """E3 — content hashes + config fingerprints + model snapshots on write."""
        ev = record(
            self.store,
            "e3run",
            "TOOL",
            {"tool_name": "search", "ok": True},
            model_id="local-model",
            config_fingerprint="cfg_e3",
            input_text="query",
            output_text="result",
        )
        payload = ev["payload"]
        self.assertTrue(payload.get("payload_hash"))
        self.assertEqual(payload.get("config_fingerprint"), "cfg_e3")
        self.assertEqual(payload["_diagnostics"]["config_fingerprint"], "cfg_e3")
        self.assertEqual(payload["model_snapshot"]["model_id"], "local-model")
        self.assertTrue(ev.get("input_hash"))
        self.assertTrue(ev.get("output_hash"))

    def test_compare_runs_includes_failure_taxonomy_diff(self) -> None:
        record(self.store, "a", "TOOL", {"ok": False, "error": "tool failed"})
        record(self.store, "a", "VERIFY", {"passed": True})
        record(self.store, "b", "TOOL", {"ok": True})
        record(self.store, "b", "VERIFY", {"passed": False, "error": "verification failed"})
        diff = compare_runs(self.store, "a", "b")
        self.assertIn("failure_taxonomy_diff", diff)
        self.assertIn("a", diff["failure_taxonomy_diff"])
        self.assertIn("b", diff["failure_taxonomy_diff"])

    def test_emit_run_lifecycle_vocabulary(self) -> None:
        run_id = "life1"
        for phase in (
            "MODEL_IO",
            "CONTEXT_SELECTED",
            "PLAN",
            "TOOL",
            "APPROVAL",
            "REPLAN",
            "VERIFY",
            "ARTIFACT",
            "TERMINAL",
        ):
            ev = emit_run_lifecycle(self.store, run_id, phase, {"phase": phase})
            self.assertEqual(ev["event_type"], phase)
            self.assertEqual(ev["component"], "run_lifecycle")

    def test_replay_plan_remains_inspection_not_replay(self) -> None:
        record(self.store, "src", "MODEL_REQUEST", {"prompt": "x"}, model_id="m")
        record(self.store, "src", "TOOL_RESULT", {"ok": True, "wrote": "out.txt"})
        manifest = replay_plan(self.store, "src")
        self.assertEqual(manifest["kind"], "inspection_not_replay")
        self.assertEqual(manifest["mode"], "inspect_manifest")
        self.assertFalse(manifest["alternate_model_executed"])
        self.assertFalse(manifest["live_side_effects_executed"])
        self.assertFalse(manifest["honesty"]["live_model_replay"])
        self.assertFalse(manifest["honesty"]["live_tool_reexecution"])

    def test_services_export_audit(self) -> None:
        self.svc.emit_run_lifecycle("s1", "PLAN", {"ok": True})
        bundle = self.svc.export_audit_bundle("s1")
        self.assertTrue(bundle["ok"])


if __name__ == "__main__":
    unittest.main()
