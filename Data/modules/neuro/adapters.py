from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .residual import (
    ResidualForwardRequest,
    ResidualForwardResult,
    ResidualHookPoint,
    ResidualInjectReceipt,
    ResidualInjectRequest,
    ResidualReadRequest,
    ResidualTensorRef,
)

VALID_INJECT_MODES = frozenset({"ADDITIVE", "GATED", "REPLACE_SLICE", "DISABLED"})


def _sigmoid(x: float) -> float:
    # Numerically stable logistic for gate scale.
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


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
    _telemetry: list[dict[str, Any]] = field(default_factory=list)
    protocol_version: str = "1.0"

    def supports_residuals(self) -> bool:
        return True

    def runtime_info(self) -> dict[str, Any]:
        return {
            "kind": "deterministic_toy",
            "protocol_version": self.protocol_version,
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

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        self._telemetry.append({"name": name, "payload": payload})

    def read(self, request: ResidualReadRequest) -> ResidualTensorRef:
        vec = self._vector_for(request.hook)
        ref = ResidualTensorRef(
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
        self._emit("residual_read", {"hook": request.hook.public_dict(), "available": True})
        return ref

    def inject(self, request: ResidualInjectRequest) -> ResidualInjectReceipt:
        if request.mode == "DISABLED":
            receipt = ResidualInjectReceipt(
                implemented=True,
                mode=request.mode,
                hook=request.hook,
                applied=False,
                detail="DISABLED mode — no mutation",
                reason="disabled",
                degraded_to_chat_completions=False,
            )
            self._emit("residual_inject", receipt.public_dict())
            return receipt
        if request.mode not in VALID_INJECT_MODES:
            receipt = ResidualInjectReceipt(
                implemented=True,
                mode=request.mode,
                hook=request.hook,
                applied=False,
                detail=f"Unknown mode {request.mode}",
                reason="unknown_mode",
            )
            self._emit("residual_inject", receipt.public_dict())
            return receipt
        vec = self._vector_for(request.hook)
        seed = request.payload_ref or request.source
        delta = self._vector_for(request.hook, seed=seed)
        scale = float(request.scale)
        if request.mode == "ADDITIVE":
            updated = [v + scale * d for v, d in zip(vec, delta)]
        elif request.mode == "GATED":
            gate = _sigmoid(scale)
            updated = [v + gate * d for v, d in zip(vec, delta)]
        else:  # REPLACE_SLICE
            updated = list(delta)
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
        receipt = ResidualInjectReceipt(
            implemented=True,
            mode=request.mode,
            hook=request.hook,
            applied=True,
            detail="Applied on deterministic toy residual state",
            reason="applied_toy",
        )
        self._emit("residual_inject", receipt.public_dict())
        return receipt

    def run_forward(self, request: ResidualForwardRequest) -> ResidualForwardResult:
        receipts = tuple(self.inject(item) for item in request.inject)
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
        result = ResidualForwardResult(
            implemented=True,
            text=text,
            degraded_to_chat_completions=False,
            detail="Deterministic residual forward (toy) — not production LLM output",
            reason="deterministic_forward",
            receipts=receipts,
            metadata={"runtime": self.runtime_info()},
        )
        self._emit("residual_forward", result.public_dict())
        return result


@dataclass
class HFTransformersResidualAdapter:
    """HuggingFace/transformers residual adapter with optional weight-backed hooks.

    Default posture (Phase 52):
      - config probe only when model_id set and deps importable
      - supports_residuals() is True ONLY when weights are explicitly loaded
      - load_weights requires LEVIATHAN_NEURO_RESIDUAL_LOAD_WEIGHTS / load_weights=True
        (high-memory / dev-only)

    Modes: ADDITIVE (h' = h + α·Δ), GATED (h' = h + σ(g)·Δ), DISABLED (honest no-op).
    """

    model_id: str | None = None
    device: str = "cpu"
    load_weights: bool = False
    max_new_tokens: int = 64
    _available: bool = False
    _config_ready: bool = False
    _error: str | None = None
    _hooks: tuple[ResidualHookPoint, ...] = ()
    _model: Any = None
    _tokenizer: Any = None
    _torch: Any = None
    _activations: dict[str, Any] = field(default_factory=dict)
    _pending_injects: dict[str, ResidualInjectRequest] = field(default_factory=dict)
    _hook_handles: list[Any] = field(default_factory=list)
    _telemetry: list[dict[str, Any]] = field(default_factory=list)
    protocol_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.model_id:
            self._available = False
            self._config_ready = False
            self._error = "LEVIATHAN_NEURO_RESIDUAL_MODEL unset — HF adapter inactive"
            return
        try:
            import torch  # noqa: F401
            from transformers import AutoConfig  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self._available = False
            self._config_ready = False
            self._error = f"transformers/torch unavailable: {exc}"
            return
        try:
            config = AutoConfig.from_pretrained(self.model_id)
            n_layers = int(
                getattr(config, "num_hidden_layers", None)
                or getattr(config, "n_layer", 0)
                or getattr(config, "n_layers", 0)
                or 0
            )
            if n_layers <= 0:
                n_layers = 12
            self._hooks = tuple(
                ResidualHookPoint(layer_index=i, name=f"hf_block_{i}", site="block_out")
                for i in range(min(n_layers, 48))
            )
            self._config_ready = True
            self._activations["config_only"] = True
            self._activations["n_layers"] = n_layers
            if self.load_weights:
                self._load_weight_backed_model()
            else:
                self._available = False
                self._error = (
                    "HF config ready but weights not loaded — set "
                    "LEVIATHAN_NEURO_RESIDUAL_LOAD_WEIGHTS=true for weight-backed residuals"
                )
        except Exception as exc:  # noqa: BLE001
            self._available = False
            self._config_ready = False
            self._error = f"HF config load failed: {exc}"

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        self._telemetry.append({"name": name, "payload": payload})

    def _load_weight_backed_model(self) -> None:
        """Explicit high-memory path. Never called at Core boot unless flag is set."""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self._available = False
            self._error = f"weight load blocked — deps missing: {exc}"
            return
        try:
            self._torch = torch
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=False)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                torch_dtype=getattr(torch, "float32"),
                trust_remote_code=False,
            )
            self._model.to(self.device)
            self._model.eval()
            self._register_layer_hooks()
            self._available = True
            self._error = None
            self._activations["config_only"] = False
            self._activations["weights_loaded"] = True
        except Exception as exc:  # noqa: BLE001
            self._available = False
            self._model = None
            self._tokenizer = None
            self._error = f"HF weight load failed: {exc}"

    def _iter_transformer_layers(self) -> list[Any]:
        if self._model is None:
            return []
        for path in (
            ("model", "layers"),
            ("transformer", "h"),
            ("model", "decoder", "layers"),
            ("gpt_neox", "layers"),
        ):
            obj: Any = self._model
            ok = True
            for attr in path:
                if not hasattr(obj, attr):
                    ok = False
                    break
                obj = getattr(obj, attr)
            if ok and obj is not None:
                try:
                    return list(obj)
                except TypeError:
                    continue
        return []

    def _register_layer_hooks(self) -> None:
        layers = self._iter_transformer_layers()
        self._hook_handles.clear()
        for idx, layer in enumerate(layers[: len(self._hooks)]):
            hook = self._hooks[idx]

            def _make_hook(h: ResidualHookPoint) -> Callable[..., Any]:
                def _hook(_module: Any, _inputs: Any, output: Any) -> Any:
                    torch = self._torch
                    tensor = output[0] if isinstance(output, tuple) else output
                    if torch is None or not hasattr(tensor, "detach"):
                        return output
                    # Capture last-token residual stats (no full tensor export as evidence).
                    last = tensor[:, -1, :].detach()
                    flat = last.reshape(-1).float().cpu()
                    values = flat.tolist()
                    key = f"{h.layer_index}:{h.site}:{h.name}"
                    self._activations[key] = values
                    inject = self._pending_injects.get(key)
                    if inject is None or inject.mode == "DISABLED":
                        return output
                    delta_seed = inject.payload_ref or inject.source or "neuro"
                    digest = hashlib.sha256(f"{key}|{delta_seed}".encode("utf-8")).digest()
                    dim = flat.numel()
                    delta = torch.tensor(
                        [(digest[i % len(digest)] / 255.0) * 2.0 - 1.0 for i in range(dim)],
                        dtype=flat.dtype,
                        device=tensor.device,
                    ).view_as(last)
                    scale = float(inject.scale)
                    if inject.mode == "ADDITIVE":
                        last_new = last + scale * delta
                    elif inject.mode == "GATED":
                        gate = _sigmoid(scale)
                        last_new = last + gate * delta
                    elif inject.mode == "REPLACE_SLICE":
                        last_new = delta
                    else:
                        return output
                    # Write back last-token slice only — bounded, explicit mutation.
                    new_tensor = tensor.clone()
                    new_tensor[:, -1, :] = last_new
                    if isinstance(output, tuple):
                        return (new_tensor,) + output[1:]
                    return new_tensor

                return _hook

            handle = layer.register_forward_hook(_make_hook(hook))
            self._hook_handles.append(handle)

    def supports_residuals(self) -> bool:
        return bool(self._available and self._model is not None)

    def runtime_info(self) -> dict[str, Any]:
        return {
            "kind": "hf_transformers",
            "protocol_version": self.protocol_version,
            "production_grade": False,
            "model_id": self.model_id,
            "device": self.device,
            "available": self._available,
            "config_ready": self._config_ready,
            "error": self._error,
            "weights_loaded": bool(self._model is not None),
            "load_weights_requested": self.load_weights,
            "truth": {
                "config_available_is_not_weights_loaded": True,
                "weights_loaded_required_for_supports_residuals": True,
                "residual_injection_is_not_authority": True,
                "high_memory_dev_only_weight_load": True,
            },
        }

    def list_hook_points(self) -> Sequence[ResidualHookPoint]:
        return self._hooks if (self._config_ready or self._available) else ()

    def read(self, request: ResidualReadRequest) -> ResidualTensorRef:
        if not self.supports_residuals():
            ref = ResidualTensorRef(
                hook=request.hook,
                dtype="none",
                shape=(),
                available=False,
                note=self._error or "HF adapter unavailable / weights not loaded",
                metadata=self.runtime_info(),
            )
            self._emit("residual_read", {"available": False, "reason": ref.note})
            return ref
        key = f"{request.hook.layer_index}:{request.hook.site}:{request.hook.name}"
        values = self._activations.get(key)
        if not values:
            ref = ResidualTensorRef(
                hook=request.hook,
                dtype="f32-stat",
                shape=(),
                available=False,
                note="No captured activation yet — run_forward first",
                metadata=self.runtime_info(),
            )
            self._emit("residual_read", {"available": False, "reason": ref.note})
            return ref
        norm = math.sqrt(sum(v * v for v in values))
        ref = ResidualTensorRef(
            hook=request.hook,
            dtype="f32-stat",
            shape=(len(values),),
            available=True,
            note=f"HF residual capture mean={sum(values)/len(values):.4f}",
            metadata={
                "norm": round(norm, 6),
                "mean": round(sum(values) / len(values), 6),
                "runtime": self.runtime_info(),
            },
        )
        self._emit("residual_read", {"available": True, "hook": request.hook.public_dict()})
        return ref

    def inject(self, request: ResidualInjectRequest) -> ResidualInjectReceipt:
        if request.mode == "DISABLED":
            receipt = ResidualInjectReceipt(
                implemented=self.supports_residuals() or self._config_ready,
                mode=request.mode,
                hook=request.hook,
                applied=False,
                detail="DISABLED mode — no mutation",
                reason="disabled",
                degraded_to_chat_completions=not self.supports_residuals(),
            )
            self._emit("residual_inject", receipt.public_dict())
            return receipt
        if not self.supports_residuals():
            receipt = ResidualInjectReceipt(
                implemented=False,
                mode=request.mode,
                hook=request.hook,
                applied=False,
                detail=self._error or "HF weight-backed inject unavailable",
                reason="weights_not_loaded" if self._config_ready else "hf_unavailable",
                degraded_to_chat_completions=True,
            )
            self._emit("residual_inject", receipt.public_dict())
            return receipt
        if request.mode not in VALID_INJECT_MODES:
            receipt = ResidualInjectReceipt(
                implemented=True,
                mode=request.mode,
                hook=request.hook,
                applied=False,
                detail=f"Unknown mode {request.mode}",
                reason="unknown_mode",
            )
            self._emit("residual_inject", receipt.public_dict())
            return receipt
        key = f"{request.hook.layer_index}:{request.hook.site}:{request.hook.name}"
        self._pending_injects[key] = request
        receipt = ResidualInjectReceipt(
            implemented=True,
            mode=request.mode,
            hook=request.hook,
            applied=True,
            detail="Queued weight-backed inject for next forward pass",
            reason="queued_for_forward",
        )
        self._emit("residual_inject", receipt.public_dict())
        return receipt

    def run_forward(self, request: ResidualForwardRequest) -> ResidualForwardResult:
        receipts = tuple(self.inject(item) for item in request.inject)
        if not self.supports_residuals():
            result = ResidualForwardResult(
                implemented=False,
                text=None,
                degraded_to_chat_completions=True,
                detail=self._error or "HF residual forward requires loaded weights — degrade to chat",
                reason="weights_not_loaded" if self._config_ready else "hf_unavailable",
                receipts=receipts,
                metadata=self.runtime_info(),
            )
            self._emit("residual_forward", result.public_dict())
            return result
        try:
            torch = self._torch
            assert torch is not None and self._tokenizer is not None and self._model is not None
            user = ""
            for msg in request.messages:
                if msg.get("role") == "user":
                    user = str(msg.get("content") or "")
                    break
            prompt = user or " "
            encoded = self._tokenizer(prompt, return_tensors="pt")
            encoded = {k: v.to(self.device) for k, v in encoded.items()}
            with torch.no_grad():
                outputs = self._model.generate(
                    **encoded,
                    max_new_tokens=max(1, int(self.max_new_tokens)),
                    do_sample=False,
                )
            text = self._tokenizer.decode(outputs[0], skip_special_tokens=True)
            result = ResidualForwardResult(
                implemented=True,
                text=text,
                degraded_to_chat_completions=False,
                detail="HF weight-backed residual forward completed",
                reason="hf_weight_forward",
                receipts=receipts,
                metadata={
                    "runtime": self.runtime_info(),
                    "engage_cortex": request.engage_cortex,
                    "critic_rounds": request.critic_rounds,
                },
            )
            self._emit("residual_forward", result.public_dict())
            return result
        except Exception as exc:  # noqa: BLE001
            result = ResidualForwardResult(
                implemented=False,
                text=None,
                degraded_to_chat_completions=True,
                detail=f"HF forward failed — degrade to chat: {exc}",
                reason="hf_forward_error",
                receipts=receipts,
                metadata=self.runtime_info(),
            )
            self._emit("residual_forward", result.public_dict())
            return result


