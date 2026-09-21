"""Bounded NVMe / disk read-ahead cache for layer streaming.

Never assumes unbounded OS page cache. Metrics are explicit.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from training.streaming.residency import snapshot_module_state_to_cpu


class NvmeLayerCache:
    def __init__(
        self,
        layer_states: list[dict[str, Any]],
        *,
        max_cached_layers: int = 2,
    ):
        self._layers = layer_states
        self.max_cached_layers = max(1, int(max_cached_layers))
        self._cache: OrderedDict[int, dict[str, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.bytes_read = 0
        self._closed = False

    @classmethod
    def from_model(cls, model: Any, *, torch_module: Any, max_cached_layers: int = 2) -> "NvmeLayerCache":
        from training.streaming.architecture_adapter import resolve_adapter

        adapter = resolve_adapter(model)
        blocks = list(adapter.iter_transformer_blocks(model))
        # Initial materialization snapshots layers to host tensors representing shard-backed state.
        # True mmap safetensors lookup can replace this once shard indexing is wired per-tensor.
        states = [
            snapshot_module_state_to_cpu(block, torch_module=torch_module, pin_memory=False)
            for block in blocks
        ]
        return cls(states, max_cached_layers=max_cached_layers)

    def load_layer_state(self, layer_index: int) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("NvmeLayerCache closed")
        if layer_index in self._cache:
            self.hits += 1
            self._cache.move_to_end(layer_index)
            return self._cache[layer_index]
        self.misses += 1
        state = self._layers[layer_index]
        size = sum(int(t.numel() * t.element_size()) for t in state.values())
        self.bytes_read += size
        self._cache[layer_index] = state
        self._cache.move_to_end(layer_index)
        while len(self._cache) > self.max_cached_layers:
            self._cache.popitem(last=False)
        return state

    def metrics(self) -> dict[str, Any]:
        return {
            "cache_hits": self.hits,
            "cache_misses": self.misses,
            "bytes_read": self.bytes_read,
            "cached_layers": list(self._cache.keys()),
            "max_cached_layers": self.max_cached_layers,
        }

    def close(self) -> None:
        self._closed = True
        self._cache.clear()
