"""RAM / NVMe layer-streaming strategy runtime for allowlisted architectures.

Correctness-first design:
- Frozen base layer weights live on host (RAM) or are loaded via bounded NVMe cache.
- Trainable LoRA parameters remain on the compute device and are never recreated.
- Each layer is staged into a reusable GPU buffer before compute.
- Activation checkpointing re-stages during backward recompute.
- Double buffering is optional; single-buffer remains the correctness baseline.
"""

from __future__ import annotations

from typing import Any

from training.execution_plan import MemoryStrategy, TrainingExecutionPlan
from training.streaming.architecture_adapter import resolve_adapter
from training.streaming.buffers import LayerBufferPool
from training.streaming.residency import apply_state_dict_tensors, snapshot_module_state_to_cpu
from training.streaming.transfer_scheduler import TransferScheduler

NAME = MemoryStrategy.RAM_LAYER_STREAMING


class LayerStreamingRuntime:
    def __init__(
        self,
        model: Any,
        plan: TrainingExecutionPlan,
        *,
        torch_module: Any,
        device: Any,
        source: str = "ram",
        nvme_cache: Any | None = None,
    ):
        self.torch = torch_module
        self.model = model
        self.plan = plan
        self.device = device
        self.source = source
        self.nvme_cache = nvme_cache
        self.adapter = resolve_adapter(model)
        self.layout = self.adapter.inspect(model)
        self.blocks = list(self.adapter.iter_transformer_blocks(model))
        self.cpu_states: list[dict[str, Any]] = []
        self.pool = LayerBufferPool(
            buffer_count=max(1, int(plan.buffer_count or 1)),
            device=device,
            torch_module=torch_module,
        )
        self.scheduler = TransferScheduler(self.pool)
        self._handles: list[Any] = []
        self.current_compute_layer: int | None = None
        self.closed = False

    def install(self) -> Any:
        pin = self.source == "ram"
        for index, block in enumerate(self.blocks):
            if self.source == "nvme" and self.nvme_cache is not None:
                state = self.nvme_cache.load_layer_state(index)
            else:
                state = snapshot_module_state_to_cpu(block, torch_module=self.torch, pin_memory=pin)
            self.cpu_states.append(state)
            # Move trainable LoRA params to compute device; freeze base params as host-staged.
            for name, param in block.named_parameters(recurse=True):
                if param.requires_grad or "lora_" in name:
                    param.data = param.data.to(self.device)
                else:
                    # Keep a tiny host-resident master; compute uses staged storage via hook.
                    param.data = param.data.detach().to("cpu")
                    param.requires_grad_(False)

            pre_handle = block.register_forward_pre_hook(self._make_pre_hook(index), with_kwargs=True)
            post_handle = block.register_forward_hook(self._make_post_hook(index))
            self._handles.extend([pre_handle, post_handle])

        # Embeddings / norm / lm head stay on compute device when practical.
        base = self.adapter._base(self.model)  # noqa: SLF001 — intentional adapter seam
        for attr in self.layout.persistent_modules:
            module = getattr(base, attr, None) if hasattr(base, attr) else getattr(self.model, attr, None)
            if module is None and hasattr(self.model, "get_base_model"):
                root = self.model.get_base_model()
                module = getattr(root, attr, None)
            if module is not None:
                module.to(self.device)
        return self.model

    def _make_pre_hook(self, layer_index: int):
        def _pre_hook(module, args, kwargs):  # type: ignore[no-untyped-def]
            if self.closed:
                raise RuntimeError("LayerStreamingRuntime closed during forward")
            self.current_compute_layer = layer_index

            def prefetch_next():
                nxt = layer_index + 1
                if nxt >= len(self.cpu_states):
                    return None
                if self.source == "nvme" and self.nvme_cache is not None:
                    return nxt, self.nvme_cache.load_layer_state(nxt)
                return nxt, self.cpu_states[nxt]

            staged = self.scheduler.stage(
                layer_index,
                self.cpu_states[layer_index],
                prefetch_next=prefetch_next if self.pool.buffer_count >= 2 else None,
            )
            apply_state_dict_tensors(module, staged)
            # Ensure inputs are on compute device.
            if args and hasattr(args[0], "to"):
                args = tuple(a.to(self.device) if hasattr(a, "to") else a for a in args)
            if kwargs:
                kwargs = {
                    key: (value.to(self.device) if hasattr(value, "to") else value)
                    for key, value in kwargs.items()
                }
            return args, kwargs

        return _pre_hook

    def _make_post_hook(self, layer_index: int):
        def _post_hook(module, inputs, output):  # type: ignore[no-untyped-def]
            _ = module, inputs
            self.scheduler.mark_compute_finished(layer_index)
            return output

        return _post_hook

    def telemetry_snapshot(self) -> dict[str, Any]:
        return {
            "current_compute_layer": self.current_compute_layer,
            "current_staged_layer": self.scheduler.current_layer,
            "prefetched_layer": self.scheduler.prefetched_layer,
            "buffer_count": self.pool.buffer_count,
            "h2d_bytes_total": self.pool.total_h2d_bytes,
            "measured_copy_compute_overlap": bool(self.pool.measured_overlap),
            "source": self.source,
        }

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for handle in self._handles:
            try:
                handle.remove()
            except Exception:
                pass
        self._handles.clear()
        self.pool.close()
        if self.nvme_cache is not None:
            try:
                self.nvme_cache.close()
            except Exception:
                pass


def apply_model_load_kwargs(plan: TrainingExecutionPlan, base_kwargs: dict[str, Any]) -> dict[str, Any]:
    kwargs = dict(base_kwargs)
    # Load on CPU first; runtime stages layers to GPU.
    kwargs["device_map"] = "cpu"
    kwargs.pop("quantization_config", None)
    _ = plan
    return kwargs


def prepare_model(model: Any, plan: TrainingExecutionPlan, *, torch_module: Any, device: Any | None = None) -> tuple[Any, LayerStreamingRuntime]:
    if device is None:
        device = torch_module.device("cuda" if torch_module.cuda.is_available() else "cpu")
    source = "nvme" if plan.strategy == MemoryStrategy.NVME_LAYER_STREAMING else "ram"
    nvme_cache = None
    if source == "nvme":
        from training.streaming.nvme_cache import NvmeLayerCache

        nvme_cache = NvmeLayerCache.from_model(model, torch_module=torch_module)
    runtime = LayerStreamingRuntime(
        model,
        plan,
        torch_module=torch_module,
        device=device,
        source=source,
        nvme_cache=nvme_cache,
    )
    runtime.install()
    if plan.activation_checkpointing in {"auto", "enabled"}:
        try:
            from torch.utils.checkpoint import checkpoint_wrapper  # type: ignore[import-not-found]

            blocks = list(runtime.blocks)
            for index, block in enumerate(blocks):
                wrapped = checkpoint_wrapper(block)
                # Replace in parent ModuleList when possible.
                parent_list = None
                base = runtime.adapter._base(model)  # noqa: SLF001
                if hasattr(base, "layers"):
                    parent_list = base.layers
                elif hasattr(base, "h"):
                    parent_list = base.h
                if parent_list is not None:
                    parent_list[index] = wrapped
                    runtime.blocks[index] = wrapped
        except Exception:
            # Checkpoint wrapper is optional; streaming still works with restream-on-recompute if enabled later.
            pass
    return model, runtime
