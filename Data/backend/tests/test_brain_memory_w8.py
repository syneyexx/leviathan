"""W8 — Brain/Memory/Experience unification: trust, consolidation, skills, no Brain bypass."""

from __future__ import annotations

import unittest
from unittest import mock

from Data.modules.brain import BrainAccessFacade, BrainContextRequest
from Data.modules.brain.contracts import BrainEvidenceRef, BrainKnowledgeRef, BrainMemoryRef
from Data.modules.cognition import PerceptionService, Skill, SkillLibrary
from Data.modules.memory import (
    MemoryConsolidator,
    MemoryTrustState,
    normalize_trust_state,
)


class MemoryTrustStateTests(unittest.TestCase):
    def test_normalize_legacy_and_canonical(self) -> None:
        self.assertEqual(normalize_trust_state("model_output"), MemoryTrustState.AGENT_PROPOSED)
        self.assertEqual(normalize_trust_state("explicit"), MemoryTrustState.USER_STATED)
        self.assertEqual(normalize_trust_state("verified"), MemoryTrustState.VERIFIED)
        self.assertEqual(
            normalize_trust_state(MemoryTrustState.CONFLICTED),
            MemoryTrustState.CONFLICTED,
        )
        self.assertEqual(normalize_trust_state("unknown_x"), MemoryTrustState.AGENT_PROPOSED)


class ConsolidationTests(unittest.TestCase):
    def test_confidence_never_becomes_verified_truth(self) -> None:
        consolidator = MemoryConsolidator()
        episodic = [
            {
                "memory_id": "e1",
                "kind": "EPISODIC",
                "content": "User prefers dark mode for trading dashboards",
                "trust": "model_output",
                "confidence": 0.99,
            },
            {
                "memory_id": "e2",
                "kind": "EPISODIC",
                "content": "User prefers dark mode for trading screens",
                "trust": "agent",
                "confidence": 0.95,
            },
        ]
        result = consolidator.consolidate(episodic, min_cluster_size=2)
        self.assertGreaterEqual(len(result.candidates), 1)
        cand = result.candidates[0]
        self.assertEqual(cand.trust_state, MemoryTrustState.AGENT_PROPOSED)
        self.assertTrue(cand.admitted)
        self.assertIn("agent_proposed", cand.admission_reason)
        self.assertTrue(cand.public_dict()["truth"]["model_confidence_is_not_memory_truth"])

    def test_contradiction_blocks_admission(self) -> None:
        consolidator = MemoryConsolidator()
        episodic = [
            {"memory_id": "a", "kind": "EPISODIC", "content": "API base is not production"},
            {"memory_id": "b", "kind": "EPISODIC", "content": "API base is not live"},
        ]
        existing = [{"memory_id": "s1", "content": "API base is production"}]
        result = consolidator.consolidate(episodic, existing_semantic=existing, min_cluster_size=2)
        self.assertTrue(result.candidates)
        self.assertFalse(result.candidates[0].admitted)
        self.assertEqual(result.candidates[0].admission_reason, "contradiction_pending")


class SkillLibraryTests(unittest.TestCase):
    def test_derive_only_from_verified_repeats(self) -> None:
        lib = SkillLibrary()
        derived = lib.derive_from_verified_runs(
            [
                {
                    "run_id": "r1",
                    "verification_status": "VERIFIED",
                    "domain": "coding",
                    "goal": "add unit test",
                    "steps": ["inspect", "edit", "test"],
                    "capabilities": ["workspace.edit"],
                    "success": True,
                },
                {
                    "run_id": "r2",
                    "verification_status": "PASSED",
                    "domain": "coding",
                    "goal": "add unit test",
                    "steps": ["inspect", "edit", "test", "verify"],
                    "capabilities": ["workspace.edit", "workspace.test"],
                    "success": True,
                },
                {
                    "run_id": "r3",
                    "verification_status": "FAILED",
                    "domain": "coding",
                    "goal": "add unit test",
                    "success": False,
                },
            ],
            min_repeats=2,
        )
        self.assertEqual(len(derived), 1)
        skill = derived[0]
        self.assertIsInstance(skill, Skill)
        self.assertEqual(skill.attempt_count, 2)
        self.assertEqual(skill.success_count, 2)
        self.assertEqual(skill.measured_success_rate, 1.0)
        self.assertEqual(skill.trust_state, "VERIFIED")
        self.assertTrue(skill.public_dict()["truth"]["no_hidden_cot"])
        self.assertNotIn("cot", skill.public_dict())
        self.assertNotIn("reasoning", skill.public_dict())


