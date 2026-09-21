"""Phase 11: Exact Brain + Neural Memory dual retrieval."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DualRetrievalTests(unittest.TestCase):
    def test_categories_remain_distinct(self) -> None:
        from neural.dual_retrieval import candidate_to_context_item, retrieve_dual

        result = retrieve_dual(
            "worker shutdown",
            exact_retrieve=lambda _q: [
                {
                    "id": "exact-1",
                    "content": "Join worker threads before closing SQLite (commit abc123).",
                    "score": 0.91,
                    "source_ref": "file:backend/worker.py:120",
                }
            ],
            neural_retrieve=lambda _q: [
                {
                    "id": "neural-1",
                    "content": "This resembles a worker shutdown / atomic persistence failure.",
                    "score": 0.77,
                    "checkpoint_id": "slow-ckpt-9",
                    "domain": "coding",
                }
            ],
        )
        self.assertEqual(result.exact[0].provenance_status, "exact_source")
        self.assertEqual(result.neural[0].provenance_status, "neural_association")
        exact_item = candidate_to_context_item(result.exact[0])
        neural_item = candidate_to_context_item(result.neural[0])
        self.assertEqual(exact_item.kind, "evidence")
        self.assertTrue(exact_item.trusted)
        self.assertEqual(neural_item.kind, "neural_association")
        self.assertFalse(neural_item.trusted)
        self.assertIn("neural_association", neural_item.provenance)

    def test_neural_mislabel_forced_to_association(self) -> None:
        from neural.dual_retrieval import retrieve_dual

        result = retrieve_dual(
            "q",
            neural_retrieve=lambda _q: [
                {
                    "id": "bad",
                    "candidate_type": "exact",  # malicious/mislabel
                    "content": "pretend exact",
                    "score": 0.9,
                    "provenance_status": "exact_source",
                }
            ],
        )
        self.assertEqual(result.neural[0].candidate_type, "neural")
        self.assertEqual(result.neural[0].provenance_status, "neural_association")

    def test_experiment_matrix_abcd_token_estimates(self) -> None:
        from neural.dual_retrieval import compile_dual_context, retrieve_dual

        result = retrieve_dual(
            "deadlock",
            exact_retrieve=lambda _q: [
                {"id": "e1", "content": "Exact lock order: acquire A then B.", "score": 0.95},
                {"id": "e2", "content": "Test: test_worker_pool_deadlock", "score": 0.88},
            ],
            neural_retrieve=lambda _q: [
                {
                    "id": "n1",
                    "content": "Pattern: join workers before DB close.",
                    "score": 0.7,
                    "checkpoint_id": "c1",
                }
            ],
            durable_retrieve=lambda _q: [
                {"id": "d1", "content": "User decision: prefer reversible ops.", "score": 0.6}
            ],
        )
        matrix = compile_dual_context(result, max_chars=2000)
        self.assertEqual(matrix["modes"]["A"]["token_estimate_chars"], 0)
        self.assertGreater(matrix["modes"]["B"]["token_estimate_chars"], 0)
        self.assertGreater(matrix["modes"]["C"]["token_estimate_chars"], 0)
        self.assertGreaterEqual(
            matrix["modes"]["D"]["token_estimate_chars"],
            matrix["modes"]["B"]["token_estimate_chars"],
        )
        self.assertEqual(matrix["modes"]["B"]["neural_kept"], 0)
        self.assertEqual(matrix["modes"]["C"]["exact_kept"], 0)
        self.assertGreaterEqual(matrix["modes"]["D"]["exact_kept"], 1)
        self.assertGreaterEqual(matrix["modes"]["D"]["neural_kept"], 1)
        # D is not assumed better — only measured.
        self.assertIn("token_estimate_chars", matrix["modes"]["D"])

    def test_bounded_selection_does_not_dump_all(self) -> None:
        from neural.dual_retrieval import retrieve_dual

        exact = [{"id": f"e{i}", "content": f"exact row {i} " + ("x" * 20), "score": 1.0 - i * 0.01} for i in range(20)]
        neural = [{"id": f"n{i}", "content": f"neural {i}", "score": 0.5} for i in range(20)]
        result = retrieve_dual(
            "q",
            exact_retrieve=lambda _q: exact,
            neural_retrieve=lambda _q: neural,
            max_exact=3,
            max_neural=2,
        )
        self.assertEqual(len(result.exact), 3)
        self.assertEqual(len(result.neural), 2)

    def test_compiler_items_preserve_provenance_status(self) -> None:
        from neural.dual_retrieval import candidates_to_compiler_items, retrieve_dual

        result = retrieve_dual(
            "q",
            exact_retrieve=lambda _q: [{"id": "e", "content": "exact", "score": 1.0}],
            neural_retrieve=lambda _q: [
                {"id": "n", "content": "assoc", "score": 0.5, "checkpoint_id": "ck"}
            ],
        )
        items = candidates_to_compiler_items(result.all_candidates())
        by_id = {i["id"]: i for i in items}
        self.assertEqual(by_id["e"]["provenance_status"], "exact_source")
        self.assertTrue(by_id["e"]["trusted"])
        self.assertEqual(by_id["n"]["provenance_status"], "neural_association")
        self.assertFalse(by_id["n"]["trusted"])
        self.assertEqual(by_id["n"]["kind"], "neural_association")

    def test_optional_gen2_compile_accepts_packed_items(self) -> None:
        try:
            from gen2.context_compiler import compile_context
            from gen2.store import Gen2Store
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"gen2 unavailable: {exc}")
        from neural.dual_retrieval import candidates_to_compiler_items, retrieve_dual

        result = retrieve_dual(
            "shutdown",
            exact_retrieve=lambda _q: [
                {"id": "e1", "content": "Exact: flush WAL then close.", "score": 0.9, "source_ref": "doc:1"}
            ],
            neural_retrieve=lambda _q: [
                {
                    "id": "n1",
                    "content": "Association: shutdown ordering failure pattern.",
                    "score": 0.6,
                    "checkpoint_id": "ck1",
                }
            ],
        )
        items = candidates_to_compiler_items(result.all_candidates())
        with tempfile.TemporaryDirectory() as tmp:
            store = Gen2Store(str(Path(tmp) / "context.db"))
            packed = compile_context(
                store,
                goal="shutdown ordering",
                items=items,
                max_tokens=512,
                persist=False,
            )
        self.assertIn("kept", packed)
        # Ensure neural content remains labeled if kept.
        joined = json.dumps(packed)
        self.assertIn("neural_association", joined)
        kinds = {str(item.get("kind") or "") for item in packed.get("kept") or []}
        self.assertIn("evidence", kinds)
        self.assertIn("neural_association", kinds)


if __name__ == "__main__":
    unittest.main()
