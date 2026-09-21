"""ATME streaming buffer / double-buffer unit coverage (torch optional)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


@unittest.skipUnless(TORCH_AVAILABLE, "torch not installed")
class AtmeBufferTests(unittest.TestCase):
    def test_single_and_double_buffer_slots(self) -> None:
        import torch

        from training.streaming.buffers import LayerBufferPool

        pool1 = LayerBufferPool(buffer_count=1, device=torch.device("cpu"), torch_module=torch)
        pool2 = LayerBufferPool(buffer_count=2, device=torch.device("cpu"), torch_module=torch)
        self.assertEqual(len(pool1.slots), 1)
        self.assertEqual(len(pool2.slots), 2)
        state = {"weight": torch.randn(4, 4)}
        pool2.stage_state_dict(pool2.slot_for_layer(0), state, layer_index=0)
        pool2.stage_state_dict(pool2.slot_for_layer(1), state, layer_index=1)
        self.assertEqual(pool2.slot_for_layer(0).occupied_by_layer, 0)
        self.assertEqual(pool2.slot_for_layer(1).occupied_by_layer, 1)
        # Overlap is never claimed without CUDA event proof.
        self.assertFalse(pool2.measured_overlap)
        pool1.close()
        pool2.close()

    def test_nvme_cache_is_bounded(self) -> None:
        import torch

        from training.streaming.nvme_cache import NvmeLayerCache

        layers = [{"w": torch.ones(2, 2)} for _ in range(5)]
        cache = NvmeLayerCache(layers, max_cached_layers=2)
        cache.load_layer_state(0)
        cache.load_layer_state(1)
        cache.load_layer_state(2)
        self.assertLessEqual(len(cache._cache), 2)
        self.assertGreaterEqual(cache.misses, 3)
        cache.load_layer_state(2)
        self.assertGreaterEqual(cache.hits, 1)
        cache.close()


if __name__ == "__main__":
    unittest.main()
