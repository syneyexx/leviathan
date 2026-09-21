"""Hierarchical conversation summary cache tests."""

from __future__ import annotations

import unittest

from conversation_summaries import build_hierarchical_history


class ConversationSummaryTests(unittest.TestCase):
    def test_raw_only_for_short_threads(self) -> None:
        messages = [{"id": str(i), "role": "user", "content": f"msg {i}"} for i in range(5)]
        out, meta = build_hierarchical_history(messages, max_recent_raw=12)
        self.assertEqual(meta["mode"], "raw_only")
        self.assertEqual(len(out), 5)

    def test_cached_layers_not_resummarized(self) -> None:
        messages = [
            {"id": str(i), "role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} " + ("x" * 40)}
            for i in range(40)
        ]
        calls = {"n": 0}

        def summarize(_prompt: str) -> str:
            calls["n"] += 1
            return f"summary-{calls['n']}"

        cache: dict = {}
        out1, meta1 = build_hierarchical_history(
            messages, max_recent_raw=8, layer_size=10, cache=cache, summarize_fn=summarize
        )
        self.assertEqual(meta1["mode"], "hierarchical")
        self.assertGreater(calls["n"], 0)
        first_calls = calls["n"]
        out2, meta2 = build_hierarchical_history(
            messages, max_recent_raw=8, layer_size=10, cache=cache, summarize_fn=summarize
        )
        self.assertEqual(calls["n"], first_calls)
        self.assertGreater(meta2["cache_hits"], 0)
        self.assertTrue(any("model_summary" in m["content"] for m in out2 if m["role"] == "system") or out1)

    def test_stub_when_model_unavailable(self) -> None:
        messages = [{"id": str(i), "role": "user", "content": f"msg {i}"} for i in range(25)]

        def boom(_prompt: str) -> str:
            raise RuntimeError("lm unavailable")

        _out, meta = build_hierarchical_history(
            messages, max_recent_raw=5, layer_size=10, summarize_fn=boom
        )
        self.assertIn("stub_not_model_summary", meta["summary_quality_set"])


if __name__ == "__main__":
    unittest.main()
