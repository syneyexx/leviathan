"""Characterization tests for Gen2 Multi-Agent Intelligence Committee extraction."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.committee import (
    committee_roles,
    finalize_committee,
    role_stance,
    run_committee,
    run_committee_live,
)
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class CommitteeModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "committee.db"))
        self.events: list[tuple[str, str]] = []

        def _record(run_id: str, event_type: str, payload=None, **kwargs):
            self.events.append((run_id, event_type))
            return {"run_id": run_id, "event_type": event_type, "payload": payload or {}}

        self.record = _record

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_role_stance_requires_topical_evidence(self) -> None:
        unsupported = role_stance("primary_researcher", "NVIDIA outlook", ["unrelated weather note"])
        self.assertFalse(unsupported["supported"])
        self.assertEqual(unsupported["mode"], "heuristic_isolated")
        self.assertLess(unsupported["confidence"], 0.5)

        supported = role_stance(
            "primary_researcher",
            "NVIDIA outlook",
            ["NVIDIA earnings beat estimates"],
        )
        self.assertTrue(supported["supported"])
        self.assertGreaterEqual(supported["confidence"], 0.65)

    def test_committee_roles_complexity(self) -> None:
        simple = committee_roles("research", topic="What is RAM?")
        self.assertEqual(simple[0]["complexity"], "simple")
        self.assertLessEqual(len(simple), 2)

        finance = committee_roles("finance", topic="NVIDIA valuation outlook earnings")
        self.assertEqual(finance[0]["complexity"], "complex")
        self.assertGreaterEqual(len(finance), 5)
        ids = {r["id"] for r in finance}
        self.assertIn("bear_case", ids)
        self.assertIn("fundamental_analyst", ids)

    def test_finalize_consensus_fields(self) -> None:
        positions = [
            {
                "agent": "primary_researcher",
                "claim": "NVIDIA grows on datacenter demand",
                "confidence": 0.7,
                "supported": True,
                "rationale": "primary",
                "mode": "heuristic_isolated",
                "model_invoked": False,
            },
            {
                "agent": "skeptic",
                "claim": "Claim is onvoldoende onderbouwd of te optimistisch: NVIDIA",
                "confidence": 0.55,
                "supported": True,
                "rationale": "skeptic",
                "mode": "heuristic_isolated",
                "model_invoked": False,
            },
            {
                "agent": "evidence_auditor",
                "claim": "Alleen evidence-backed deelclaims accepteren voor: NVIDIA",
                "confidence": 0.7,
                "supported": False,
                "rationale": "auditor",
                "mode": "heuristic_isolated",
                "model_invoked": False,
            },
        ]
        evidence = ["NVIDIA grows on datacenter demand from hyperscalers"]
        session = finalize_committee(
            self.store,
            self.record,
            "NVIDIA outlook",
            "research",
            evidence,
            positions,
            live_requested=False,
            model_id=None,
        )
        consensus = session["consensus"]
        self.assertEqual(consensus["basis"], "position_results_plus_external_evidence")
        self.assertIn("agreements", consensus)
        self.assertIn("disagreements", consensus)
        self.assertIn("minority_positions", consensus)
        self.assertIn("unsupported_claims", consensus)
        self.assertIn("missing_evidence", consensus)
        self.assertIn("evidence_checks", consensus)
        self.assertIn("support_ratio", consensus)
        self.assertEqual(consensus["mode"], "heuristic_isolated")
        self.assertFalse(consensus["live_requested"])
        self.assertEqual(consensus["position_count"], 3)
        # Primary vs skeptic claim mismatch → disagreement surface.
        self.assertTrue(any("skeptic" in d for d in consensus["disagreements"]))
        # External evidence overlap rewrites supported flags.
        self.assertTrue(any(c["agent"] == "primary_researcher" for c in consensus["evidence_checks"]))
        self.assertEqual(len([e for e in self.events if e[1] == "VERIFICATION"]), 1)

    def test_run_committee_heuristic_public_shape(self) -> None:
        session = run_committee(
            self.store,
            self.record,
            "NVIDIA valuation outlook",
            domain="finance",
            evidence=["Revenue grew 20%", "Guidance mixed"],
        )
        consensus = session["consensus"]
        self.assertGreaterEqual(len(session["positions"]), 5)
        self.assertEqual(consensus["mode"], "heuristic_isolated")
        self.assertIn("disagreements", consensus)
        self.assertIn("missing_evidence", consensus)
        self.assertIn("role_selection", consensus)
        self.assertEqual(consensus["role_selection"]["complexity"], "complex")
        for pos in session["positions"]:
            self.assertFalse(pos.get("model_invoked"))
            self.assertEqual(pos.get("mode"), "heuristic_isolated")

    def test_run_committee_live_blocked_without_client(self) -> None:
        session = asyncio.run(
            run_committee_live(
                self.store,
                self.record,
                "NVIDIA outlook",
                evidence=["NVIDIA earnings beat"],
                chat_fn=None,
            )
        )
        consensus = session["consensus"]
        self.assertTrue(consensus.get("live_requested"))
        self.assertEqual(consensus.get("live_blocked_reason"), "lm_client_unavailable")
        self.assertEqual(consensus.get("mode"), "heuristic_isolated")
        self.assertEqual(session.get("status"), "completed_heuristic_fallback")
        self.assertFalse(any(p.get("model_invoked") for p in session["positions"]))
        # Never invent live specialist scores when blocked.
        for pos in session["positions"]:
            self.assertNotEqual(pos.get("mode"), "live_specialist")

    def test_run_committee_live_independent_perspectives(self) -> None:
        calls: list[str] = []

        async def chat_fn(payload: dict) -> dict:
            content = payload["messages"][0]["content"]
            calls.append(content)
            # Distinct claim per role so perspectives are independent.
            role = "unknown"
            if "committee role `" in content:
                role = content.split("committee role `", 1)[1].split("`", 1)[0]
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                f'{{"claim":"Independent stance from {role}",'
                                f'"confidence":0.{min(9, 5 + len(calls))},'
                                f'"supported":true,"rationale":"live {role}"}}'
                            )
                        }
                    }
                ]
            }

        session = asyncio.run(
            run_committee_live(
                self.store,
                self.record,
                "NVIDIA risks",
                domain="research",
                evidence=["NVIDIA filing note on export controls"],
                chat_fn=chat_fn,
                model_id="local-test-model",
            )
        )
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(any(p.get("model_invoked") for p in session["positions"]))
        live_claims = {p["claim"] for p in session["positions"] if p.get("model_invoked")}
        self.assertGreaterEqual(len(live_claims), 2)
        consensus = session["consensus"]
        self.assertIn(consensus.get("mode"), {"live_specialist", "mixed_live_heuristic"})
        self.assertTrue(consensus.get("live_requested"))
        self.assertIsNone(consensus.get("live_blocked_reason"))

    def test_services_delegate(self) -> None:
        svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        session = svc.run_committee(
            "What is RAM?",
            evidence=["RAM is memory"],
        )
        self.assertGreaterEqual(len(session["positions"]), 2)
        self.assertIn("consensus", session)
        roles = svc._committee_roles("coding", topic="simple compare migration architect")
        self.assertTrue(roles)

    def test_divergent_slices_not_identical_clones(self) -> None:
        """When evidence differs across role slices, positions must not be identical clones."""
        evidence = [
            "NVIDIA datacenter revenue grew strongly on AI demand",
            "NVIDIA export controls create regulatory downside risk",
            "Competitor ASICs may pressure NVIDIA margins",
            "Macro rates remain elevated for growth tech",
            "Guidance mixed on China exposure",
        ]
        session = run_committee(
            self.store,
            self.record,
            "NVIDIA valuation outlook earnings risk",
            domain="finance",
            evidence=evidence,
            model_slots={
                "fundamental_analyst": "local-slot-fundamentals",
                "bear_case": "local-slot-bear",
            },
        )
        positions = session["positions"]
        self.assertGreaterEqual(len(positions), 3)
        claims = {p["claim"] for p in positions}
        # Role-specific claim templates → not five identical clones.
        self.assertGreaterEqual(len(claims), 2)
        slice_fps = {p["evidence_slice_fingerprint"] for p in positions}
        self.assertGreaterEqual(len(slice_fps), 2)
        prompt_fps = {p["prompt_fingerprint"] for p in positions}
        self.assertGreaterEqual(len(prompt_fps), 2)
        consensus = session["consensus"]
        self.assertIn("divergence", consensus)
        self.assertFalse(consensus["divergence"]["clone_risk"])
        self.assertIn("claim_marks", consensus)
        self.assertEqual(session.get("claim_marks"), consensus["claim_marks"])
        # Dynamic slots applied where configured.
        fund = next(p for p in positions if p["agent"] == "fundamental_analyst")
        bear = next(p for p in positions if p["agent"] == "bear_case")
        self.assertEqual(fund["model_id_slot"], "local-slot-fundamentals")
        self.assertEqual(bear["model_id_slot"], "local-slot-bear")
        # Different evidence content in slices for fund vs bear.
        self.assertNotEqual(fund["evidence_used"], bear["evidence_used"])
        # Persisted claim_marks reload from store consensus.
        loaded = self.store.get_committee(session["id"])
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertIn("claim_marks", loaded["consensus"])

    def test_role_prompts_diverge(self) -> None:
        from gen2.committee import role_prompt

        a = role_prompt("skeptic", "X", ["e1"], focus="challenge")
        b = role_prompt("primary_researcher", "X", ["e1"], focus="broad")
        self.assertNotEqual(a, b)
        self.assertIn("Stance directive", a)
        self.assertIn("falsification", a.lower())


if __name__ == "__main__":
    unittest.main()
