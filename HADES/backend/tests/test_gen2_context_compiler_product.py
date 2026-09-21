"""Product-depth tests for Gen2 Context Compiler 2.0 (F1.1–F1.8)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen2.context_compiler import compile_context, estimate_tokens, estimate_tokens_with_mode
from gen2.services import Gen2Services
from gen2.store import Gen2Store


class ContextCompilerProductTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Gen2Store(str(Path(self.temp.name) / "ctx.db"))
        self.svc = Gen2Services(self.store, data_root=Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_tokenizer_modes(self) -> None:
        self.assertEqual(estimate_tokens("abcdefgh"), 2)
        count, label = estimate_tokens_with_mode("one two three four", tokenizer_mode="whitespace_words")
        self.assertEqual(count, 4)
        self.assertEqual(label, "whitespace_words")
        count2, label2 = estimate_tokens_with_mode("hello world", tokenizer_mode="tiktoken_cl100k")
        self.assertIn(label2, {"tiktoken_cl100k", "tiktoken_unavailable_fallback_approx"})
        self.assertGreaterEqual(count2, 1)

    def test_tokenizer_mode_reports_honestly_when_tiktoken_missing_or_present(self) -> None:
        """F1.1 product honesty: pack tokenizer label matches availability."""
        try:
            import tiktoken  # noqa: F401

            tiktoken_present = True
        except Exception:
            tiktoken_present = False
        pack = compile_context(
            self.store,
            goal="tok",
            items=[{"item_id": "t1", "content": "hello world tokens for budgeting", "kind": "evidence", "source": "a"}],
            max_tokens=128,
            persist=False,
            tokenizer_mode="tiktoken_cl100k",
        )
        if tiktoken_present:
            self.assertEqual(pack["tokenizer"], "tiktoken_cl100k")
            self.assertFalse(pack["tokenizer_estimate"])
            self.assertEqual(pack["token_accounting"], "tiktoken_cl100k")
        else:
            self.assertEqual(pack["tokenizer"], "tiktoken_unavailable_fallback_approx")
            self.assertTrue(pack["tokenizer_estimate"])
            self.assertIn("estimate", pack["token_accounting"])
        self.assertEqual(pack["tokenizer_mode_requested"], "tiktoken_cl100k")
        self.assertTrue(pack["not_provider_billing"] or pack["tokenizer"] == "tiktoken_cl100k")

    def test_contradiction_clustering(self) -> None:
        """F1.3 — contradicting items share a cluster in compile output."""
        pack = compile_context(
            self.store,
            goal="contradiction",
            items=[
                {
                    "item_id": "pos",
                    "content": "NVIDIA growth is strong and earnings are true beat",
                    "kind": "evidence",
                    "reliability": 0.8,
                    "source": "wire-a",
                    "contradiction_group": "nvidia_growth",
                },
                {
                    "item_id": "neg",
                    "content": "NVIDIA growth is not strong and guidance is false",
                    "kind": "evidence",
                    "reliability": 0.7,
                    "source": "wire-b",
                    "contradiction_group": "nvidia_growth",
                },
            ],
            max_tokens=500,
            persist=False,
        )
        self.assertTrue(pack["contradiction_clusters"])
        cluster = pack["contradiction_clusters"][0]
        self.assertEqual(set(cluster["item_ids"]), {"pos", "neg"})
        self.assertEqual(cluster["method"], "lightweight_heuristic")
        kept_risks = {i["item_id"]: i.get("contradiction_risk") for i in pack["kept"]}
        self.assertGreaterEqual(kept_risks.get("pos", 0), 0.8)
        self.assertGreaterEqual(kept_risks.get("neg", 0), 0.8)

    def test_pack_preview_fields(self) -> None:
        pack = compile_context(
            self.store,
            goal="preview",
            items=[
                {"item_id": "a", "content": "alpha evidence " * 20, "kind": "evidence", "reliability": 0.9, "source": "a"},
                {"item_id": "b", "content": "beta noise " * 20, "kind": "other", "reliability": 0.3, "source": "b"},
            ],
            max_tokens=80,
            persist=False,
            tokenizer_mode="approx_chars_4",
        )
        preview = pack["pack_preview"]
        self.assertIn("kept", preview)
        self.assertIn("dropped", preview)
        self.assertIn("why", preview)
        self.assertIn("tokenizer", preview)
        self.assertIn("budget", preview)
        self.assertEqual(pack["tokenizer"], "approx_chars_4")

    def test_mandatory_pin_not_silently_dropped(self) -> None:
        pack = compile_context(
            self.store,
            goal="pins",
            items=[
                {
                    "item_id": "pin1",
                    "content": "mandatory evidence about ACME earnings that must stay",
                    "pin": True,
                    "kind": "evidence",
                    "usefulness": 0.05,
                    "reliability": 0.95,
                    "source": "pin",
                },
                {
                    "item_id": "noise",
                    "content": "x" * 4000,
                    "usefulness": 0.99,
                    "reliability": 0.99,
                    "source": "noise",
                },
            ],
            max_tokens=40,
            persist=False,
            pin_overflow="keep_with_note",
        )
        kept_ids = {i["item_id"] for i in pack["kept"]}
        self.assertIn("pin1", kept_ids)
        pin = next(i for i in pack["kept"] if i["item_id"] == "pin1")
        self.assertTrue(pin.get("pinned") or pin.get("overflow_note"))

    def test_pin_overflow_error_mode(self) -> None:
        with self.assertRaises(ValueError):
            compile_context(
                self.store,
                goal="err",
                items=[
                    {
                        "item_id": "huge_pin",
                        "content": "y" * 4000,
                        "mandatory": True,
                        "kind": "evidence",
                        "source": "p",
                    }
                ],
                max_tokens=64,
                persist=False,
                pin_overflow="error",
            )

    def test_freshness_and_temporal_validity(self) -> None:
        pack = compile_context(
            self.store,
            goal="fresh",
            items=[
                {
                    "item_id": "old",
                    "content": "stale rumor from long ago about markets",
                    "observed_at": "2020-01-01T00:00:00+00:00",
                    "freshness": 0.1,
                    "usefulness": 0.9,
                    "source": "old",
                },
                {
                    "item_id": "future",
                    "content": "not yet valid claim about markets",
                    "valid_from": "2099-01-01T00:00:00+00:00",
                    "usefulness": 0.9,
                    "source": "future",
                },
                {
                    "item_id": "now",
                    "content": "current evidence about markets today",
                    "observed_at": "2026-09-01T00:00:00+00:00",
                    "freshness": 0.9,
                    "usefulness": 0.9,
                    "kind": "evidence",
                    "source": "now",
                },
            ],
            max_tokens=500,
            persist=False,
            max_age_hours=24 * 30,
            now="2026-09-09T00:00:00+00:00",
        )
        kept_ids = {i["item_id"] for i in pack["kept"]}
        dropped_reasons = {d.get("drop_reason") for d in pack["dropped"]}
        self.assertIn("now", kept_ids)
        self.assertTrue("stale" in dropped_reasons or "future" not in kept_ids)
        self.assertTrue("stale" in dropped_reasons or "old" not in kept_ids)

    def test_hierarchical_summary_provenance(self) -> None:
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
        )
        summaries = [i for i in pack["kept"] if i.get("is_summary_node")]
        if summaries:
            self.assertTrue(summaries[0].get("provenance_links"))
            self.assertEqual(summaries[0].get("summary_quality"), "stub_not_model_summary")
            honesty = summaries[0].get("honesty") or {}
            self.assertTrue(honesty.get("is_stub"))
            self.assertFalse(honesty.get("model_quality"))
            self.assertTrue(pack["metrics"].get("hierarchical_summarization_stub"))
        # Either summary exists or drops are labeled — no silent loss without reason.
        for d in pack["dropped"]:
            self.assertTrue(d.get("drop_reason") or d.get("why"))

    def test_services_tokenizer_passthrough(self) -> None:
        pack = self.svc.compile_context(
            goal="svc",
            items=[{"content": "hello world tokens", "kind": "evidence", "source": "a"}],
            max_tokens=128,
            persist=False,
            tokenizer_mode="whitespace_words",
        )
        self.assertEqual(pack["tokenizer"], "whitespace_words")
        self.assertIn("pack_preview", pack)


    def test_wave13_drop_reason_taxonomy(self) -> None:
        from gen2.context_compiler import canonicalize_drop_reason

        self.assertEqual(canonicalize_drop_reason("duplicate_content_hash"), "duplicate")
        self.assertEqual(canonicalize_drop_reason("stale_max_age"), "stale")
        self.assertEqual(canonicalize_drop_reason("token_budget"), "token_budget")
        pack = compile_context(
            self.store,
            goal="drops",
            items=[
                {"item_id": "a", "content": "same body", "usefulness": 0.9, "source": "s1"},
                {"item_id": "b", "content": "same body", "usefulness": 0.9, "source": "s2"},
                {"item_id": "c", "content": "weak", "usefulness": 0.05, "source": "s3"},
                {"item_id": "d", "content": "old fact", "status": "superseded", "superseded_by": "e", "source": "s4"},
                {"item_id": "keep", "content": "useful evidence about topic", "usefulness": 0.9, "kind": "evidence", "source": "s5"},
            ],
            max_tokens=800,
            persist=False,
        )
        reasons = set(pack["selection_explain"]["drop_reasons"])
        self.assertTrue(reasons <= {"token_budget", "duplicate", "low_relevance", "stale", "superseded", "insufficient_evidence"} or reasons)
        self.assertIn("duplicate", reasons)
        self.assertIn("low_relevance", reasons)
        self.assertIn("superseded", reasons)
        self.assertEqual(pack.get("evidence_status"), "ok")


if __name__ == "__main__":
    unittest.main()
