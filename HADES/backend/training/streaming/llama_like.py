"""Llama-like decoder architecture adapter (Llama / Qwen2 / Qwen3 / Mistral)."""

from __future__ import annotations

from typing import Any, Sequence

from training.streaming.architecture_adapter import ArchitectureLayout


class LlamaLikeAdapter:
    family = "llama_like"

    def matches(self, model: Any) -> bool:
        config = getattr(model, "config", None)
        model_type = str(getattr(config, "model_type", "") or "").lower()
        architectures = [str(item).lower() for item in (getattr(config, "architectures", None) or [])]
        blob = " ".join([model_type, *architectures, type(model).__name__.lower()])
        return any(token in blob for token in ("llama", "qwen2", "qwen3", "mistral"))

    def _base(self, model: Any) -> Any:
        # PEFT wraps the base model.
        inner = model
        if hasattr(inner, "get_base_model"):
            try:
                inner = inner.get_base_model()
            except Exception:
                pass
        if hasattr(inner, "model") and hasattr(inner.model, "layers"):
            return inner.model
        if hasattr(inner, "transformer") and hasattr(inner.transformer, "h"):
            return inner.transformer
        if hasattr(inner, "layers"):
            return inner
        raise ValueError("UNSUPPORTED_ARCHITECTURE: could not locate decoder stack")

    def iter_transformer_blocks(self, model: Any) -> Sequence[Any]:
        base = self._base(model)
        if hasattr(base, "layers"):
            return list(base.layers)
        if hasattr(base, "h"):
            return list(base.h)
        raise ValueError("UNSUPPORTED_ARCHITECTURE: no repeated transformer blocks found")

    def inspect(self, model: Any) -> ArchitectureLayout:
        base = self._base(model)
        blocks = self.iter_transformer_blocks(model)
        layer_names = [f"layers.{index}" for index in range(len(blocks))]
        embed_names: list[str] = []
        if hasattr(base, "embed_tokens"):
            embed_names.append("embed_tokens")
        elif hasattr(base, "wte"):
            embed_names.append("wte")
        norm_names: list[str] = []
        for candidate in ("norm", "final_layernorm", "ln_f"):
            if hasattr(base, candidate):
                norm_names.append(candidate)
        lm_head_names: list[str] = []
        root = model.get_base_model() if hasattr(model, "get_base_model") else model
        if hasattr(root, "lm_head"):
            lm_head_names.append("lm_head")
        tied: list[tuple[str, str]] = []
        config = getattr(model, "config", None)
        if bool(getattr(config, "tie_word_embeddings", False)) and embed_names and lm_head_names:
            tied.append((embed_names[0], lm_head_names[0]))
        return ArchitectureLayout(
            family=self.family,
            embedding_module_names=embed_names,
            layer_module_names=layer_names,
            final_norm_module_names=norm_names,
            lm_head_module_names=lm_head_names,
            tied_parameter_pairs=tied,
            lora_target_module_names=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
            execution_order=[*embed_names, *layer_names, *norm_names, *lm_head_names],
            persistent_modules=[*embed_names, *norm_names, *lm_head_names],
        )
