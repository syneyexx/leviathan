"""Unit tests for Chat → Brain knowledge activation event mapping."""

from __future__ import annotations

import unittest
from typing import Any


class _FakeObs:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def emit(self, category: str, name: str, **kwargs: Any) -> dict[str, Any]:
        row = {"category": category, "name": name, **kwargs}
        self.calls.append(row)
        return row


class KnowledgeActivationEventsTests(unittest.TestCase):
    def test_maps_document_and_memory_ids(self) -> None:
        from Data.modules.brain.activation_events import brain_node_ids_from_hits

        ids = brain_node_ids_from_hits(
            knowledge_hits=[{"id": "doc-1"}, {"document_id": "doc-2"}, {"id": "doc-1"}],
            memory_hits=[{"memory_id": "m1"}, {"id": "m2"}],
        )
        self.assertEqual(
            ids,
            [
                "knowledge:document:doc-1",
                "knowledge:document:doc-2",
                "memory:m1",
                "memory:m2",
            ],
        )

    def test_document_identity_wins_over_chunk_identity(self) -> None:
        from Data.modules.brain.activation_events import brain_node_ids_from_hits

        self.assertEqual(
            brain_node_ids_from_hits(knowledge_hits=[{"id": "chunk-9", "document_id": "doc-1"}]),
            ["knowledge:document:doc-1"],
        )

    def test_emit_without_identifiers_clears_node_ids(self) -> None:
        from Data.modules.brain.activation_events import emit_knowledge_activation

        obs = _FakeObs()
        emit_knowledge_activation(
            obs,
            conversation_id="c1",
            request_id="r1",
            run_id="run-1",
            phase="complete",
            knowledge_hits=[{"id": "should-not-appear"}],
            hit_count=3,
            identifiers_available=False,
        )
        self.assertEqual(len(obs.calls), 1)
        payload = obs.calls[0]["payload"]
        self.assertEqual(obs.calls[0]["category"], "brain")
        self.assertEqual(obs.calls[0]["name"], "knowledge_activation")
        self.assertEqual(payload["node_ids"], [])
        self.assertFalse(payload["identifiers_available"])
        self.assertEqual(payload["hit_count"], 3)
        self.assertTrue(payload["truth"]["hit_count_alone_is_not_identity"])

    def test_emit_with_hits_sets_brain_node_ids(self) -> None:
        from Data.modules.brain.activation_events import emit_knowledge_activation

        obs = _FakeObs()
        emit_knowledge_activation(
            obs,
            conversation_id="c1",
            request_id="r1",
            run_id="run-1",
            phase="complete",
            knowledge_hits=[{"id": "abc", "title": "T"}],
            memory_hits=[{"memory_id": "mem"}],
        )
        payload = obs.calls[0]["payload"]
        self.assertEqual(
            payload["node_ids"],
            ["knowledge:document:abc", "memory:mem"],
        )
        self.assertTrue(payload["identifiers_available"])


if __name__ == "__main__":
    unittest.main()
