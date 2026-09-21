"""Transfer scheduler coordinating layer staging and compute readiness."""

from __future__ import annotations

from typing import Any, Callable

from training.streaming.buffers import LayerBufferPool


class TransferScheduler:
    def __init__(self, pool: LayerBufferPool):
        self.pool = pool
        self.current_layer: int | None = None
        self.prefetched_layer: int | None = None

    def stage(
        self,
        layer_index: int,
        cpu_state: dict[str, Any],
        *,
        prefetch_next: Callable[[], tuple[int, dict[str, Any]] | None] | None = None,
    ) -> dict[str, Any]:
        slot = self.pool.slot_for_layer(layer_index)
        self.pool.stage_state_dict(slot, cpu_state, layer_index=layer_index)
        self.current_layer = layer_index
        staged = dict(slot.parameter_storage)
        if prefetch_next is not None and self.pool.buffer_count >= 2:
            nxt = prefetch_next()
            if nxt is not None:
                next_index, next_state = nxt
                next_slot = self.pool.slot_for_layer(next_index)
                if next_slot.index != slot.index:
                    # Kick off staging into the alternate buffer; compute must wait on its event.
                    self.pool.stage_state_dict(next_slot, next_state, layer_index=next_index)
                    self.prefetched_layer = next_index
        return staged

    def mark_compute_finished(self, layer_index: int) -> None:
        slot = self.pool.slot_for_layer(layer_index)
        self.pool.mark_compute_done(slot)
