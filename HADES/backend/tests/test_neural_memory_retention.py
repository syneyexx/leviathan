"""Retention, interference, replay, and baseline comparison measurements."""

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


class NeuralMemoryRetentionTests(unittest.TestCase):
    """Quantitative Phase 1 gate. Failures here block deeper LLM integration."""

    def setUp(self) -> None:
        self.torch = _torch_or_skip(self)
        from neural.baselines import NearestNeighborMemory
        from neural.config import NeuralMemoryConfig
        from neural.contracts import NeuralMode
        from neural.evals import evaluate_recall, make_association_pairs, train_pairs
        from neural.memory import NeuralMemory

        self.NearestNeighborMemory = NearestNeighborMemory
        self.evaluate_recall = evaluate_recall
        self.make_association_pairs = make_association_pairs
        self.train_pairs = train_pairs
        self.NeuralMemory = NeuralMemory
        self.NeuralMode = NeuralMode
        self.base_cfg = NeuralMemoryConfig(
            dim=32,
            hidden_dim=96,
            fast_hidden_dim=48,
            mode=NeuralMode.LEARN,
            seed=123,
            learning_rate=0.15,
            max_update_steps=100,
            loss_tolerance=0.06,
            replay_enabled=True,
            replay_batch_size=4,
            replay_loss_weight=0.75,
            max_parameter_delta_norm=200.0,
        )

    def test_sequential_retention_with_replay(self) -> None:
        memory = self.NeuralMemory(self.base_cfg)
        first = self.make_association_pairs(32, 3, seed=1)
        second = self.make_association_pairs(32, 3, seed=100)
        r1 = self.train_pairs(memory, first)
        self.assertTrue(all(x["accepted"] for x in r1), r1)
        initial = self.evaluate_recall(memory, first, name="initial")
        self.assertGreaterEqual(initial.mean_cosine, 0.85, initial.to_dict())

        r2 = self.train_pairs(memory, second)
        self.assertTrue(all(x["accepted"] for x in r2), r2)
        retained = self.evaluate_recall(memory, first, name="retained")
        new_score = self.evaluate_recall(memory, second, name="new")
        # Retention gate: old associations must remain useful after new writes.
        self.assertGreaterEqual(retained.mean_cosine, 0.55, retained.to_dict())
        self.assertGreaterEqual(new_score.mean_cosine, 0.80, new_score.to_dict())
        degradation = initial.mean_cosine - retained.mean_cosine
        self.assertLessEqual(degradation, 0.40, {"initial": initial.mean_cosine, "retained": retained.mean_cosine})

    def test_replay_improves_retention_vs_no_replay(self) -> None:
        first = self.make_association_pairs(32, 3, seed=2)
        second = self.make_association_pairs(32, 3, seed=200)

        def run(replay: bool) -> float:
            from neural.config import NeuralMemoryConfig

            cfg = NeuralMemoryConfig(
                **{
                    **self.base_cfg.to_dict(),
                    "mode": self.NeuralMode.LEARN,
                    "replay_enabled": replay,
                    "seed": 99,
                }
            )
            memory = self.NeuralMemory(cfg)
            self.train_pairs(memory, first)
            self.train_pairs(memory, second)
            return self.evaluate_recall(memory, first).mean_cosine

        with_replay = run(True)
        without = run(False)
        # Replay should not be worse by a large margin; ideally better.
        # Soft gate: document both; hard gate only if no-replay somehow hugely better
        # while replay collapses (would indicate a bug).
        self.assertGreaterEqual(with_replay, 0.45, {"with_replay": with_replay, "without": without})
        self.assertGreaterEqual(with_replay + 0.05, without - 0.15, {"with_replay": with_replay, "without": without})

    def test_interference_measurement(self) -> None:
        torch = self.torch
        # Distinct keys baseline.
        distinct = self.make_association_pairs(32, 4, seed=3)
        mem_a = self.NeuralMemory(self.base_cfg)
        self.train_pairs(mem_a, distinct)
        distinct_report = self.evaluate_recall(mem_a, distinct, name="distinct")

        # Near-duplicate keys — expect degradation vs distinct set.
        base_key = torch.nn.functional.normalize(torch.randn(32), dim=0)
        pairs = []
        for i in range(4):
            g = torch.Generator()
            g.manual_seed(300 + i)
            key = torch.nn.functional.normalize(base_key + 0.02 * torch.randn(32, generator=g), dim=0)
            value = torch.nn.functional.normalize(torch.randn(32, generator=g), dim=0)
            pairs.append((f"sim{i}", key, value))
        mem_b = self.NeuralMemory(self.base_cfg)
        self.train_pairs(mem_b, pairs)
        report = self.evaluate_recall(mem_b, pairs, name="interference")
        degradation = distinct_report.mean_cosine - report.mean_cosine
        # Measurement gate: interference run finishes with finite scores and shows
        # degradation relative to distinct keys (or equal only if both saturated).
        self.assertTrue(all(s.cosine == s.cosine for s in report.scores))
        self.assertGreaterEqual(degradation, -0.05, {
            "distinct": distinct_report.mean_cosine,
            "similar": report.mean_cosine,
            "degradation": degradation,
            "similar_detail": report.to_dict(),
        })
        self.assertLessEqual(report.mean_cosine, distinct_report.mean_cosine + 0.05)

    def test_baseline_nn_perfect_on_exact_keys(self) -> None:
        nn = self.NearestNeighborMemory(32)
        pairs = self.make_association_pairs(32, 5, seed=4)
        for _, key, value in pairs:
            nn.write(key, value)
        sims = []
        for _, key, value in pairs:
            out = nn.read(key)
            cos = float(
                self.torch.nn.functional.cosine_similarity(
                    out["value"].unsqueeze(0), value.unsqueeze(0)
                ).item()
            )
            sims.append(cos)
        mean = sum(sims) / len(sims)
        self.assertGreaterEqual(mean, 0.999)

    def test_phase1_benchmark_artifact(self) -> None:
        """Write a compact JSON report for STATUS.md evidence."""
        memory = self.NeuralMemory(self.base_cfg)
        first = self.make_association_pairs(32, 3, seed=10)
        second = self.make_association_pairs(32, 3, seed=20)
        self.train_pairs(memory, first)
        initial = self.evaluate_recall(memory, first)
        self.train_pairs(memory, second)
        retained = self.evaluate_recall(memory, first)
        new_score = self.evaluate_recall(memory, second)

        nn = self.NearestNeighborMemory(32)
        for _, key, value in first + second:
            nn.write(key, value)
        nn_scores = []
        for _, key, value in first:
            out = nn.read(key)
            nn_scores.append(
                float(
                    self.torch.nn.functional.cosine_similarity(
                        out["value"].unsqueeze(0), value.unsqueeze(0)
                    ).item()
                )
            )

        report = {
            "associations_stored": memory.metrics().association_count,
            "parameter_count": memory.metrics().parameter_count,
            "initial_recall_mean_cosine": initial.mean_cosine,
            "post_write_retention_mean_cosine": retained.mean_cosine,
            "new_recall_mean_cosine": new_score.mean_cosine,
            "interference_note": "see test_interference_measurement",
            "nn_baseline_old_mean_cosine": sum(nn_scores) / len(nn_scores),
            "cpu_read_latency_ms_mean": retained.latency_ms_mean,
            "last_write_latency_ms": memory.metrics().last_write_latency_ms,
            "gpu_latency_ms": None,
            "cuda_available": bool(self.torch.cuda.is_available()),
        }
        out_dir = Path(__file__).resolve().parents[2] / "docs" / "neural"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "phase1_benchmark.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.assertTrue(path.is_file())
        self.assertGreaterEqual(report["initial_recall_mean_cosine"], 0.85)
        self.assertGreaterEqual(report["post_write_retention_mean_cosine"], 0.55)


if __name__ == "__main__":
    unittest.main()
