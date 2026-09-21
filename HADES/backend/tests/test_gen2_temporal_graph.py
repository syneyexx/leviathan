"""Characterization tests for Gen2 Temporal Intelligence Graph extraction."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.services import Gen2Services
from gen2.store import Gen2Store
from gen2.temporal_graph import as_of_beliefs, assert_edge, find_contradictions


class TemporalGraphModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "graph.db"))
        self.events: list[str] = []

        def _record(run_id: str, event_type: str, payload=None, **kwargs):
            self.events.append(event_type)
            return {"run_id": run_id, "event_type": event_type}

        self.record = _record

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_assert_edge_requires_ids(self) -> None:
        with self.assertRaises(ValueError):
            assert_edge(self.store, self.record, {"source_id": "a"})

    def test_as_of_filters_future_knowledge(self) -> None:
        assert_edge(
            self.store,
            self.record,
            {
                "source_id": "ent:nvidia",
                "target_id": "claim:growth",
                "relation_kind": "asserts",
                "valid_from": "2024-01-01T00:00:00Z",
                "valid_until": None,
                "observed_at": "2024-06-01T00:00:00Z",
            },
        )
        assert_edge(
            self.store,
            self.record,
            {
                "source_id": "ent:nvidia",
                "target_id": "claim:risk",
                "relation_kind": "contradicts",
                "contradicts": "claim:growth",
                "valid_from": "2024-01-01T00:00:00Z",
                "observed_at": "2025-01-01T00:00:00Z",
            },
        )
        # Historical analysis at mid-2024 must not see Jan-2025 observation.
        mid = as_of_beliefs(
            self.store,
            "ent:nvidia",
            "2024-07-01T00:00:00Z",
            known_as_of="2024-07-01T00:00:00Z",
        )
        self.assertTrue(mid["queryable"])
        self.assertTrue(mid["bitemporal"])
        targets = {b.get("target_id") for b in mid["beliefs"]}
        self.assertIn("claim:growth", targets)
        self.assertNotIn("claim:risk", targets)

        later = as_of_beliefs(self.store, "ent:nvidia", "2025-02-01T00:00:00Z")
        later_targets = {b.get("target_id") for b in later["beliefs"]}
        self.assertIn("claim:risk", later_targets)
        self.assertTrue(later["contradictions"])

    def test_find_contradictions(self) -> None:
        assert_edge(
            self.store,
            self.record,
            {
                "source_id": "a",
                "target_id": "b",
                "relation_kind": "contradicts",
                "contradicts": "x",
            },
        )
        found = find_contradictions(self.store, "a")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["relation_kind"], "contradicts")

    def test_services_delegate(self) -> None:
        svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        edge = svc.assert_edge({"source_id": "x", "target_id": "y", "relation": "related_to"})
        self.assertTrue(edge["id"])
        beliefs = svc.as_of_beliefs("x", "2099-01-01T00:00:00Z")
        self.assertGreaterEqual(beliefs["count"], 1)
        self.assertTrue(beliefs.get("queryable"))


if __name__ == "__main__":
    unittest.main()
