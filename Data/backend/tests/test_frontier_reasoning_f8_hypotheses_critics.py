"""F8 — HypothesisBoard + named CriticMesh (public, not private CoT)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.backend.migrations import MigrationRunner
from Data.modules.cognition.critic_mesh import CriticMesh
from Data.modules.cognition.hypotheses import (
    ConfidenceBand,
    HypothesisBoard,
    HypothesisStatus,
    hypothesis_board_from_mapping,
)
from Data.modules.cognition.runtime import CognitiveRuntime
from Data.modules.cognition.store import CognitionStore
from Data.modules.cognition.types import CognitiveRunStatus


class HypothesisBoardContractTests(unittest.TestCase):
    def test_seed_branch_and_public_dict(self) -> None:
        board = HypothesisBoard()
        seeded = board.seed_from_task(
            assumptions=["server DNS is broken"],
            unknowns=["which nameserver"],
            domain="debugging",
        )
        self.assertGreaterEqual(len(seeded), 2)
        parent = seeded[0]
        child = board.branch(parent.hypothesis_id, "Resolver cache is stale", domain="debugging")
        self.assertIsNotNone(child)
        assert child is not None
        self.assertEqual(child.parent_id, parent.hypothesis_id)
        self.assertIn(child.hypothesis_id, parent.branch_ids)
        public = board.public_dict()
        self.assertTrue(public["truth"]["hypothesis_board_is_public"])
        self.assertTrue(public["truth"]["not_private_cot"])
        self.assertTrue(public["truth"]["deep_branched"])
        self.assertGreaterEqual(public["branch_count"], 1)
        self.assertGreaterEqual(public["open_count"], 2)
        restored = hypothesis_board_from_mapping(public)
        self.assertEqual(len(restored.items), len(board.items))
        self.assertEqual(
            restored.get(child.hypothesis_id).parent_id,  # type: ignore[union-attr]
            parent.hypothesis_id,
        )

    def test_observation_evidence_updates_status(self) -> None:
        board = HypothesisBoard()
        hyp = board.add("cache miss causes latency", prior_plausibility=0.5, domain="debugging")
        touched = board.apply_observation_evidence(
            observation_id="obs-1",
            summary="cache miss causes latency spike confirmed",
            success=True,
            evidence_refs=["ev-1"],
        )
        self.assertIn(hyp.hypothesis_id, touched)
        self.assertIn("obs-1", hyp.supporting_evidence_ids)
        # Second support → SUPPORTED
        board.apply_observation_evidence(
            observation_id="obs-2",
            summary="cache miss causes latency again",
            success=True,
        )
        self.assertEqual(hyp.current_status, HypothesisStatus.SUPPORTED)
        self.assertIn(hyp.confidence_band, {ConfidenceBand.MODERATE, ConfidenceBand.STRONG})

    def test_confidence_bands_not_fake_precision(self) -> None:
        board = HypothesisBoard()
        hyp = board.add("maybe X", prior_plausibility=0.87)
        public = hyp.public_dict()
        self.assertTrue(public["truth"]["confidence_band_is_not_precise_probability"])
        self.assertNotIn("0.87", str(public.get("confidence_band")))


class CriticMeshContractTests(unittest.TestCase):
    def test_named_domain_critics_and_priority(self) -> None:
        mesh = CriticMesh()
        ids = [getattr(c, "critic_id") for c in mesh.critics]
        self.assertIn("evidence_coverage", ids)
        self.assertIn("consistency", ids)
        self.assertIn("risk_gate", ids)
        self.assertIn("completeness", ids)
        self.assertIn("freshness", ids)
        self.assertIn("working_memory", ids)
        report = mesh.evaluate(
            {
                "requires_research": True,
                "evidence_coverage": 0.1,
                "open_hypothesis_count": 2,
                "failure_observation_count": 2,
                "risk_class": "HIGH",
                "verification_passed": False,
            }
        )
        public = report.public_dict()
        self.assertTrue(public["truth"]["critic_mesh_is_named_domain_critics"])
        self.assertTrue(public["truth"]["not_a_second_runtime"])
        self.assertTrue(public["truth"]["not_private_cot"])
        self.assertGreaterEqual(public["finding_count"], 2)
        # replan / verify outrank retrieve
        self.assertIn(report.recommend, {"replan", "verify"})
        self.assertEqual(len(report.critics_run), len(mesh.critics))

    def test_continue_when_clean(self) -> None:
        mesh = CriticMesh()
        report = mesh.evaluate(
            {
                "evidence_coverage": 0.9,
                "contradiction_density": 0.0,
                "open_hypothesis_count": 0,
                "risk_class": "LOW",
                "verification_passed": True,
                "working_memory_saturation": 0.1,
                "failure_observation_count": 0,
            }
        )
        self.assertEqual(report.recommend, "continue")
        self.assertEqual(report.findings, ())


class RuntimeHypothesisCriticTests(unittest.TestCase):
    def test_submit_seeds_board_and_status_exposes(self) -> None:
        runtime = CognitiveRuntime(enabled=True, shadow=True, iterative=False)
        status = runtime.submit(
            "Debug why the latest cache miss causes latency on production",
            run=False,
        )
        self.assertIn("hypothesis_board", status)
        board = status["hypothesis_board"]
        self.assertTrue(status["truth"]["hypothesis_board_is_public"])
        self.assertTrue(status["truth"]["critic_mesh_is_named_domain_critics"])
        self.assertTrue(board["truth"]["deep_branched"])
        # Assumptions/unknowns from TaskModel may seed items; board contract always present.
        self.assertIn("items", board)
        self.assertIn("open_count", board)

    def test_process_critic_uses_named_mesh(self) -> None:
        runtime = CognitiveRuntime(enabled=True, shadow=True, iterative=False)
        status = runtime.submit("Research the latest fusion energy contradictions", run=False)
        run_id = status["run_id"]
        state = runtime._require(run_id)
        state.hypothesis_board.add("tokamak claim X", domain="research")
        # Force CRITIQUING-compatible status
        state.status = CognitiveRunStatus.REASONING
        out = runtime._process_critic(state)
        self.assertIn("critics_run", out)
        self.assertIn("findings", out)
        self.assertTrue(out["truth"]["critic_mesh_is_named_domain_critics"])
        self.assertIsNotNone(state.last_critic_report)
        self.assertIn(out["recommend"], {"continue", "retrieve", "replan", "verify", "compact"})

    def test_persist_and_hydrate_hypothesis_board(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "cognition.db"
            MigrationRunner(db).apply_all()
            store = CognitionStore(db_path=db)

            runtime = CognitiveRuntime(
                enabled=True,
                shadow=True,
                iterative=False,
                store=store,
            )
            status = runtime.submit("Investigate DNS failure hypotheses", run=False)
            run_id = status["run_id"]
            live = runtime._require(run_id)
            parent = live.hypothesis_board.add("DNS resolver broken", domain="debugging")
            live.hypothesis_board.branch(parent.hypothesis_id, "Only IPv6 path fails")
            live.status = CognitiveRunStatus.SHADOW
            live.last_critic_report = {
                "recommend": "retrieve",
                "reason": "test",
                "findings": [],
                "critics_run": ["evidence_coverage"],
            }
            runtime._persist_update(live, final=True)

            runtime._runs.clear()
            hydrated = runtime._hydrate_from_store(run_id)
            self.assertGreaterEqual(len(hydrated.hypothesis_board.items), 2)
            self.assertGreaterEqual(hydrated.hypothesis_board.public_dict()["branch_count"], 1)
            self.assertEqual(hydrated.last_critic_report["recommend"], "retrieve")
            public = hydrated.public_status()
            self.assertTrue(public["hypothesis_board"]["truth"]["hypothesis_board_is_public"])
            store.close()


if __name__ == "__main__":
    unittest.main()
