"""Runtime binding + format-aware servability (source ≠ runtime)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from Data.modules.models.contracts import (
    ModelDescriptor,
    ModelRuntimeBinding,
    RuntimeCapabilities,
    ServabilityState,
)


MANAGED_KINDS = frozenset({"llama_cpp", "llamacpp", "llama.cpp", "vllm", "vllm_class", "vllm-class"})
EXTERNAL_KINDS = frozenset({"lm_studio", "lmstudio", "ollama", "openai_compatible", "openai"})


def infer_runtime_kind(
    *,
    provider_type: str | None,
    runtime_id: str | None,
    format_name: str | None,
    managed_hint: bool = False,
) -> str:
    pt = (provider_type or "").strip().lower()
    rt = (runtime_id or "").strip().lower()
    fmt = (format_name or "").strip().lower()
    if pt in MANAGED_KINDS or rt in MANAGED_KINDS:
        if "vllm" in pt or "vllm" in rt:
            return "vllm_class"
        if "llama" in pt or "llama" in rt or fmt == "gguf":
            return "llama_cpp"
        return pt or rt
    if pt in EXTERNAL_KINDS or rt in {"lm_studio", "ollama"}:
        if pt in {"lm_studio", "lmstudio"} or rt in {"lm_studio", "lmstudio"}:
            return "lm_studio"
        if pt == "ollama" or rt == "ollama":
            return "ollama"
        return "openai_compatible"
    if pt == "local_import":
        # Source/provider conflation: local_import is acquisition, not a runtime.
        if fmt == "gguf":
            return "llama_cpp"
        if fmt in {"safetensors", "transformers", "hf"}:
            return "vllm_class"
        return "unknown"
    if fmt == "gguf":
        return "llama_cpp" if managed_hint else "unknown"
    if fmt in {"safetensors", "transformers", "hf"}:
        return "vllm_class" if managed_hint else "unknown"
    return pt or rt or "unknown"


def assess_gguf_servability(
    local_path: str | None,
    *,
    llama_cpp_executable: str | None,
    managed_enabled: bool,
) -> tuple[ServabilityState, str | None]:
    if not local_path:
        return ServabilityState.UNAVAILABLE, "GGUF local path missing"
    path = Path(local_path)
    if not path.is_file():
        return ServabilityState.UNAVAILABLE, f"GGUF file not found: {local_path}"
    if not managed_enabled:
        return (
            ServabilityState.UNAVAILABLE,
            "Managed llama.cpp serving is disabled",
        )
    if not llama_cpp_executable:
        return (
            ServabilityState.UNAVAILABLE,
            "llama.cpp executable not configured (LEVIATHAN_LLAMA_CPP_EXECUTABLE)",
        )
    exe = Path(llama_cpp_executable)
    if not exe.exists():
        return (
            ServabilityState.UNAVAILABLE,
            f"llama.cpp executable not found: {llama_cpp_executable}",
        )
    return ServabilityState.SERVABLE, None


def assess_transformers_snapshot(local_path: str | None) -> tuple[ServabilityState, str | None]:
    """A lone .safetensors file is NOT automatically a complete inference model."""
    if not local_path:
        return ServabilityState.UNAVAILABLE, "model snapshot path missing"
    path = Path(local_path)
    if path.is_file() and path.suffix.lower() == ".safetensors":
        parent = path.parent
        config = parent / "config.json"
        if not config.is_file():
            return (
                ServabilityState.UNAVAILABLE,
                "Incomplete transformers snapshot: lone .safetensors without config.json",
            )
        # Check for sharded index or sibling shards
        index = parent / "model.safetensors.index.json"
        if index.is_file():
            try:
                data = json.loads(index.read_text(encoding="utf-8"))
                weight_map = data.get("weight_map") or {}
                required = sorted(set(weight_map.values()))
                missing = [name for name in required if not (parent / name).is_file()]
                if missing:
                    return (
                        ServabilityState.UNAVAILABLE,
                        f"Incomplete safetensors shard set; missing: {missing[:5]}",
                    )
            except (OSError, json.JSONDecodeError) as exc:
                return ServabilityState.UNAVAILABLE, f"Invalid shard index: {exc}"
        return ServabilityState.SERVABLE, None
    if path.is_dir():
        config = path / "config.json"
        if not config.is_file():
            return ServabilityState.UNAVAILABLE, "HF snapshot missing config.json"
        has_weights = any(path.glob("*.safetensors")) or any(path.glob("pytorch_model*.bin"))
        if not has_weights:
            return ServabilityState.UNAVAILABLE, "HF snapshot missing weight files"
        index = path / "model.safetensors.index.json"
        if index.is_file():
            try:
                data = json.loads(index.read_text(encoding="utf-8"))
                weight_map = data.get("weight_map") or {}
                required = sorted(set(weight_map.values()))
                missing = [name for name in required if not (path / name).is_file()]
                if missing:
                    return (
                        ServabilityState.UNAVAILABLE,
                        f"Incomplete safetensors shard set; missing: {missing[:5]}",
                    )
            except (OSError, json.JSONDecodeError) as exc:
                return ServabilityState.UNAVAILABLE, f"Invalid shard index: {exc}"
        tokenizer_ok = (
            (path / "tokenizer.json").is_file()
            or (path / "tokenizer_config.json").is_file()
            or (path / "vocab.json").is_file()
        )
        if not tokenizer_ok:
            return (
                ServabilityState.UNAVAILABLE,
                "HF snapshot missing tokenizer files",
            )
        return ServabilityState.SERVABLE, None
    return ServabilityState.UNAVAILABLE, f"Unrecognized local path: {local_path}"


def build_runtime_binding(
    model: ModelDescriptor,
    *,
    provider_type: str | None,
    provider_endpoint: str | None = None,
    managed_serving_enabled: bool = False,
    llama_cpp_executable: str | None = None,
    vllm_executable: str | None = None,
    caps: RuntimeCapabilities | None = None,
) -> ModelRuntimeBinding:
    kind = infer_runtime_kind(
        provider_type=provider_type,
        runtime_id=model.runtime_id,
        format_name=model.format,
        managed_hint=managed_serving_enabled,
    )
    managed = False
    state = ServabilityState.UNKNOWN
    reason: str | None = None
    backend_model_id = str(model.metadata.get("provider_model_id") or model.display_name)

    if kind in {"lm_studio", "ollama", "openai_compatible"}:
        managed = False
        state = ServabilityState.SERVABLE if provider_endpoint else ServabilityState.UNAVAILABLE
        reason = None if provider_endpoint else "external endpoint missing"
    elif kind == "llama_cpp":
        managed = bool(managed_serving_enabled)
        state, reason = assess_gguf_servability(
            model.local_path,
            llama_cpp_executable=llama_cpp_executable,
            managed_enabled=managed,
        )
        if not managed and model.endpoint:
            # Unmanaged llama.cpp already running elsewhere
            managed = False
            state = ServabilityState.SERVABLE
            reason = "external llama.cpp endpoint"
    elif kind == "vllm_class":
        managed = bool(managed_serving_enabled and vllm_executable)
        if not managed_serving_enabled:
            state = ServabilityState.UNAVAILABLE
            reason = "Managed vLLM serving is disabled"
        elif not vllm_executable:
            state = ServabilityState.UNAVAILABLE
            reason = "vLLM executable/module not configured"
        else:
            state, reason = assess_transformers_snapshot(model.local_path)
            if state == ServabilityState.SERVABLE and not Path(vllm_executable).exists():
                # Allow module-style entrypoints like "python" — existence checked at start.
                if "/" in vllm_executable or "\\" in vllm_executable:
                    state = ServabilityState.UNAVAILABLE
                    reason = f"vLLM executable not found: {vllm_executable}"
    else:
        managed = False
        if model.provider_id == "local_import":
            state = ServabilityState.UNAVAILABLE
            reason = (
                "local_import is a model source, not a runtime; "
                "bind a llama.cpp or vLLM runtime to serve this file"
            )
        else:
            state = ServabilityState.UNKNOWN
            reason = "runtime kind unknown"

    return ModelRuntimeBinding(
        model_id=model.id,
        runtime_kind=kind,
        runtime_provider_id=model.provider_id,
        backend_model_id=backend_model_id,
        local_path=model.local_path,
        managed=managed and state == ServabilityState.SERVABLE,
        servability_state=state,
        servability_reason=reason,
        runtime_capabilities=caps,
        metadata={
            "source": model.source.value if hasattr(model.source, "value") else str(model.source),
            "format": model.format,
            "providerType": provider_type,
        },
    )


def binding_from_row(row: dict[str, Any]) -> ModelRuntimeBinding:
    try:
        state = ServabilityState(str(row.get("servability_state") or "UNKNOWN"))
    except ValueError:
        state = ServabilityState.UNKNOWN
    return ModelRuntimeBinding(
        model_id=row["model_id"],
        runtime_kind=str(row.get("runtime_kind") or "unknown"),
        runtime_provider_id=row.get("runtime_provider_id"),
        backend_model_id=row.get("backend_model_id"),
        local_path=row.get("local_path"),
        managed=bool(row.get("managed")),
        servability_state=state,
        servability_reason=row.get("servability_reason"),
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
    )


def binding_to_row(binding: ModelRuntimeBinding) -> dict[str, Any]:
    return {
        "model_id": binding.model_id,
        "runtime_kind": binding.runtime_kind,
        "runtime_provider_id": binding.runtime_provider_id,
        "backend_model_id": binding.backend_model_id,
        "local_path": binding.local_path,
        "managed": binding.managed,
        "servability_state": binding.servability_state.value,
        "servability_reason": binding.servability_reason,
        "metadata": dict(binding.metadata),
    }
