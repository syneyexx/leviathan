from __future__ import annotations

import unittest

from Data.modules.brain import BrainQueryFacade


class _Doc:
    def __init__(self, id: str, title: str) -> None:
        self._id = id
        self._title = title

    def public_dict(self):
        return {"id": self._id, "title": self._title, "status": "READY", "source": "manual", "created_at": "t"}


class _Evidence:
    def public_dict(self):
        return {
            "evidence_id": "ev1",
            "claim": "claim text",
            "status": "VERIFIED",
            "kind": "ARTIFACT_HASH",
            "created_at": "t",
            "run_id": "run-1",
        }


class BrainFacadeTests(unittest.TestCase):
    def test_bounded_projection_and_edges(self) -> None:
        facade = BrainQueryFacade(
            knowledge_list=lambda: [_Doc("d1", "Doc One"), _Doc("d2", "Doc Two")],
            evidence_list=lambda: [_Evidence()],
            max_nodes=50,
            max_edges=100,
        )
        graph = facade.query(limit=50)
        self.assertGreaterEqual(graph["stats"]["node_count"], 3)
        ids = {n["id"] for n in graph["nodes"]}
        self.assertIn("knowledge:document:d1", ids)
        self.assertIn("evidence:ev1", ids)
        self.assertTrue(graph["truth"]["projection_only"])
        # run edge from evidence
        self.assertTrue(any(e["relation"] == "from_run" for e in graph["edges"]))

    def test_type_filter_and_limit(self) -> None:
        facade = BrainQueryFacade(
            knowledge_list=lambda: [_Doc(f"d{i}", f"T{i}") for i in range(20)],
            max_nodes=100,
        )
        graph = facade.query(types=["knowledge.document"], limit=5)
        self.assertLessEqual(len(graph["nodes"]), 5)
        self.assertTrue(all(n["type"] == "knowledge.document" for n in graph["nodes"]))


if __name__ == "__main__":
    unittest.main()
