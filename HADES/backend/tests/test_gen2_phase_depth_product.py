"""Product-depth tests for Gen2 Phase 3–5 slices (sandbox/committee/graph/finance/compute/context)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.compute_fabric import process_local_queue, single_node_solidity_gate
from gen2.context_compiler import chat_compiler_enabled, compile_for_chat_path
from gen2.finance_fusion import fuse_market_intelligence, persist_thesis, run_event_study
from gen2.services import Gen2Services
from gen2.store import Gen2Store
from gen2.temporal_graph import as_of_beliefs, assert_edge, cross_store_link_plan, find_analogues, find_contradictions


class Gen2PhaseDepthProductTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Gen2Store(str(self.root / "phase.db"))
        self.svc = Gen2Services(self.store, data_root=self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_temporal_contradiction_analogue_provenance(self) -> None:
        assert_edge(
            self.store,
            self.svc.record,
            {
                "source_id": "ent:acme",
                "target_id": "claim:bull",
                "relation_kind": "supports",
                "valid_from": "2024-01-01T00:00:00Z",
                "observed_at": "2024-02-01T00:00:00Z",
                "provenance": "filing:10k",
                "confidence": 0.8,
            },
            require_provenance=True,
        )
        assert_edge(
            self.store,
            self.svc.record,
            {
                "source_id": "ent:acme",
                "target_id": "claim:bear",
                "relation_kind": "contradicts",
                "contradicts": "claim:bull",
                "valid_from": "2024-01-01T00:00:00Z",
                "observed_at": "2024-03-01T00:00:00Z",
                "provenance": "analyst:note",
                "confidence": 0.7,
            },
            require_provenance=True,
        )
        with self.assertRaises(ValueError):
            self.svc.assert_edge(
                {"source_id": "ent:acme", "target_id": "claim:x", "relation_kind": "supports"},
                require_provenance=True,
            )
        mid = as_of_beliefs(
            self.store,
            "ent:acme",
            "2024-02-15T00:00:00Z",
            known_as_of="2024-02-15T00:00:00Z",
        )
        targets = {b.get("target_id") for b in mid["beliefs"]}
        self.assertIn("claim:bull", targets)
        self.assertNotIn("claim:bear", targets)
        contras = find_contradictions(self.store, "ent:acme")
        self.assertGreaterEqual(len(contras), 1)
        analogues = find_analogues(self.store, text="acme supports filing", limit=5)
        self.assertGreaterEqual(analogues["count"], 1)
        plan = cross_store_link_plan(memory_ids=["m1"], evidence_ids=["e1"])
        self.assertTrue(plan["roles_preserved"])
        self.assertEqual(len(plan["links"]), 2)

    def test_finance_event_study_and_thesis_persistence(self) -> None:
        refused = run_event_study({"id": "evt1"}, bars=None)
        self.assertEqual(refused["status"], "plan_only")
        self.assertTrue(refused["incomplete"])
        self.assertIsNone(refused["computed_abnormal_return"])

        incomplete = run_event_study(
            {"id": "evt1"},
            bars=[{"close": 10.0}, {"close": 10.5}],
            window_days=5,
        )
        self.assertEqual(incomplete["status"], "incomplete")
        self.assertIsNone(incomplete["computed_abnormal_return"])

        bars = [{"close": 10.0 + i * 0.2} for i in range(8)]
        computed = run_event_study({"id": "evt1"}, bars=bars, window_days=5)
        self.assertEqual(computed["status"], "computed_simple_return")
        self.assertIsNone(computed["computed_abnormal_return"])
        self.assertIsNotNone(computed["computed_simple_return"])
        self.assertTrue(computed["paper_only"])

        fused = fuse_market_intelligence(
            self.store,
            articles=[
                {
                    "title": "ACME earnings beat estimates",
                    "summary": "ACME quarterly earnings beat",
                    "source": "wire-a",
                },
                {
                    "title": "ACME reports earnings beat",
                    "summary": "ACME strong earnings print",
                    "source": "wire-b",
                },
            ],
            symbol="ACME",
        )
        self.assertTrue(fused["cross_verify"]["verified"] or fused["cross_verify"]["source_count"] >= 2)
        self.assertIn("thesis_persisted", fused)
        self.assertTrue(fused["thesis_persisted"]["ok"])
        thesis_id = fused["thesis_persisted"]["thesis_event_id"]
        loaded = self.store.get_market_event(thesis_id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual((loaded.get("metadata") or {}).get("kind"), "paper_thesis")
        self.assertTrue((loaded.get("metadata") or {}).get("paper_only"))

        again = persist_thesis(
            self.store,
            {"statement": "ACME structural catalyst cluster", "confidence": 0.6, "event_ids": []},
            symbol="ACME",
        )
        self.assertTrue(again["ok"])

    def test_compute_local_queue_and_solidity_gate(self) -> None:
        gate = single_node_solidity_gate(self.store, self.root)
        self.assertTrue(gate["passed"])
        self.assertTrue(gate["multi_host_deferred"])
        self.assertFalse(gate["multi_host_allowed"])
        self.assertTrue(gate["checks"]["queue_drain_processed"])

        self.store.create_remote_job(
            {"node_id": "node_local", "status": "queued", "payload": {"op": "local_info"}}
        )
        drained = process_local_queue(self.store, self.root, limit=5)
        self.assertGreaterEqual(drained["processed"], 1)
        self.assertEqual(drained["mode"], "single_node_local_queue")
        svc_gate = self.svc.single_node_compute_gate()
        self.assertEqual(svc_gate["gate"], "L6_single_node_solidity")

    def test_context_compiler_chat_opt_in_default_off(self) -> None:
        self.assertFalse(chat_compiler_enabled())
        self.assertFalse(chat_compiler_enabled(env={}))
        off = compile_for_chat_path(
            self.store,
            goal="test",
            items=[{"item_id": "1", "content": "fact", "kind": "knowledge"}],
            opt_in=False,
            persist=False,
        )
        self.assertFalse(off["enabled"])
        self.assertTrue(off["default_path_preserved"])
        self.assertFalse(off["used_compiler"])

        on = compile_for_chat_path(
            self.store,
            goal="test",
            items=[{"item_id": "1", "content": "fact about test", "kind": "knowledge"}],
            opt_in=True,
            persist=False,
            max_tokens=256,
        )
        self.assertTrue(on["enabled"])
        self.assertTrue(on["used_compiler"])
        self.assertIn("pack", on)

        env_on = compile_for_chat_path(
            self.store,
            goal="test",
            items=[{"item_id": "1", "content": "fact about test", "kind": "knowledge"}],
            env={"HADES_CONTEXT_COMPILER_CHAT": "1"},
            persist=False,
        )
        self.assertTrue(env_on["enabled"])

        svc_off = self.svc.compile_context_for_chat(
            goal="x", items=[{"item_id": "a", "content": "y"}], opt_in=False
        )
        self.assertFalse(svc_off["enabled"])


if __name__ == "__main__":
    unittest.main()
