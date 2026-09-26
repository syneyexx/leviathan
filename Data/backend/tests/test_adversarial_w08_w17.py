"""A08/W08 preference correction + T08/W17 sealed holdout rename inheritance."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.agent_lab import (
    AcceptanceCriteria,
    assert_lineage_holdout_clean,
    evaluate_candidate_pipeline,
    mark_sealed_revealed,
    new_agent_lab,
    register_lineage_rename,
)
from Data.modules.market_sim.types import MarketSimError
from Data.modules.memory import MemoryKind, MemoryStatus, MemoryStore


class PreferenceCorrectionA08Tests(unittest.TestCase):
    def test_corrected_preference_wins_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            old = store.create(
                content="User prefers concise bullet replies",
                kind=MemoryKind.PREFERENCE,
                source="user",
                trust="explicit",
                conversation_id="c1",
                tags=["preference", "reply_style"],
                metadata={"preference_key": "reply_style"},
            )
            # Adversarial duplicate: raw create without supersession (stale would win
            # if correct_preference only appended another ACTIVE row).
            duplicate = store.create(
                content="User prefers concise bullet replies",
                kind=MemoryKind.FACT,
                source="user",
                trust="explicit",
                conversation_id="c1",
                tags=["preference", "reply_style"],
                metadata={"preference_key": "reply_style"},
            )
            corrected = store.correct_preference(
                "User prefers full prose paragraphs",
                preference_key="reply_style",
                conversation_id="c1",
            )
            self.assertEqual(corrected.kind, MemoryKind.PREFERENCE)
            self.assertEqual(corrected.supersedes_id, old.memory_id)
            for mid in (old.memory_id, duplicate.memory_id):
                stale = store.get(mid)
                assert stale is not None
                self.assertEqual(stale.status, MemoryStatus.SUPERSEDED)

            hits = store.search("prefers", conversation_id="c1")
            contents = [h.content for h in hits]
            self.assertIn("User prefers full prose paragraphs", contents)
            self.assertNotIn("User prefers concise bullet replies", contents)

            active_prefs = store.list(conversation_id="c1", kind=MemoryKind.PREFERENCE)
            self.assertEqual(len(active_prefs), 1)
            self.assertEqual(active_prefs[0].memory_id, corrected.memory_id)
            self.assertEqual(active_prefs[0].metadata.get("preference_key"), "reply_style")

            # Persist across re-open: reload store from same DB path.
            reloaded = MemoryStore(Path(tmp) / "memory.db")
            reloaded.initialize()
            again = reloaded.list(conversation_id="c1", kind=MemoryKind.PREFERENCE)
            self.assertEqual(len(again), 1)
            self.assertEqual(again[0].content, "User prefers full prose paragraphs")
            self.assertEqual(
                reloaded.get(old.memory_id).status,  # type: ignore[union-attr]
                MemoryStatus.SUPERSEDED,
            )


class SealedRenameT08Tests(unittest.TestCase):
    def test_renamed_strategy_inherits_holdout_contamination(self) -> None:
        lab = new_agent_lab()
        mark_sealed_revealed(
            lab,
            strategy_id="mean-reversion-v1",
            parent_version=2,
            sealed_dataset_id="holdout-sealed-A",
            sealed_attempt_id="attempt-1",
        )
        root = register_lineage_rename(
            lab,
            from_strategy_id="mean-reversion-v1",
            to_strategy_id="mr-renamed-champion",
        )
        self.assertEqual(root, "mean-reversion-v1")
        with self.assertRaises(MarketSimError) as ctx:
            assert_lineage_holdout_clean(
                lab,
                strategy_id="mr-renamed-champion",
                parent_version=2,
                sealed_dataset_id="holdout-sealed-A",
            )
        self.assertEqual(ctx.exception.code, "HOLDOUT_LINEAGE_CONTAMINATED")
        # Explicit root without rename registry also contaminates.
        with self.assertRaises(MarketSimError):
            assert_lineage_holdout_clean(
                lab,
                strategy_id="brand-new-name",
                parent_version=2,
                sealed_dataset_id="holdout-sealed-A",
                root_lineage_id="mean-reversion-v1",
            )
        # Fresh holdout epoch remains allowed.
        assert_lineage_holdout_clean(
            lab,
            strategy_id="mr-renamed-champion",
            parent_version=2,
            sealed_dataset_id="holdout-sealed-B",
        )

    def test_renamed_descendant_pipeline_refuses_same_holdout(self) -> None:
        """T08: after sealed reveal + rename, pipeline still sees contamination."""
        crit = AcceptanceCriteria(
            min_trades=1,
            max_drawdown_pct=50,
            require_val_pass=False,
            require_robustness_pass=False,
        )
        lab = new_agent_lab(acceptance=crit)
        good = {"trade_count": 5, "max_drawdown_pct": 5, "total_return_pct": 3}
        evaluate_candidate_pipeline(
            lab,
            strategy_id="alpha-original",
            strategy_version=1,
            hypothesis="first sealed exposure",
            train_metrics=good,
            val_metrics=good,
            robustness_metrics=good,
            sealed_metrics=good,
            sealed_attempt_id="att-orig",
            parent_version=0,
            sealed_dataset_id="holdout-A",
        )
        register_lineage_rename(
            lab,
            from_strategy_id="alpha-original",
            to_strategy_id="alpha-renamed",
        )
        with self.assertRaises(MarketSimError) as ctx:
            evaluate_candidate_pipeline(
                lab,
                strategy_id="alpha-renamed",
                strategy_version=2,
                hypothesis="retry after rename",
                train_metrics=good,
                val_metrics=good,
                robustness_metrics=good,
                sealed_metrics=good,
                sealed_attempt_id="att-rename",
                parent_version=0,
                sealed_dataset_id="holdout-A",
            )
        self.assertEqual(ctx.exception.code, "HOLDOUT_LINEAGE_CONTAMINATED")

        # Parent-lineage descendant without rename registry still contaminated.
        with self.assertRaises(MarketSimError) as ctx2:
            evaluate_candidate_pipeline(
                lab,
                strategy_id="alpha-child",
                strategy_version=1,
                hypothesis="forked child",
                train_metrics=good,
                val_metrics=good,
                robustness_metrics=good,
                sealed_metrics=good,
                sealed_attempt_id="att-child",
                parent_version=0,
                sealed_dataset_id="holdout-A",
                ancestor_strategy_ids=["alpha-original"],
            )
        self.assertEqual(ctx2.exception.code, "HOLDOUT_LINEAGE_CONTAMINATED")


if __name__ == "__main__":
    unittest.main()
