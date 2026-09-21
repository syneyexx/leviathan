"""Experimental neural model runtime (research fixture).

Frozen base toy Transformer + HADES neural memory residual fusion (ADR-N4).

Dispatch into ModelGateway is gated by ``reasoning.runtime_selection`` /
``reasoning.model_chat_dispatch``. READ is **not** product-primary (F-06):
selection refuses neural as primary until real LM fusion exists. SHADOW may
run diagnostics beside Standard. Defaults remain OFF.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from neural.config import NeuralMemoryConfig
from neural.contracts import NeuralMode
from neural.deps import require_torch
from neural.errors import NeuralModeUnsupported, NeuralRuntimeUnavailable
from neural.fusion import FusionDiagnostics, build_residual_fusion
from neural.memory import NeuralMemory
from neural.toy_transformer import (
    ToyTransformerConfig,
    assert_module_frozen,
    build_toy_causal_lm,
    freeze_module,
    parameter_checksum,
)


@dataclass
class RuntimeForwardResult:
    logits: Any
    mode: NeuralMode
    base_checksum: str
    fusion_events: list[dict[str, Any]] = field(default_factory=list)
    bypassed: bool = False


@dataclass
class ModelArchitectureAdapter:
    """Boundary over a concrete model family (toy causal for Phase 3)."""

    model: Any
    family: str
    hidden_size: int
    num_layers: int

    def resolve_layers(self, injection_layers: Sequence[int] | None = None) -> list[Any]:
        blocks = list(self.model.blocks)
        if injection_layers is None:
            # Default: last block only.
            indices = [len(blocks) - 1]
        else:
            indices = list(injection_layers)
        resolved: list[Any] = []
        for idx in indices:
            if idx < 0 or idx >= len(blocks):
                raise ValueError(f"injection layer {idx} out of range 0..{len(blocks) - 1}")
            resolved.append(blocks[idx])
        return resolved

    def validate(self) -> None:
        if not hasattr(self.model, "blocks"):
            raise NeuralRuntimeUnavailable("model lacks inspectable blocks", detail={"family": self.family})
        if int(self.hidden_size) < 1 or int(self.num_layers) < 1:
            raise NeuralRuntimeUnavailable("invalid model geometry")


class NeuralModelRuntime:
    """Research runtime: frozen backbone + optional memory fusion."""

    def __init__(
        self,
        *,
        toy_config: ToyTransformerConfig | None = None,
        memory_config: NeuralMemoryConfig | None = None,
        mode: NeuralMode = NeuralMode.OFF,
        injection_layers: Sequence[int] | None = None,
        fusion_scale: float = 0.0,
        device: str = "cpu",
    ) -> None:
        torch = require_torch()
        self.device = torch.device(device)
        self.mode = mode
        self.injection_layers = list(injection_layers) if injection_layers is not None else None
        self.toy_config = toy_config or ToyTransformerConfig()
        model, self.toy_config = build_toy_causal_lm(self.toy_config)
        self.base_model = model.to(self.device)
        freeze_module(self.base_model)
        assert_module_frozen(self.base_model)
        self.base_checksum = parameter_checksum(self.base_model)

        mem_cfg = memory_config or NeuralMemoryConfig(
            dim=self.toy_config.hidden_size,
            hidden_dim=max(32, self.toy_config.hidden_size * 2),
            mode=NeuralMode.OFF,  # memory module mode unused; runtime owns mode
            seed=self.toy_config.seed,
            device=device,
        )
        if mem_cfg.dim != self.toy_config.hidden_size:
            raise ValueError(
                f"memory dim {mem_cfg.dim} must match hidden_size {self.toy_config.hidden_size}"
            )
        self.memory = NeuralMemory(mem_cfg)
        self.fusion = build_residual_fusion(
            hidden_size=self.toy_config.hidden_size,
            memory_dim=mem_cfg.dim,
            scale=fusion_scale,
        ).to(self.device)
        self.adapter = ModelArchitectureAdapter(
            model=self.base_model,
            family=getattr(self.base_model, "architecture_family", "unknown"),
            hidden_size=self.toy_config.hidden_size,
            num_layers=self.toy_config.num_layers,
        )
        self.adapter.validate()
        self._hooks: list[Any] = []
        self._last_fusion_events: list[dict[str, Any]] = []

    def set_mode(self, mode: NeuralMode) -> None:
        if mode is NeuralMode.LEARN:
            # Phase 3: online learning remains unsupported at the runtime boundary.
            raise NeuralModeUnsupported(
                "LEARN mode is not enabled on NeuralModelRuntime in Phase 3",
                detail={"mode": mode.value},
            )
        self.mode = mode

    def set_fusion_scale(self, scale: float) -> None:
        self.fusion.set_scale(scale)

    def verify_base_frozen(self) -> str:
        assert_module_frozen(self.base_model)
        current = parameter_checksum(self.base_model)
        if current != self.base_checksum:
            raise AssertionError("base model weights changed after freeze")
        return current

    def _detach_hooks(self) -> None:
        for handle in self._hooks:
            handle.remove()
        self._hooks.clear()

    def _attach_hooks(self, *, mutate: bool) -> None:
        self._detach_hooks()
        self._last_fusion_events = []
        layers = self.adapter.resolve_layers(self.injection_layers)

        def make_hook(layer_index: int):
            def _hook(_module: Any, _inputs: Any, output: Any) -> Any:
                # output is hidden states [B, T, H]
                flat = output.reshape(-1, output.shape[-1])
                memory_out = self.memory.encode(flat)
                memory_out = memory_out.reshape(output.shape)
                new_hidden, diag = self.fusion(output, memory_out, apply=True)
                event = {"layer": layer_index, **diag.to_dict(), "mutate": mutate}
                self._last_fusion_events.append(event)
                if mutate:
                    return new_hidden
                # SHADOW: diagnostics only — original hidden states continue.
                return output

            return _hook

        for idx, layer in zip(
            self.injection_layers
            if self.injection_layers is not None
            else [self.adapter.num_layers - 1],
            layers,
            strict=True,
        ):
            self._hooks.append(layer.register_forward_hook(make_hook(int(idx))))

    def forward(self, input_ids: Any) -> RuntimeForwardResult:
        torch = require_torch()
        if not isinstance(input_ids, torch.Tensor):
            input_ids = torch.as_tensor(input_ids, dtype=torch.long)
        input_ids = input_ids.to(self.device)
        if input_ids.ndim == 1:
            input_ids = input_ids.unsqueeze(0)

        mode = self.mode
        if mode is NeuralMode.OFF:
            # Hard bypass: no hooks, no memory encode, no fusion.
            self._detach_hooks()
            with torch.no_grad():
                logits = self.base_model(input_ids)
            return RuntimeForwardResult(
                logits=logits,
                mode=mode,
                base_checksum=self.verify_base_frozen(),
                fusion_events=[],
                bypassed=True,
            )

        if mode is NeuralMode.SHADOW:
            self._attach_hooks(mutate=False)
        elif mode is NeuralMode.READ:
            self._attach_hooks(mutate=True)
        else:
            raise NeuralModeUnsupported(f"unsupported runtime mode: {mode}")

        try:
            with torch.no_grad():
                logits = self.base_model(input_ids)
            return RuntimeForwardResult(
                logits=logits,
                mode=mode,
                base_checksum=self.verify_base_frozen(),
                fusion_events=list(self._last_fusion_events),
                bypassed=False,
            )
        finally:
            self._detach_hooks()

    def compatibility_fingerprint(self) -> dict[str, Any]:
        return {
            "family": self.adapter.family,
            "hidden_size": self.adapter.hidden_size,
            "num_layers": self.adapter.num_layers,
            "injection_layers": list(self.injection_layers)
            if self.injection_layers is not None
            else [self.adapter.num_layers - 1],
            "memory_dim": self.memory.config.dim,
            "memory_architecture": self.memory.config.architecture_version,
            "base_checksum": self.base_checksum,
        }
