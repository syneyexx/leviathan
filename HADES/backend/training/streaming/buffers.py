"""Reusable GPU weight buffers with explicit CUDA event synchronization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BufferSlot:
    index: int
    device: Any
    occupied_by_layer: int | None = None
    copy_event: Any | None = None
    compute_event: Any | None = None
    parameter_storage: dict[str, Any] = field(default_factory=dict)


class LayerBufferPool:
    """One or two reusable GPU buffers for staged frozen layer weights."""

    def __init__(self, *, buffer_count: int, device: Any, torch_module: Any):
        if buffer_count < 1 or buffer_count > 4:
            raise ValueError("buffer_count must be between 1 and 4")
        self.torch = torch_module
        self.device = device
        self.buffer_count = int(buffer_count)
        self.slots = [BufferSlot(index=index, device=device) for index in range(self.buffer_count)]
        self.transfer_stream = None
        if hasattr(torch_module, "cuda") and str(device).startswith("cuda"):
            try:
                self.transfer_stream = torch_module.cuda.Stream(device=device)
            except Exception:
                self.transfer_stream = None
        self._closed = False
        self.measured_overlap = False
        self.total_h2d_bytes = 0

    def slot_for_layer(self, layer_index: int) -> BufferSlot:
        return self.slots[int(layer_index) % self.buffer_count]

    def wait_compute_done(self, slot: BufferSlot) -> None:
        if slot.compute_event is not None:
            slot.compute_event.synchronize()

    def mark_copy_done(self, slot: BufferSlot) -> None:
        if str(self.device).startswith("cuda"):
            event = self.torch.cuda.Event(enable_timing=True)
            if self.transfer_stream is not None:
                event.record(self.transfer_stream)
            else:
                event.record()
            slot.copy_event = event

    def wait_copy_done(self, slot: BufferSlot) -> None:
        if slot.copy_event is not None:
            slot.copy_event.synchronize()

    def mark_compute_done(self, slot: BufferSlot) -> None:
        if str(self.device).startswith("cuda"):
            event = self.torch.cuda.Event(enable_timing=True)
            event.record()
            slot.compute_event = event

    def stage_state_dict(
        self,
        slot: BufferSlot,
        cpu_state: dict[str, Any],
        *,
        layer_index: int,
        non_blocking: bool = True,
    ) -> None:
        if self._closed:
            raise RuntimeError("LayerBufferPool is closed")
        self.wait_compute_done(slot)
        stream_ctx = nullcontext()
        if self.transfer_stream is not None:
            stream_ctx = self.torch.cuda.stream(self.transfer_stream)
        with stream_ctx:
            for name, tensor in cpu_state.items():
                if name not in slot.parameter_storage:
                    slot.parameter_storage[name] = self.torch.empty(
                        tensor.shape,
                        dtype=tensor.dtype,
                        device=self.device,
                    )
                dest = slot.parameter_storage[name]
                if dest.shape != tensor.shape or dest.dtype != tensor.dtype:
                    dest = self.torch.empty(tensor.shape, dtype=tensor.dtype, device=self.device)
                    slot.parameter_storage[name] = dest
                dest.copy_(tensor, non_blocking=bool(non_blocking) and str(self.device).startswith("cuda"))
                self.total_h2d_bytes += int(tensor.numel() * tensor.element_size())
        self.mark_copy_done(slot)
        self.wait_copy_done(slot)
        slot.occupied_by_layer = layer_index

    def measure_overlap_if_possible(self, copy_event: Any, compute_event: Any) -> bool:
        """Return True only when CUDA event timings prove overlap."""

        if copy_event is None or compute_event is None:
            return False
        try:
            # elapsed_time requires both events recorded on CUDA.
            _ = copy_event.elapsed_time(compute_event)
            # Without a second parallel stream timeline we cannot claim overlap.
            self.measured_overlap = False
            return False
        except Exception:
            return False

    def close(self) -> None:
        self._closed = True
        self.slots.clear()
        self.transfer_stream = None


class nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False
