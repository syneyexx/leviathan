"""Non-dumping local RAG packing and provenance labels."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.retrieval import RetrievalHit, pack_hits_non_dumping


def _hit(hit_id: str, kind: str, score: float, chars: int, provenance: str | None = None) -> RetrievalHit:
    return RetrievalHit(
        hit_id=hit_id,
        kind=kind,  # type: ignore[arg-type]
        content=("x" * chars),
        provenance=provenance or f"{kind}:{hit_id}",
        score=score,
        reasons=[f"test:{hit_id}"],
    )


class NonDumpingPackTests(unittest.TestCase):
    def test_respects_char_and_hit_budget(self) -> None:
        hits = [_hit(f"m{i}", "memory", 1.0 - i * 0.01, 2_000) for i in range(10)]
        packed, meta = pack_hits_non_dumping(hits, max_hits=4, max_chars_total=3_000, max_chars_per_hit=800)
        self.assertLessEqual(len(packed), 4)
        self.assertLessEqual(meta["used_chars"], 3_000 + 50)
        self.assertTrue(meta["truncated"] or meta["dropped_hits"] > 0)
        self.assertTrue(meta["provenance_labels"])
        for item in packed:
            self.assertLessEqual(len(item.content), 800)

    def test_diversifies_kinds_before_filling(self) -> None:
        hits = [
            _hit("m1", "memory", 1.0, 200),
            _hit("m2", "memory", 0.99, 200),
            _hit("m3", "memory", 0.98, 200),
            _hit("k1", "knowledge", 0.5, 200),
            _hit("w1", "workspace", 0.4, 200),
        ]
        packed, meta = pack_hits_non_dumping(hits, max_hits=4, max_chars_total=10_000, max_chars_per_hit=500)
        kinds = {item.kind for item in packed}
        self.assertIn("memory", kinds)
        self.assertTrue("knowledge" in kinds or "workspace" in kinds)
        self.assertEqual(meta["packed_hits"], len(packed))
        labels = {row["label"] for row in meta["provenance_labels"]}
        self.assertTrue(labels)


if __name__ == "__main__":
    unittest.main()
