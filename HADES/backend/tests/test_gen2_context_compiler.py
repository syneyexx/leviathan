"""Characterization tests for Gen2 Context Compiler 2.0 extraction."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.context_compiler import compile_context, entity_key, estimate_tokens
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class ContextCompilerModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "context.db"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_estimate_tokens_approx_chars_4(self) -> None:
        self.assertEqual(estimate_tokens(""), 1)
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertEqual(estimate_tokens("abcdefgh"), 2)
        self.assertEqual(estimate_tokens("a" * 40), 10)

    def test_entity_key_stable(self) -> None:
        self.assertEqual(entity_key("NVIDIA ships GPUs"), entity_key("gpus NVIDIA ships"))
        self.assertEqual(entity_key("hi"), "misc")

    def test_compile_dedupe_budget_and_estimate_labels(self) -> None:
        items = [
            {
                "item_id": "a",
                "kind": "knowledge",
                "content": "NVIDIA ships GPUs for AI training." * 20,
                "reliability": 0.9,
                "usefulness": 0.9,
                "source": "k1",
            },
            {
                "item_id": "b",
                "kind": "knowledge",
                "content": "NVIDIA ships GPUs for AI training." * 20,
                "reliability": 0.9,
                "usefulness": 0.9,
                "source": "k1",
            },
            {
                "item_id": "c",
                "kind": "memory",
                "content": "Old rumor: NVIDIA is bankrupt.",
                "reliability": 0.2,
                "usefulness": 0.4,
                "source": "m1",
                "contradiction_group": "nvidia",
            },
            {
                "item_id": "d",
                "kind": "evidence",
                "content": "NVIDIA is not bankrupt; revenue grew.",
                "reliability": 0.8,
                "usefulness": 0.8,
                "source": "e1",
                "contradiction_group": "nvidia",
            },
        ]
        pack = compile_context(
            self.store,
            goal="NVIDIA intel",
            items=items,
            max_tokens=200,
            persist=True,
        )
        kept_ids = {i["item_id"] for i in pack["kept"]}
        self.assertNotIn("b", kept_ids)
        self.assertLessEqual(pack["used_tokens"], pack["max_tokens"])
        self.assertTrue(pack["tokenizer_estimate"])
        self.assertEqual(pack["tokenizer"], "approx_chars_4")
        self.assertTrue(pack.get("not_provider_billing"))
        self.assertIn("estimate", (pack.get("token_accounting") or "").lower())
        self.assertTrue(self.store.get_context_pack(pack["id"]))

    def test_full_request_budget_and_selection_explain(self) -> None:
        pack = compile_context(
            self.store,
            goal="budget explain",
            items=[
                {"content": "alpha evidence " * 40, "kind": "evidence", "reliability": 0.9, "source": "a"},
                {"content": "beta noise " * 40, "kind": "other", "reliability": 0.4, "source": "b"},
            ],
            max_tokens=2000,
            request_budget_tokens=1000,
            system_reserve_tokens=100,
            response_reserve_tokens=200,
            persist=False,
        )
        self.assertEqual(pack["budget_reserve"]["mode"], "full_request_budget")
        self.assertEqual(pack["max_tokens"], 700)
        self.assertIn("kept_ids", pack["selection_explain"])
        self.assertIn("drop_reasons", pack["selection_explain"])
        self.assertTrue(pack["tokenizer_estimate"])
        self.assertTrue(pack["not_provider_billing"])

    def test_invalid_score_raises(self) -> None:
        with self.assertRaises(ValueError):
            compile_context(
                self.store,
                goal="bad",
                items=[{"content": "x", "reliability": 1.5}],
                persist=False,
            )

    def test_services_delegate(self) -> None:
        svc = Gen2Services(self.store, data_root=Path(self.temp.name))
        self.assertEqual(svc.estimate_tokens("abcdefgh"), 2)
        pack = svc.compile_context(
            goal="delegate",
            items=[{"content": "hello world evidence", "kind": "evidence", "usefulness": 0.9}],
            max_tokens=64,
            persist=False,
        )
        self.assertTrue(pack["tokenizer_estimate"])
        self.assertTrue(pack["not_provider_billing"])
        self.assertEqual(pack["tokenizer"], "approx_chars_4")


if __name__ == "__main__":
    unittest.main()
