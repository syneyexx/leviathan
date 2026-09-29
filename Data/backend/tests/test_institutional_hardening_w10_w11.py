"""Wave 10–11 — claim relations, independent verifier, bounded concurrency."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from Data.modules.research.claim_relations import (
    ClaimRelation,
    normalize_claim_relation,
    relation_from_entailment_status,
)
from Data.modules.research.concurrency import BoundedConcurrencyGate, clamp_concurrency
from Data.modules.research.graph import ClaimEvidenceGraphBuilder, citation_entailment_check
from Data.modules.research.independent_verifier import IndependentClaimVerifier
from Data.modules.research.store import ResearchStore
from Data.modules.research.types import (
    ClaimStatus,
    ResearchClaim,
    ResearchEvidence,
    ResearchSource,
    SourceType,
)


class ClaimRelationVocabularyTests(unittest.TestCase):
    def test_closed_vocabulary(self) -> None:
        allowed = {r.value for r in ClaimRelation}
        self.assertEqual(
            allowed,
            {"SUPPORTS", "CONTRADICTS", "QUALIFIES", "BACKGROUND", "INSUFFICIENT"},
        )

    def test_legacy_aliases(self) -> None:
        self.assertEqual(normalize_claim_relation("supports"), ClaimRelation.SUPPORTS)
        self.assertEqual(normalize_claim_relation("contradicts"), ClaimRelation.CONTRADICTS)
        self.assertEqual(normalize_claim_relation("related"), ClaimRelation.BACKGROUND)

    def test_entailment_mapping(self) -> None:
        self.assertEqual(relation_from_entailment_status("SUPPORTED"), ClaimRelation.SUPPORTS)
        self.assertEqual(relation_from_entailment_status("CONTRADICTED"), ClaimRelation.CONTRADICTS)
        self.assertEqual(
            relation_from_entailment_status("INSUFFICIENT_EVIDENCE"),
            ClaimRelation.INSUFFICIENT,
        )


class IndependentVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ResearchStore(Path(self.tmp.name) / "r.db")
        self.store.initialize()
        self.project = self.store.create_project(
            title="Claim graph",
            topic="Bitcoin launched in 2009",
            project_id="proj-1",
        )
        src = ResearchSource(
            source_id="src-1",
            project_id="proj-1",
            source_type=SourceType.WEB_PAGE,
            title="History",
            original_uri="https://example.com/a",
            canonical_uri="https://example.com/a",
            created_at="2026-01-01T00:00:00+00:00",
        )
        self.store.upsert_source(src)
        ev = ResearchEvidence(
            evidence_id="ev-1",
            project_id="proj-1",
            source_id="src-1",
            span_text="Bitcoin was launched in 2009 by Satoshi Nakamoto.",
            created_at="2026-01-01T00:00:00+00:00",
        )
        self.store.add_evidence(ev)
        claim = ResearchClaim(
            claim_id="cl-1",
            project_id="proj-1",
            proposition="Bitcoin was launched in 2009",
            status=ClaimStatus.SUPPORTED,
            supporting_evidence_ids=["ev-1"],
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        self.store.upsert_claim(claim)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_graph_uses_closed_relations(self) -> None:
        graph = ClaimEvidenceGraphBuilder(self.store).build("proj-1")
        self.assertGreaterEqual(len(graph.edges), 1)
        for edge in graph.edges:
            self.assertIn(edge.relation, {r.value for r in ClaimRelation})
            pub = edge.public_dict()
            self.assertIn(pub["relation"], pub["truth"]["allowed_relations"])

    def test_independent_verifier_report(self) -> None:
        report = IndependentClaimVerifier(self.store).verify_project("proj-1")
        payload = report.public_dict()
        self.assertEqual(payload["cross_model_status"], "UNAVAILABLE")
        self.assertTrue(payload["truth"]["independent_of_authoring_path"])
        self.assertGreaterEqual(payload["counts"]["SUPPORTS"], 1)

    def test_contradiction_detected(self) -> None:
        check = citation_entailment_check(
            "Bitcoin was launched in 2009",
            "Bitcoin was not launched in 2009; it never existed.",
        )
        self.assertEqual(check["status"], "CONTRADICTED")


class BoundedConcurrencyTests(unittest.TestCase):
    def test_clamp(self) -> None:
        self.assertEqual(clamp_concurrency(100, default=4, ceiling=8), 8)
        self.assertEqual(clamp_concurrency(None, default=4, ceiling=8), 4)

    def test_gate_limits_parallelism(self) -> None:
        gate = BoundedConcurrencyGate(max_workers=2, name="test")
        active = 0
        peak = 0
        lock = __import__("threading").Lock()

        def work(_: int) -> int:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return 1

        results = gate.run_bounded(list(range(6)), work)
        self.assertEqual(len(results), 6)
        self.assertLessEqual(peak, 2)
        self.assertEqual(gate.acquisitions, 6)


if __name__ == "__main__":
    unittest.main()
