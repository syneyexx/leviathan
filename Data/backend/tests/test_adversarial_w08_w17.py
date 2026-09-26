"""A08 preference correction + T08 sealed holdout rename inheritance."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.market_sim.agent_lab import (
    assert_lineage_holdout_clean,
    mark_sealed_revealed,
    new_agent_lab,
    register_lineage_rename,
)
from Data.modules.market_sim.types import MarketSimError
from Data.modules.memory import MemoryKind, MemoryStatus, MemoryStore


class PreferenceCorrectionA08Tests(unittest.TestCase):
    def test_corrected_preference_supersedes_stale_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            old = store.create(
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
            self.assertEqual(corrected.supersedes_id, old.memory_id)
            stale = store.get(old.memory_id)
            assert stale is not None
            self.assertEqual(stale.status, MemoryStatus.SUPERSEDED)

            hits = store.search("prefers", conversation_id="c1")
            contents = [h.content for h in hits]
            self.assertIn("User prefers full prose paragraphs", contents)
            self.assertNotIn("User prefers concise bullet replies", contents)

            active = store.list(conversation_id="c1", kind=MemoryKind.FACT)
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0].memory_id, corrected.memory_id)


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


if __name__ == "__main__":
    unittest.main()
