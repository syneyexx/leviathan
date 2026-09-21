"""Host residency helpers for frozen base weights."""

from __future__ import annotations

from typing import Any


def snapshot_module_state_to_cpu(module: Any, *, torch_module: Any, pin_memory: bool = False) -> dict[str, Any]:
    """Snapshot frozen base tensors only — never capture trainable LoRA parameters."""

    state: dict[str, Any] = {}
    for name, param in module.named_parameters(recurse=True):
        if param.requires_grad or "lora_" in name:
            continue
        tensor = param.detach().to("cpu", copy=True)
        if pin_memory and str(getattr(tensor, "device", "")).startswith("cpu"):
            try:
                tensor = tensor.pin_memory()
            except RuntimeError:
                pass
        state[name] = tensor
    for name, buf in module.named_buffers(recurse=True):
        if "lora_" in name:
            continue
        tensor = buf.detach().to("cpu", copy=True)
        state[name] = tensor
    return state


def apply_state_dict_tensors(module: Any, tensors: dict[str, Any]) -> None:
    params = dict(module.named_parameters(recurse=True))
    buffers = dict(module.named_buffers(recurse=True))
    for name, tensor in tensors.items():
        if name in params:
            if params[name].requires_grad or "lora_" in name:
                continue
            params[name].data = tensor
        elif name in buffers:
            buffers[name].data = tensor
