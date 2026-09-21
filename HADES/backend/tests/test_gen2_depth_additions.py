"""Focused tests for Gen2 depth additions (graph analogues, finance fusion, policies, gates)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.committee import mark_claims, run_committee
from gen2.finance_fusion import (
    cross_verify_sources,
    evaluate_finance_claim,
    fuse_market_intelligence,
    propose_paper_strategy,
)
from gen2.mission_control import (
    compile_mission,
    decide_mission_gate,
    diff_mission_revisions,
    mission_revision_snapshot,
    revoke_mission_gate,
)
from gen2.policy_profiles import envelope_for_profile, jit_grant, list_policy_profiles
from gen2.store import Gen2Store
from gen2.temporal_graph import assert_edge, find_analogues


class Gen2DepthAdditionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "depth.db"))
        self.events: list[dict] = []

        def _record(run_id, event_type, payload=None, **kwargs):
            row = {"run_id": run_id, "event_type": event_type, "payload": payload or {}}
            self.events.append(row)
            return row

        self.record = _record

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_policy_profiles_listed(self) -> None:
        rows = list_policy_profiles()
        ids = {r["id"] for r in rows}
        self.assertEqual(ids, {"personal", "strict", "research", "coding"})
        env = envelope_for_profile("demo.plugin", "strict")
        self.assertEqual(env["envelope"]["network_policy"], "deny")
        denied = jit_grant(
            plugin_id="demo.plugin",
            profile_id="strict",
            capability="network",
            reason="test",
            now_iso="2026-01-01T00:00:00Z",
        )
        self.assertFalse(denied["ok"])

    def test_temporal_analogues_and_strict_provenance(self) -> None:
        assert_edge(
            self.store,
            self.record,
            {
                "source_id": "ent:a",
                "target_id": "claim:growth",
                "relation_kind": "supports",
                "provenance": "test:1",
                "confidence": 0.8,
            },
            require_provenance=True,
        )
        with self.assertRaises(ValueError):
            assert_edge(
                self.store,
                self.record,
                {"source_id": "ent:a", "target_id": "claim:x", "relation_kind": "supports"},
                require_provenance=True,
            )
        analogues = find_analogues(self.store, text="growth supports", limit=5)
        self.assertGreaterEqual(analogues["count"], 1)
        self.assertEqual(analogues["method"], "token_overlap_local")

    def test_finance_cross_verify_and_paper_wall(self) -> None:
        articles = [
            {
                "title": "ACME announces earnings beat",
                "summary": "ACME quarterly earnings beat estimates",
                "source": "wire-a",
            },
            {
                "title": "ACME earnings beat market",
                "summary": "ACME reports strong earnings",
                "source": "wire-b",
            },
        ]
        verify = cross_verify_sources(articles)
        self.assertGreaterEqual(verify["source_count"], 2)
        fused = fuse_market_intelligence(self.store, articles=articles, symbol="ACME")
        self.assertTrue(fused["paper_only"])
        self.assertTrue(fused["paper_strategy_proposal"]["requires_human_approval"])
        self.assertFalse(fused["paper_strategy_proposal"]["live_trading"])
        self.assertIsNone(fused["events"][0]["event_study"]["computed_abnormal_return"])
        claim = evaluate_finance_claim("ACME will moon 900%", evidence=[], events=[])
        self.assertEqual(claim["status"], "unsupported_or_missing_evidence")
        proposal = propose_paper_strategy(fused["events"], symbol="ACME")
        self.assertEqual(proposal["status"], "awaiting_approval")

    def test_gate_fingerprint_and_revoke(self) -> None:
        mission = compile_mission(self.store, self.record, "Analyse ACME earnings risk")
        gate_id = mission["gates"][0]["id"]
        approved = decide_mission_gate(
            self.store, self.record, mission["id"], gate_id, approve=True, note="ok"
        )
        gate = next(g for g in approved["gates"] if g["id"] == gate_id)
        self.assertTrue(gate.get("decision_fingerprint"))
        revoked = revoke_mission_gate(
            self.store, self.record, mission["id"], gate_id, reason="changed mind"
        )
        gate2 = next(g for g in revoked["gates"] if g["id"] == gate_id)
        self.assertEqual(gate2["status"], "revoked")
        before = mission_revision_snapshot(mission)
        after = mission_revision_snapshot(revoked)
        diff = diff_mission_revisions(before, after)
        self.assertGreaterEqual(diff["change_count"], 1)

    def test_committee_claim_marks(self) -> None:
        marks = mark_claims(
            [{"agent": "skeptic", "claim": "NVIDIA risks are understated", "confidence": 0.4}],
            ["NVIDIA supply chain risks understated in guidance"],
        )
        self.assertEqual(marks[0]["status"], "supported")
        session = run_committee(
            self.store,
            self.record,
            "NVIDIA valuation risks",
            domain="finance",
            evidence=["NVIDIA valuation risks from competition"],
        )
        self.assertIn("claim_marks", session["consensus"])


if __name__ == "__main__":
    unittest.main()