@dataclass
class VllmResidualAdapter:
    """vLLM residual adapter — probes endpoint when configured; honest otherwise."""

    endpoint: str | None = None
    protocol_version: str = "1.0"
    _hooks: tuple[ResidualHookPoint, ...] = ()
    _probe_detail: str = "vLLM residual hooks not wired"
    _telemetry: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.endpoint:
            self._probe_detail = "vLLM endpoint unset"
            return
        # Local endpoint metadata probe only — never invent residual support.
        try:
            import urllib.request

            req = urllib.request.Request(
                self.endpoint.rstrip("/") + "/health",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=0.5) as resp:  # noqa: S310
                _ = resp.status
            self._probe_detail = (
                "vLLM endpoint reachable but residual hook plugin not confirmed — "
                "supports_residuals=False"
            )
        except Exception as exc:  # noqa: BLE001
            self._probe_detail = f"vLLM endpoint probe failed: {exc}"

    def supports_residuals(self) -> bool:
        return False

    def runtime_info(self) -> dict[str, Any]:
        return {
            "kind": "vllm",
            "protocol_version": self.protocol_version,
            "production_grade": False,
            "endpoint": self.endpoint,
            "available": False,
            "probe": self._probe_detail,
            "truth": {
                "adapter_requires_hooks_plugin": True,
                "residual_injection_is_not_authority": True,
            },
        }

    def list_hook_points(self) -> Sequence[ResidualHookPoint]:
        return self._hooks

    def read(self, request: ResidualReadRequest) -> ResidualTensorRef:
        return ResidualTensorRef(
            hook=request.hook,
            dtype="none",
            shape=(),
            available=False,
            note=self._probe_detail,
            metadata=self.runtime_info(),
        )

    def inject(self, request: ResidualInjectRequest) -> ResidualInjectReceipt:
        receipt = ResidualInjectReceipt(
            implemented=False,
            mode=request.mode,
            hook=request.hook,
            applied=False,
            detail="vLLM residual adapter — hooks plugin not available",
            reason="vllm_hooks_unavailable",
            degraded_to_chat_completions=True,
        )
        self._telemetry.append({"name": "residual_inject", "payload": receipt.public_dict()})
        return receipt

    def run_forward(self, request: ResidualForwardRequest) -> ResidualForwardResult:
        return ResidualForwardResult(
            implemented=False,
            text=None,
            degraded_to_chat_completions=True,
            detail="vLLM residual forward unavailable — degrade to chat completions",
            reason="vllm_unavailable",
            receipts=tuple(self.inject(item) for item in request.inject),
            metadata=self.runtime_info(),
        )


