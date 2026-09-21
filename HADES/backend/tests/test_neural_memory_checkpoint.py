"""Atomic checkpoint / restore / corrupt / compatibility tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _torch_or_skip(test: unittest.TestCase):
    from neural.deps import neural_available

    if not neural_available():
        test.skipTest("torch unavailable")
    import torch

    return torch


class NeuralMemoryCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.checkpoint import NeuralMemoryCheckpointStore
        from neural.config import NeuralMemoryConfig
        from neural.contracts import NeuralMode
        from neural.evals import make_association_pairs, train_pairs
        from neural.memory import NeuralMemory

        self.tmp = tempfile.TemporaryDirectory()
        self.store = NeuralMemoryCheckpointStore(Path(self.tmp.name) / "ckpts")
        self.config = NeuralMemoryConfig(
            dim=20,
            hidden_dim=48,
            mode=NeuralMode.LEARN,
            seed=5,
            learning_rate=0.2,
            max_update_steps=70,
            loss_tolerance=0.08,
        )
        self.memory = NeuralMemory(self.config)
        self.pairs = make_association_pairs(20, 3, seed=9)
        train_pairs(self.memory, self.pairs)
        self.NeuralMemoryConfig = NeuralMemoryConfig
        self.NeuralMode = NeuralMode
        self.evaluate_recall = __import__("neural.evals", fromlist=["evaluate_recall"]).evaluate_recall

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_snapshot_restore_roundtrip(self) -> None:
        snap = self.memory.snapshot()
        score_before = self.evaluate_recall(self.memory, self.pairs).mean_cosine
        # Mutate
        extra = self.torch.randn(20)
        self.memory.write(extra, extra)
        self.memory.restore(snap)
        score_after = self.evaluate_recall(self.memory, self.pairs).mean_cosine
        self.assertAlmostEqual(score_before, score_after, places=5)

    def test_atomic_checkpoint_save_load(self) -> None:
        manifest = self.store.save(self.memory, checkpoint_id="nm_001", candidate=True)
        self.assertEqual(manifest["schema_version"], 2)
        self.assertTrue(manifest["integrity_hash"])
        loaded = self.store.load("nm_001", candidate=True)
        before = self.evaluate_recall(self.memory, self.pairs).mean_cosine
        after = self.evaluate_recall(loaded, self.pairs).mean_cosine
        self.assertAlmostEqual(before, after, places=5)
        # Promote to good
        promoted = self.store.promote_candidate("nm_001")
        self.assertFalse(promoted["candidate"])
        good = self.store.load(candidate=False)
        self.assertAlmostEqual(before, self.evaluate_recall(good, self.pairs).mean_cosine, places=5)

    def test_corrupt_checkpoint_fails_safe(self) -> None:
        from neural.errors import NeuralCheckpointCorrupt

        self.store.save(self.memory, checkpoint_id="nm_bad", candidate=True)
        weights = self.store.candidate_dir / "nm_bad" / "weights.pt"
        raw = bytearray(weights.read_bytes())
        raw[0] ^= 0xFF
        weights.write_bytes(bytes(raw))
        with self.assertRaises(NeuralCheckpointCorrupt):
            self.store.load("nm_bad", candidate=True)

    def test_incompatible_config_rejected(self) -> None:
        from neural.errors import NeuralCheckpointIncompatible

        self.store.save(self.memory, checkpoint_id="nm_dim", candidate=False)
        other = self.NeuralMemoryConfig(dim=8, hidden_dim=16, mode=self.NeuralMode.OFF)
        with self.assertRaises(NeuralCheckpointIncompatible):
            self.store.load("nm_dim", candidate=False, expected_config=other)

    def test_corrupt_manifest_fails_safe(self) -> None:
        from neural.errors import NeuralCheckpointCorrupt

        self.store.save(self.memory, checkpoint_id="nm_man", candidate=True)
        manifest_path = self.store.candidate_dir / "nm_man" / "manifest.json"
        manifest_path.write_text("{not-json", encoding="utf-8")
        with self.assertRaises(NeuralCheckpointCorrupt):
            self.store.load("nm_man", candidate=True)


if __name__ == "__main__":
    unittest.main()