class PerceptionBrainPathTests(unittest.TestCase):
    def test_bound_brain_skips_private_stores(self) -> None:
        knowledge_store = mock.Mock()
        knowledge_store.search = mock.Mock(return_value=[{"id": "priv-k", "content": "PRIVATE_K"}])
        memory_store = mock.Mock()
        memory_store.search = mock.Mock(return_value=[{"id": "priv-m", "content": "PRIVATE_M"}])
        evidence_service = mock.Mock()
        evidence_service.list = mock.Mock(return_value=[{"id": "priv-e", "summary": "PRIVATE_E"}])

        brain = BrainAccessFacade(
            knowledge_search=lambda q, limit=4: [
                {"id": "bk1", "content": "via brain knowledge about trading"},
            ],
            memory_search=lambda q, limit=4: [
                {
                    "memory_id": "bm1",
                    "content": "via brain memory preference",
                    "trust": "USER_STATED",
                },
            ],
            evidence_list=lambda limit=4: [
                {"id": "be1", "summary": "via brain evidence", "status": "VERIFIED"},
            ],
        )
        svc = PerceptionService(
            knowledge_store=knowledge_store,
            memory_store=memory_store,
            evidence_service=evidence_service,
            brain_access=brain,
        )
        snap = svc.perceive("trading preference", budgets={"knowledge": 2, "memory": 2, "evidence": 2})
        authorities = {i.authority for i in snap.items}
        self.assertIn("brain/knowledge", authorities)
        self.assertIn("brain/memory", authorities)
        self.assertIn("brain/evidence", authorities)
        knowledge_store.search.assert_not_called()
        memory_store.search.assert_not_called()
        summaries = " ".join(i.summary for i in snap.items)
        self.assertIn("via brain", summaries)
        self.assertNotIn("PRIVATE_K", summaries)
        mem_items = [i for i in snap.items if i.authority == "brain/memory"]
        self.assertTrue(mem_items)
        self.assertEqual(mem_items[0].verification_status, "USER_STATED")

    def test_unbound_brain_uses_private_stores(self) -> None:
        memory_store = mock.Mock()
        memory_store.search = mock.Mock(
            return_value=[{"id": "m1", "content": "direct memory hit", "trust": "explicit"}]
        )
        svc = PerceptionService(memory_store=memory_store)
        snap = svc.perceive("hit", budgets={"memory": 2, "knowledge": 0, "evidence": 0})
        memory_store.search.assert_called()
        self.assertTrue(any(i.authority == "memory" for i in snap.items))

    def test_brain_facade_normalizes_memory_trust(self) -> None:
        facade = BrainAccessFacade(
            memory_search=lambda q, limit=4: [
                {"memory_id": "x", "content": "model said so", "trust": "model_output"},
            ],
        )
        ctx = facade.gather(
            BrainContextRequest(
                goal="said",
                queries=["said"],
                result_limits={"memory": 2, "knowledge": 0, "evidence": 0},
                include_evidence=False,
            )
        )
        self.assertEqual(len(ctx.memory), 1)
        self.assertIsInstance(ctx.memory[0], BrainMemoryRef)
        self.assertEqual(ctx.memory[0].trust, "AGENT_PROPOSED")


if __name__ == "__main__":
    unittest.main()
