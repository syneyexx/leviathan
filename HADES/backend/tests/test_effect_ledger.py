"""Tests for at-least-once effect ledger restart classification."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.effect_ledger import EffectLedger


class EffectLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = EffectLedger(Path(self.tmp.name) / "effects.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_prepared_irreversible_requires_reconciliation(self) -> None:
        rec = self.ledger.prepare(tool="rm", arguments={"path": "x"}, effect_class="fs_delete")
        decision = self.ledger.classify_on_restart(rec.effect_id)
        self.assertEqual(decision["class"], "REQUIRES_RECONCILIATION")

    def test_committed_is_already_committed(self) -> None:
        rec = self.ledger.prepare(tool="echo", arguments={"x": 1}, effect_class="plugin_side_effect")
        self.ledger.mark_committed(rec.effect_id)
        decision = self.ledger.classify_on_restart(rec.effect_id)
        self.assertEqual(decision["class"], "ALREADY_COMMITTED")

    def test_failed_before_effect_is_safe_to_retry(self) -> None:
        rec = self.ledger.prepare(tool="echo", arguments={"x": 1}, effect_class="plugin_side_effect")
        self.ledger.mark_failed(rec.effect_id, detail={"error": "boom", "effect_applied": False, "failure_stage": "before_execute"})
        decision = self.ledger.classify_on_restart(rec.effect_id)
        self.assertEqual(decision["class"], "SAFE_TO_RETRY")

    def test_failed_after_possible_effect_requires_reconciliation(self) -> None:
        rec = self.ledger.prepare(tool="echo", arguments={"x": 1}, effect_class="plugin_side_effect")
        self.ledger.mark_failed(rec.effect_id, detail={"error": "boom", "effect_applied": True, "failure_stage": "after_execute"})
        decision = self.ledger.classify_on_restart(rec.effect_id)
        self.assertEqual(decision["class"], "REQUIRES_RECONCILIATION")

    def test_failed_unknown_effect_state_is_unknown(self) -> None:
        rec = self.ledger.prepare(tool="echo", arguments={"x": 1}, effect_class="plugin_side_effect")
        self.ledger.mark_failed(rec.effect_id, detail={"error": "boom"})
        decision = self.ledger.classify_on_restart(rec.effect_id)
        self.assertEqual(decision["class"], "UNKNOWN_EXTERNAL_STATE")

    def test_contradiction_applied_true_with_before_execute_requires_reconciliation(self) -> None:
        """Reproduced bug: effect_applied=True + failure_stage=before_execute must not be SAFE_TO_RETRY."""
        rec = self.ledger.prepare(tool="echo", arguments={"x": 1}, effect_class="plugin_side_effect")
        self.ledger.mark_failed(
            rec.effect_id,
            detail={"error": "boom", "effect_applied": True, "failure_stage": "before_execute"},
        )
        decision = self.ledger.classify_on_restart(rec.effect_id)
        self.assertEqual(decision["class"], "REQUIRES_RECONCILIATION")
        self.assertEqual(decision["reason"], "contradictory_metadata_applied_vs_early_stage")

    def test_contradiction_applied_false_with_after_execute_is_unknown(self) -> None:
        rec = self.ledger.prepare(tool="echo", arguments={"x": 1}, effect_class="plugin_side_effect")
        self.ledger.mark_failed(
            rec.effect_id,
            detail={"error": "boom", "effect_applied": False, "failure_stage": "after_execute"},
        )
        decision = self.ledger.classify_on_restart(rec.effect_id)
        self.assertEqual(decision["class"], "UNKNOWN_EXTERNAL_STATE")
        self.assertEqual(decision["reason"], "contradictory_metadata_not_applied_vs_late_stage")

    def test_partial_effect_requires_reconciliation(self) -> None:
        rec = self.ledger.prepare(tool="echo", arguments={"x": 1}, effect_class="fs_write")
        self.ledger.mark_failed(rec.effect_id, detail={"failure_stage": "partial_effect"})
        decision = self.ledger.classify_on_restart(rec.effect_id)
        self.assertEqual(decision["class"], "REQUIRES_RECONCILIATION")

    def test_failed_before_execute_stage_alone_is_safe(self) -> None:
        rec = self.ledger.prepare(tool="echo", arguments={"x": 1}, effect_class="plugin_side_effect")
        self.ledger.mark_failed(rec.effect_id, detail={"failure_stage": "validation"})
        decision = self.ledger.classify_on_restart(rec.effect_id)
        self.assertEqual(decision["class"], "SAFE_TO_RETRY")
        self.assertEqual(decision["reason"], "failed_before_effect")

    def test_missing_failed_metadata_is_unknown(self) -> None:
        rec = self.ledger.prepare(tool="echo", arguments={"x": 1}, effect_class="plugin_side_effect")
        self.ledger.mark_failed(rec.effect_id, detail={})
        decision = self.ledger.classify_on_restart(rec.effect_id)
        self.assertEqual(decision["class"], "UNKNOWN_EXTERNAL_STATE")

    def test_unknown_outcome(self) -> None:
        rec = self.ledger.prepare(tool="echo", arguments={"x": 1}, effect_class="network_post")
        self.ledger.mark_unknown(rec.effect_id)
        decision = self.ledger.classify_on_restart(rec.effect_id)
        self.assertEqual(decision["class"], "UNKNOWN_EXTERNAL_STATE")

    def test_args_hash_stable(self) -> None:
        a = self.ledger.prepare(tool="t", arguments={"b": 2, "a": 1})
        b = self.ledger.prepare(tool="t", arguments={"a": 1, "b": 2})
        self.assertEqual(a.args_hash, b.args_hash)


if __name__ == "__main__":
    unittest.main()
