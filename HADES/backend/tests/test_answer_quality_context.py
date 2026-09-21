"""Tests for context compiler empty selection + protected constraint budgeting."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.chat_context import compiler_pack_to_context_items, context_items_to_compiler_payload
from reasoning.context import budget_context_items
from reasoning.contracts import ContextItem
from reasoning.evidence_coverage import stable_claim_id


class CompilerEmptySelectionTests(unittest.TestCase):
    def test_intentional_empty_does_not_restore_fallback(self) -> None:
        fallback = [
            ContextItem(item_id="a", kind="knowledge", content="rejected", provenance="a", priority=1)
        ]
        out = compiler_pack_to_context_items(
            {"kept": [], "intentional_empty": True},
            fallback=fallback,
        )
        self.assertEqual(out, [])

    def test_missing_kept_falls_back(self) -> None:
        fallback = [
            ContextItem(item_id="a", kind="knowledge", content="orig", provenance="a", priority=1)
        ]
        out = compiler_pack_to_context_items({"status": "error"}, fallback=fallback)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].content, "orig")

    def test_reliability_defaults_unmeasured(self) -> None:
        items = [
            ContextItem(item_id="k", kind="knowledge", content="x", provenance="p", priority=1, trusted=True)
        ]
        row = context_items_to_compiler_payload(items)[0]
        self.assertIsNone(row["reliability"])
        self.assertEqual(row["reliability_basis"], "unmeasured_default")


class ProtectedConstraintBudgetTests(unittest.TestCase):
    def test_late_constraint_survives_budget(self) -> None:
        items = [
            ContextItem(item_id=f"n{i}", kind="knowledge", content=("word " * 100), provenance=f"n{i}", priority=40)
            for i in range(6)
        ]
        items.append(
            ContextItem(
                item_id="constraint_end",
                kind="user_constraint",
                content="Gebruik geen externe netwerkcalls.",
                provenance="user",
                priority=99,
                trusted=True,
                redactable=False,
            )
        )
        kept, report = budget_context_items(items, max_chars=900)
        self.assertTrue(any(i.item_id == "constraint_end" for i in kept))
        self.assertGreaterEqual(report.protected_kept, 1)


class StableClaimIdTests(unittest.TestCase):
    def test_not_python_hash(self) -> None:
        a = stable_claim_id("same claim")
        b = stable_claim_id("same claim")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("claim_"))
        self.assertEqual(len(a), len("claim_") + 16)


if __name__ == "__main__":
    unittest.main()
