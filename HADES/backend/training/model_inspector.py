"""Model metadata inspection without loading weights into GPU VRAM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from training.execution_plan import stable_hash

FactSource = Literal["detected", "measured", "estimated", "unknown"]

# Explicit allowlist for custom ATME layer streaming. Unknown families are
# rejected for streaming strategies even if they expose a `layers` attribute.
STREAMING_ARCHITECTURE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "llama",
        "llamaforcausallm",
        "qwen2",
        "qwen2forcausallm",
        "qwen3",
        "qwen3forcausallm",
        "mistral",
        "mistralforcausallm",
    }
)

# First shipped adapter family for RAM/NVMe streaming.
V1_ARCHITECTURE_FAMILY = "llama_like"


class ModelProfile(BaseModel):
    base_model: str
    local_path: str | None = None
    architecture: str | None = None
    model_type: str | None = None
    architecture_family: str | None = None
    num_hidden_layers: int | None = None
    hidden_size: int | None = None
    intermediate_size: int | None = None
    vocab_size: int | None = None
    num_attention_heads: int | None = None
    num_key_value_heads: int | None = None
    torch_dtype: str | None = None
    parameter_count_estimated: int | None = None
    estimated_bytes_per_layer: int | None = None
    estimated_total_weight_bytes: int | None = None
    tied_embeddings: bool | None = None
    quantization: str | None = None
    shard_files: list[str] = Field(default_factory=list)
    shard_total_bytes: int | None = None
    adapter_target_modules: list[str] = Field(default_factory=lambda: ["all-linear"])
    streaming_compatible: bool = False
    streaming_compatibility_reason: str | None = None
    trust_remote_code: bool = False
    sources: dict[str, FactSource] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    profile_hash: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _dtype_nbytes(dtype_name: str | None) -> int:
    name = str(dtype_name or "").lower()
    if "float32" in name or name in {"f32", "fp32"}:
        return 4
    if "bfloat16" in name or "float16" in name or name in {"bf16", "fp16", "f16"}:
        return 2
    if "float8" in name or "int8" in name:
        return 1
    if "int4" in name or "nf4" in name or "4bit" in name:
        return 1  # packed; treated conservatively later
    return 2  # default estimate for modern LLM weights


def _normalize_arch(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _family_for(model_type: str | None, architectures: list[str]) -> tuple[str | None, bool, str | None]:
    candidates = [_normalize_arch(model_type), *[_normalize_arch(item) for item in architectures]]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate in STREAMING_ARCHITECTURE_ALLOWLIST or any(
            candidate.startswith(prefix) for prefix in ("llama", "qwen2", "qwen3", "mistral")
        ):
            return V1_ARCHITECTURE_FAMILY, True, None
    if any(candidates):
        return None, False, "architecture_not_on_atme_streaming_allowlist"
    return None, False, "architecture_unknown"


def _estimate_params(config: dict[str, Any]) -> tuple[int | None, FactSource]:
    if isinstance(config.get("num_parameters"), int):
        return int(config["num_parameters"]), "detected"
    layers = config.get("num_hidden_layers")
    hidden = config.get("hidden_size")
    intermediate = config.get("intermediate_size")
    vocab = config.get("vocab_size")
    heads = config.get("num_attention_heads")
    if not all(isinstance(v, int) and v > 0 for v in (layers, hidden, intermediate, vocab)):
        return None, "unknown"
    # Rough decoder-only estimate: embeddings + N * (attn + mlp) + lm_head if untied.
    assert isinstance(layers, int) and isinstance(hidden, int)
    assert isinstance(intermediate, int) and isinstance(vocab, int)
    head_dim = hidden // int(heads or 1) if isinstance(heads, int) and heads else hidden
    kv_heads = int(config.get("num_key_value_heads") or heads or 1)
    attn = hidden * (hidden + 2 * kv_heads * head_dim)  # q + k + v approx + o later
    attn += hidden * hidden  # o_proj
    mlp = hidden * intermediate * 2  # up/gate-ish + down (conservative for SwiGLU-like)
    if str(config.get("hidden_act") or "").lower() in {"silu", "swiglu"} or "moe" not in str(
        config.get("model_type") or ""
    ).lower():
        # Qwen/Llama SwiGLU: gate + up + down
        mlp = hidden * intermediate * 3
    per_layer = attn + mlp
    embeddings = vocab * hidden
    lm_head = 0 if config.get("tie_word_embeddings") else vocab * hidden
    total = embeddings + lm_head + per_layer * layers
    return int(total), "estimated"


def inspect_local_model_dir(path: Path) -> ModelProfile:
    path = path.expanduser().resolve()
    config = _read_json(path / "config.json") or {}
    architectures = [str(item) for item in (config.get("architectures") or []) if item]
    model_type = str(config.get("model_type") or "") or None
    family, streaming_ok, streaming_reason = _family_for(model_type, architectures)
    dtype = config.get("torch_dtype") or config.get("dtype")
    param_count, param_source = _estimate_params(config)
    bytes_per_param = _dtype_nbytes(str(dtype) if dtype else None)
    total_weight_bytes = int(param_count * bytes_per_param) if param_count else None
    layers = config.get("num_hidden_layers") if isinstance(config.get("num_hidden_layers"), int) else None

    shard_files: list[str] = []
    shard_total = 0
    index = _read_json(path / "model.safetensors.index.json")
    if index and isinstance(index.get("weight_map"), dict):
        shard_files = sorted({str(v) for v in index["weight_map"].values()})
    else:
        for pattern in ("*.safetensors", "*.bin"):
            for child in sorted(path.glob(pattern)):
                if child.name.endswith(".index.json"):
                    continue
                shard_files.append(child.name)
    for name in shard_files:
        candidate = path / name
        if candidate.is_file():
            try:
                shard_total += candidate.stat().st_size
            except OSError:
                pass

    weight_basis = shard_total or total_weight_bytes
    bytes_per_layer = None
    if weight_basis and layers:
        # Exclude embeddings roughly for staging buffer sizing.
        hidden = int(config.get("hidden_size") or 0)
        vocab = int(config.get("vocab_size") or 0)
        embed_bytes = vocab * hidden * bytes_per_param if vocab and hidden else 0
        bytes_per_layer = max(1, (int(weight_basis) - embed_bytes) // layers)

    sources: dict[str, FactSource] = {
        "architecture": "detected" if architectures or model_type else "unknown",
        "num_hidden_layers": "detected" if layers is not None else "unknown",
        "parameter_count_estimated": param_source,
        "shard_files": "detected" if shard_files else "unknown",
        "estimated_total_weight_bytes": "measured" if shard_total else ("estimated" if total_weight_bytes else "unknown"),
    }
    warnings: list[str] = []
    if not streaming_ok:
        warnings.append(streaming_reason or "streaming_incompatible")
    if not shard_files:
        warnings.append("no_local_weight_shards_found")

    profile = ModelProfile(
        base_model=str(path),
        local_path=str(path),
        architecture=architectures[0] if architectures else None,
        model_type=model_type,
        architecture_family=family,
        num_hidden_layers=layers,
        hidden_size=int(config["hidden_size"]) if isinstance(config.get("hidden_size"), int) else None,
        intermediate_size=int(config["intermediate_size"]) if isinstance(config.get("intermediate_size"), int) else None,
        vocab_size=int(config["vocab_size"]) if isinstance(config.get("vocab_size"), int) else None,
        num_attention_heads=int(config["num_attention_heads"]) if isinstance(config.get("num_attention_heads"), int) else None,
        num_key_value_heads=int(config["num_key_value_heads"]) if isinstance(config.get("num_key_value_heads"), int) else None,
        torch_dtype=str(dtype) if dtype else None,
        parameter_count_estimated=param_count,
        estimated_bytes_per_layer=bytes_per_layer,
        estimated_total_weight_bytes=shard_total or total_weight_bytes,
        tied_embeddings=bool(config.get("tie_word_embeddings")) if "tie_word_embeddings" in config else None,
        quantization=str(config.get("quantization_config") or "") or None,
        shard_files=shard_files,
        shard_total_bytes=shard_total or None,
        streaming_compatible=streaming_ok,
        streaming_compatibility_reason=None if streaming_ok else streaming_reason,
        trust_remote_code=False,
        sources=sources,
        warnings=warnings,
    )
    profile.profile_hash = stable_hash(
        {
            "path": str(path),
            "architecture": profile.architecture,
            "model_type": profile.model_type,
            "layers": profile.num_hidden_layers,
            "hidden": profile.hidden_size,
            "params": profile.parameter_count_estimated,
            "shards": profile.shard_files,
            "weight_bytes": profile.estimated_total_weight_bytes,
        }
    )
    return profile


def inspect_model_reference(base_model: str, *, allow_network_metadata: bool = False) -> ModelProfile:
    """Inspect a local Transformers directory or return a conservative remote stub.

    Remote Hub config fetch is intentionally not performed unless a future approved
    network design is added. Planning for remote IDs without local files remains
    low-confidence.
    """

    raw = str(base_model or "").strip()
    if not raw:
        raise ValueError("Basismodel is verplicht.")
    expanded = Path(raw).expanduser()
    looks_local = expanded.is_absolute() or raw.startswith(".") or "\\" in raw or "/" in raw and expanded.exists()
    if expanded.is_dir() and (expanded / "config.json").is_file():
        return inspect_local_model_dir(expanded)
    if looks_local and expanded.exists() and not expanded.is_dir():
        raise ValueError(
            "Basismodel moet een Hugging Face model-ID of lokale Transformers-modelmap zijn; "
            "losse GGUF-bestanden zijn niet direct trainbaar."
        )

    # Remote / unresolved ID: metadata unknown without download.
    _ = allow_network_metadata  # reserved; keep trust_remote_code=False and no auto-fetch.
    profile = ModelProfile(
        base_model=raw,
        local_path=None,
        streaming_compatible=False,
        streaming_compatibility_reason="remote_model_metadata_not_fetched",
        trust_remote_code=False,
        sources={
            "architecture": "unknown",
            "parameter_count_estimated": "unknown",
            "estimated_total_weight_bytes": "unknown",
        },
        warnings=[
            "Model metadata is unknown until weights/config are available locally. "
            "Planner confidence will remain low for streaming strategies."
        ],
    )
    profile.profile_hash = stable_hash({"base_model": raw, "kind": "unresolved_ref"})
    return profile