@dataclass
class LlamaCppResidualAdapter:
    """llama.cpp residual adapter — selected-layer access when custom server exposes hooks."""

    model_path: str | None = None
    server_url: str | None = None
    selected_layers: tuple[int, ...] = ()
    protocol_version: str = "1.0"
    _hooks: tuple[ResidualHookPoint, ...] = ()
    _detail: str = "llama.cpp residual hooks not wired"
    _telemetry: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.selected_layers:
            self._hooks = tuple(
                ResidualHookPoint(layer_index=i, name=f"llama_block_{i}", site="block_out")
                for i in self.selected_layers
            )
        if self.server_url:
            self._detail = (
                "llama.cpp server configured but residual layer API not confirmed — "
                "supports_residuals=False"
            )
        elif self.model_path:
            self._detail = (
                "llama.cpp model_path set but custom residual server not configured — "
                "supports_residuals=False"
            )
        else:
            self._detail = "llama.cpp residual adapter inactive"

    def supports_residuals(self) -> bool:
        # Real selected-layer inject requires a custom server contract not present by default.
        return False

    def runtime_info(self) -> dict[str, Any]:
        return {
            "kind": "llama_cpp",
            "protocol_version": self.protocol_version,
            "production_grade": False,
            "model_path": self.model_path,
            "server_url": self.server_url,
            "selected_layers": list(self.selected_layers),
            "available": False,
            "detail": self._detail,
            "truth": {
                "adapter_stub_until_custom_server": True,
                "residual_injection_is_not_authority": True,
            },
        }

    def list_hook_points(self) -> Sequence[ResidualHookPoint]:
        return self._hooks

    def read(self, request: ResidualReadRequest) -> ResidualTensorRef:
        return ResidualTensorRef(
            hook=request.hook,
            dtype="none",
            shape=(),
            available=False,
            note=self._detail,
            metadata=self.runtime_info(),
        )

    def inject(self, request: ResidualInjectRequest) -> ResidualInjectReceipt:
        receipt = ResidualInjectReceipt(
            implemented=False,
            mode=request.mode,
            hook=request.hook,
            applied=False,
            detail=self._detail,
            reason="llama_cpp_hooks_unavailable",
            degraded_to_chat_completions=True,
        )
        self._telemetry.append({"name": "residual_inject", "payload": receipt.public_dict()})
        return receipt

    def run_forward(self, request: ResidualForwardRequest) -> ResidualForwardResult:
        return ResidualForwardResult(
            implemented=False,
            text=None,
            degraded_to_chat_completions=True,
            detail="llama.cpp residual forward unavailable — degrade to chat completions",
            reason="llama_cpp_unavailable",
            receipts=tuple(self.inject(item) for item in request.inject),
            metadata=self.runtime_info(),
        )


def build_residual_runtime(
    *,
    kind: str = "unsupported",
    model_id: str | None = None,
    device: str = "cpu",
    n_layers: int = 8,
    hidden_size: int = 64,
    load_weights: bool = False,
    selected_layers: tuple[int, ...] | None = None,
    server_url: str | None = None,
) -> Any:
    """Factory for residual runtimes. Unknown kinds fall back to Unsupported."""
    normalized = (kind or "unsupported").strip().lower()
    if normalized in {"deterministic", "toy", "deterministic_toy"}:
        return DeterministicResidualRuntime(n_layers=n_layers, hidden_size=hidden_size)
    if normalized in {"hf", "transformers", "huggingface"}:
        return HFTransformersResidualAdapter(
            model_id=model_id,
            device=device,
            load_weights=load_weights,
        )
    if normalized in {"vllm"}:
        return VllmResidualAdapter(endpoint=model_id)
    if normalized in {"llama_cpp", "llamacpp", "llama.cpp"}:
        return LlamaCppResidualAdapter(
            model_path=model_id,
            server_url=server_url,
            selected_layers=tuple(selected_layers or ()),
        )
    from .residual import UnsupportedResidualRuntime

    return UnsupportedResidualRuntime()
