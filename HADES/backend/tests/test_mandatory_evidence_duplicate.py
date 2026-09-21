"""Regression: mandatory pinned duplicate must not cause insufficient_evidence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gen2.context_compiler import compile_context
from gen2.store import Gen2Store


class MandatoryEvidenceDuplicateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(Path(self.tmp.name) / "g2.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pinned_duplicate_does_not_mark_insufficient_evidence(self) -> None:
        body = "mandatory evidence body that must remain semantically satisfied"
        pack = compile_context(
            self.store,
            goal="dup-pin",
            items=[
                {
                    "item_id": "pin-a",
                    "content": body,
                    "kind": "evidence",
                    "pinned": True,
                    "usefulness": 0.9,
                    "source": "a",
                },
                {
                    "item_id": "pin-b",
                    "content": body,
                    "kind": "evidence",
                    "pinned": True,
                    "usefulness": 0.9,
                    "source": "b",
                },
            ],
            max_tokens=800,
            persist=False,
        )
        # One copy kept; duplicate dropped as duplicate — evidence still OK.
        kept_pins = [i for i in pack["kept"] if i.get("pinned")]
        self.assertGreaterEqual(len(kept_pins), 1)
        drop_reasons = {d.get("drop_reason") for d in pack["dropped"]}
        self.assertIn("duplicate", drop_reasons)
        self.assertEqual(pack.get("evidence_status"), "ok")
        self.assertNotEqual(pack.get("evidence_status"), "insufficient_evidence")

    def test_model_summary_path_when_summarize_fn_works(self) -> None:
        items = [
            {
                "item_id": f"c{i}",
                "content": f"chunk number {i} with unique payload " + ("data " * 40),
                "usefulness": 0.5,
                "reliability": 0.5,
                "source": f"s{i}",
            }
            for i in range(8)
        ]
        pack = compile_context(
            self.store,
            goal="summary",
            items=items,
            max_tokens=120,
            persist=False,
            hierarchical_summarization=True,
            summarize_fn=lambda _prompt: "Model condensed the deferred chunks honestly.",
        )
        summaries = [i for i in pack["kept"] if i.get("is_summary_node")]
        if summaries:
            self.assertEqual(summaries[0].get("summary_quality"), "model_summary")
            self.assertTrue(pack["metrics"].get("hierarchical_summarization_model"))
            self.assertFalse(pack["metrics"].get("hierarchical_summarization_stub"))


if __name__ == "__main__":
    unittest.main()
