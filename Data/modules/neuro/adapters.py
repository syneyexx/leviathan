from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from .residual import (
    ResidualForwardRequest,
    ResidualForwardResult,
    ResidualHookPoint,
    ResidualInjectReceipt,
    ResidualInjectRequest,
    ResidualReadRequest,
    ResidualTensorRef,
)


@dataclass
class DeterministicResidualRuntime:
    """In-process residual port for contract testing and local ablations.

    Truth:
      - supports_residuals = True
      - production_grade = False
      - does not load a real LLM weights file
      - tensor stats are deterministic hashes — not fabricated model activations claimed as real
    """

    n_layers: int = 8
    hidden_size: int = 64
    _state: dict[str, list[float]] = field(default_factory=dict)
    _inject_log: list[dict[str, Any]] = field(default_factory=list)

    def supports_residuals(self) -> bool:
        return True

    def runtime_info(self) -> dict[str, Any]:
        return {
            "kind": "deterministic_toy",
            "production_grade": False,
            "n_layers": self.n_layers,
            "hidden_size": self.hidden_size,
            "truth": {
                "not_a_frontier_model_residual": True,
                "deterministic_contract_runtime": True,
            },
        }

    def list_hook_points(self) -> Sequence[ResidualHookPoint]:
        points: list[ResidualHookPoint] = []
        for idx in range(self.n_layers):
            points.append(ResidualHookPoint(layer_index=idx, name=f"block_{idx}", site="block_out"))
        return points

    def _key(self, hook: ResidualHookPoint) -> str:
        return f"{hook.layer_index}:{hook.site}:{hook.name}"

    def _vector_for(self, hook: ResidualHookPoint, seed: str = "") -> list[float]:
        key = self._key(hook)
        if key in self._state and not seed:
            return list(self._state[key])
        digest = hashlib.sha256(f"{key}|{seed}".encode("utf-8")).digest()
        values = [(digest[i % len(digest)] / 255.0) * 2.0 - 1.0 for i in range(self.hidden_size)]
        if not seed:
            self._state[key] = values
        return values

    def read(self, request: ResidualReadRequest) -> ResidualTensorRef:
        vec = self._vector_for(request.hook)
        return ResidualTensorRef(
            hook=request.hook,
            dtype="f32-stat",
            shape=(self.hidden_size,),
            available=True,
            note=f"deterministic toy residual mean={sum(vec)/len(vec):.4f}",
            metadata={
                "norm": round(math.sqrt(sum(v * v for v in vec)), 6),
                "mean": round(sum(vec) / len(vec), 6),
                "runtime": self.runtime_info(),
            },
        )

    def inject(self, request: ResidualInjectRequest) -> ResidualInjectReceipt:
        if request.mode == "DISABLED":
            return ResidualInjectReceipt(
                implemented=True,
                mode=request.mode,
                hook=request.hook,
                applied=False,
                detail="DISABLED mode — no mutation",
            )
        vec = self._vector_for(request.hook)
        seed = request.payload_ref or request.source
        delta = self._vector_for(request.hook, seed=seed)
        scale = float(request.scale)
        if request.mode == "ADDITIVE":
            updated = [v + scale * d for v, d in zip(vec, delta)]
        elif request.mode == "GATED":
            gate = 1.0 / (1.0 + math.exp(-scale))
            updated = [v + gate * d for v, d in zip(vec, delta)]
        elif request.mode == "REPLACE_SLICE":
            updated = list(delta)
        else:
            return ResidualInjectReceipt(
                implemented=True,
                mode=request.mode,
                hook=request.hook,
                applied=False,
                detail=f"Unknown mode {request.mode}",
            )
        self._state[self._key(request.hook)] = updated
        self._inject_log.append(
            {
                "mode": request.mode,
                "scale": scale,
                "source": request.source,
                "payload_ref": request.payload_ref,
                "hook": request.hook.public_dict(),
            }
        )
        return ResidualInjectReceipt(
            implemented=True,
            mode=request.mode,
            hook=request.hook,
            applied=True,
            detail="Applied on deterministic toy residual state",
        )

    def run_forward(self, request: ResidualForwardRequest) -> ResidualForwardResult:
        receipts = tuple(self.inject(item) for item in request.inject)
        # Produce a deterministic non-LLM stub string — never claim it is model output evidence.
        user = ""
        for msg in request.messages:
            if msg.get("role") == "user":
                user = str(msg.get("content") or "")
                break
        digest = hashlib.sha256(user.encode("utf-8")).hexdigest()[:12]
        text = (
            f"[deterministic-residual-forward digest={digest} "
            f"cortex={request.engage_cortex} critic_rounds={request.critic_rounds}] "
            "Not a model completion; chat completions remain the production path."
        )
        return ResidualForwardResult(
            implemented=True,
            text=text,
            degraded_to_chat_completions=False,
            detail="Deterministic residual forward (toy) — not production LLM output",
            receipts=receipts,
            metadata={"runtime": self.runtime_info()},
        )


@dataclass
class HFTransformersResidualAdapter:
    """Optional HuggingFace/transformers residual adapter.

    Loads only when transformers+torch are importable AND a model_id/path is configured.
    Otherwise reports supports_residuals=False honestly.
    """

    model_id: str | None = None
    device: str = "cpu"
    _available: bool = False
    _error: str | None = None
    _hooks: tuple[ResidualHookPoint, ...] = ()
    _model: Any = None
    _activations: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_id:
            self._available = False
            self._error = "LEVIATHAN_NEURO_RESIDUAL_MODEL unset — HF adapter inactive"
            return
        try:
            import torch  # noqa: F401
            from transformers import AutoConfig  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self._available = False
            self._error = f"transformers/torch unavailable: {exc}"
            return
        try:
            config = AutoConfig.from_pretrained(self.model_id)
            n_layers = int(getattr(config, "num_hidden_layers", None) or getattr(config, "n_layer", 0) or 0)
            if n_layers <= 0:
                n_layers = 12
            self._hooks = tuple(
                ResidualHookPoint(layer_index=i, name=f"hf_block_{i}", site="block_out")
                for i in range(min(n_layers, 48))
            )
            # Do not auto-download giant weights in LEVIATHAN startup.
            # Availability here means config+deps are present; weights load is explicit later.
            self._available = True
            self._error = None
            self._activations["config_only"] = True
            self._activations["n_layers"] = n_layers
        except Exception as exc:  # noqa: BLE001
            self._available = False
            self._error = f"HF config load failed: {exc}"

    def supports_residuals(self) -> bool:
        return self._available

    def runtime_info(self) -> dict[str, Any]:
        return {
            "kind": "hf_transformers",
            "production_grade": False,  # weights not auto-loaded; explicit future work
            "model_id": self.model_id,
            "device": self.device,
            "available": self._available,
            "error": self._error,
            "weights_loaded": bool(self._model is not None),
            "truth": {
                "config_available_is_not_weights_loaded": True,
                "residual_injection_is_not_authority": True,
            },
        }

    def list_hook_points(self) -> Sequence[ResidualHookPoint]:
        return self._hooks if self._available else ()

    def read(self, request: ResidualReadRequest) -> ResidualTensorRef:
        if not self._available:
            return ResidualTensorRef(
                hook=request.hook,
                dtype="none",
                shape=(),
                available=False,
                note=self._error or "HF adapter unavailable",
                metadata=self.runtime_info(),
            )
        return ResidualTensorRef(
            hook=request.hook,
            dtype="config-only",
            shape=(),
            available=False,
            note="HF adapter config-ready but weights not loaded — residual tensor unread",
            metadata=self.runtime_info(),
        )

    def inject(self, request: ResidualInjectRequest) -> ResidualInjectReceipt:
        return ResidualInjectReceipt(
            implemented=self._available,
            mode=request.mode,
            hook=request.hook,
            applied=False,
            detail=(
                "HF adapter present but weight-backed inject not enabled in Phase 47 "
                "(config-only readiness)"
                if self._available
                else (self._error or "HF adapter unavailable")
            ),
        )

    def run_forward(self, request: ResidualForwardRequest) -> ResidualForwardResult:
        receipts = tuple(self.inject(item) for item in request.inject)
        return ResidualForwardResult(
            implemented=False,
            text=None,
            degraded_to_chat_completions=True,
            detail=self._error or "HF residual forward requires loaded weights — degrade to chat",
            receipts=receipts,
            metadata=self.runtime_info(),
        )


def build_residual_runtime(
    *,
    kind: str = "unsupported",
    model_id: str | None = None,
    device: str = "cpu",
    n_layers: int = 8,
    hidden_size: int = 64,
) -> Any:
    """Factory for residual runtimes. Unknown kinds fall back to Unsupported."""
    normalized = (kind or "unsupported").strip().lower()
    if normalized in {"deterministic", "toy", "deterministic_toy"}:
        return DeterministicResidualRuntime(n_layers=n_layers, hidden_size=hidden_size)
    if normalized in {"hf", "transformers", "huggingface"}:
        return HFTransformersResidualAdapter(model_id=model_id, device=device)
    from .residual import UnsupportedResidualRuntime

    return UnsupportedResidualRuntime()
