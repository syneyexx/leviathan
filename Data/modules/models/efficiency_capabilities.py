"""Runtime inference-efficiency capability contracts and probing helpers.

Capability state is never inferred from provider name alone.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.models.contracts import CapabilityState


class EfficiencyFeature(str, Enum):
    PREFIX_CACHE = "prefix_cache"
    KV_CACHE = "kv_cache"
    PERSISTENT_PROMPT_CACHE = "persistent_prompt_cache"
    CONTINUOUS_BATCHING = "continuous_batching"
    SPECULATIVE_DECODING = "speculative_decoding"
    KV_CACHE_QUANTIZATION = "kv_cache_quantization"
    RUNTIME_TOKENIZE = "runtime_tokenize"
    USAGE_CACHED_TOKENS = "usage_cached_tokens"


@dataclass(frozen=True)
class EfficiencyCapability:
    feature: EfficiencyFeature
    state: CapabilityState = CapabilityState.UNKNOWN
    backend: str | None = None
    backend_version: str | None = None
    detail: str | None = None
    controlled_by: str = "unknown"  # leviathan | runtime | provider_external | unknown
    provenance: str = "UNKNOWN"  # MEASURED | RUNTIME_REPORTED | PROVIDER_REPORTED | ESTIMATED | UNKNOWN

    def public_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature.value,
            "state": self.state.value,
            "backend": self.backend,
            "backendVersion": self.backend_version,
            "detail": self.detail,
            "controlledBy": self.controlled_by,
            "provenance": self.provenance,
            "truth": {
                "not_inferred_from_provider_name_alone": True,
                "unknown_remains_unknown": self.state == CapabilityState.UNKNOWN,
            },
        }


@dataclass
class InferenceEfficiencyCapabilities:
    prefix_cache: EfficiencyCapability = field(
        default_factory=lambda: EfficiencyCapability(EfficiencyFeature.PREFIX_CACHE)
    )
    kv_cache: EfficiencyCapability = field(
        default_factory=lambda: EfficiencyCapability(EfficiencyFeature.KV_CACHE)
    )
    persistent_prompt_cache: EfficiencyCapability = field(
        default_factory=lambda: EfficiencyCapability(EfficiencyFeature.PERSISTENT_PROMPT_CACHE)
    )
    continuous_batching: EfficiencyCapability = field(
        default_factory=lambda: EfficiencyCapability(EfficiencyFeature.CONTINUOUS_BATCHING)
    )
    speculative_decoding: EfficiencyCapability = field(
        default_factory=lambda: EfficiencyCapability(EfficiencyFeature.SPECULATIVE_DECODING)
    )
    kv_cache_quantization: EfficiencyCapability = field(
        default_factory=lambda: EfficiencyCapability(EfficiencyFeature.KV_CACHE_QUANTIZATION)
    )
    runtime_tokenize: EfficiencyCapability = field(
        default_factory=lambda: EfficiencyCapability(EfficiencyFeature.RUNTIME_TOKENIZE)
    )
    usage_cached_tokens: EfficiencyCapability = field(
        default_factory=lambda: EfficiencyCapability(EfficiencyFeature.USAGE_CACHED_TOKENS)
    )

    def public_dict(self) -> dict[str, Any]:
        return {
            "prefixCache": self.prefix_cache.public_dict(),
            "kvCache": self.kv_cache.public_dict(),
            "persistentPromptCache": self.persistent_prompt_cache.public_dict(),
            "continuousBatching": self.continuous_batching.public_dict(),
            "speculativeDecoding": self.speculative_decoding.public_dict(),
            "kvCacheQuantization": self.kv_cache_quantization.public_dict(),
            "runtimeTokenize": self.runtime_tokenize.public_dict(),
            "usageCachedTokens": self.usage_cached_tokens.public_dict(),
        }

    def as_list(self) -> list[EfficiencyCapability]:
        return [
            self.prefix_cache,
            self.kv_cache,
            self.persistent_prompt_cache,
            self.continuous_batching,
            self.speculative_decoding,
            self.kv_cache_quantization,
            self.runtime_tokenize,
            self.usage_cached_tokens,
        ]


@dataclass(frozen=True)
class SpeculativeDecodingPolicy:
    mode: str = "auto"  # auto | enabled | disabled
    draft_model_id: str | None = None
    speculative_tokens: int | None = None
    backend_options: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "draftModelId": self.draft_model_id,
            "speculativeTokens": self.speculative_tokens,
            "backendOptions": dict(self.backend_options),
            "truth": {"draft_model_is_not_a_brain": True},
        }


@dataclass(frozen=True)
class NormalizedUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
    usage_source: str = "unavailable"  # provider | runtime | unavailable
    provider_raw_capability: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.total_tokens,
            "cachedInputTokens": self.cached_input_tokens,
            "cacheCreationTokens": self.cache_creation_tokens,
            "cacheReadTokens": self.cache_read_tokens,
            "usageSource": self.usage_source,
            "providerRawCapability": dict(self.provider_raw_capability),
            "truth": {
                "unknown_is_null_not_zero": True,
                "cached_tokens_not_guessed": True,
                "source_provenance": self.usage_source,
            },
        }


def normalize_provider_usage(raw: dict[str, Any] | None) -> NormalizedUsage:
    """Normalize provider usage including cached-token fields when present."""
    if not isinstance(raw, dict) or not raw:
        return NormalizedUsage()

    def _int(key: str, *alts: str) -> int | None:
        for k in (key, *alts):
            val = raw.get(k)
            if isinstance(val, (int, float)) and val >= 0:
                return int(val)
        return None

    input_tokens = _int("input_tokens", "prompt_tokens")
    output_tokens = _int("output_tokens", "completion_tokens")
    total_tokens = _int("total_tokens")
    cached_input = _int(
        "cached_tokens",
        "cache_read_input_tokens",
        "prompt_cache_hit_tokens",
        "cached_input_tokens",
    )
    cache_creation = _int("cache_creation_input_tokens", "cache_creation_tokens", "prompt_cache_miss_tokens")
    cache_read = _int("cache_read_input_tokens", "cache_read_tokens")

    # Nested prompt_tokens_details (OpenAI-style)
    details = raw.get("prompt_tokens_details")
    if isinstance(details, dict):
        if cached_input is None:
            cached_input = _int_from(details, "cached_tokens")
        nested_raw = {f"details.{k}": True for k in details.keys()}
    else:
        nested_raw = {}

    # Anthropic-style
    if cached_input is None and isinstance(raw.get("cache_read_input_tokens"), (int, float)):
        cached_input = int(raw["cache_read_input_tokens"])

    present_keys = [k for k in raw.keys() if isinstance(k, str)]
    capability_meta = {
        "keysPresent": present_keys[:32],
        **nested_raw,
    }
    # Only mark PROVIDER if we got at least one recognized field
    if all(v is None for v in (input_tokens, output_tokens, total_tokens, cached_input, cache_creation, cache_read)):
        return NormalizedUsage(provider_raw_capability=capability_meta)

    return NormalizedUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input,
        cache_creation_tokens=cache_creation,
        cache_read_tokens=cache_read if cache_read is not None else cached_input,
        usage_source="provider",
        provider_raw_capability=capability_meta,
    )


def _int_from(data: dict[str, Any], key: str) -> int | None:
    val = data.get(key)
    if isinstance(val, (int, float)) and val >= 0:
        return int(val)
    return None


def probe_llama_cpp_efficiency(
    *,
    binary_path: str | None = None,
    help_text: str | None = None,
    backend_version: str | None = None,
) -> InferenceEfficiencyCapabilities:
    """Probe llama.cpp-class runtime from help/version text — never assume by name."""
    caps = InferenceEfficiencyCapabilities()
    text = help_text or ""
    version = backend_version
    if binary_path and not text:
        try:
            proc = subprocess.run(
                [binary_path, "--help"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as exc:
            caps.prefix_cache = EfficiencyCapability(
                EfficiencyFeature.PREFIX_CACHE,
                CapabilityState.UNKNOWN,
                backend="llama_cpp",
                detail=f"probe_failed:{exc}",
                controlled_by="runtime",
                provenance="UNKNOWN",
            )
            return caps

    if not text.strip():
        # No evidence — remain UNKNOWN (not unsupported from name alone)
        for feat in EfficiencyFeature:
            setattr(
                caps,
                feat.value if hasattr(caps, feat.value) else feat.name.lower(),
                EfficiencyCapability(
                    feat,
                    CapabilityState.UNKNOWN,
                    backend="llama_cpp",
                    backend_version=version,
                    detail="no_help_text",
                    controlled_by="runtime",
                ),
            )
        # Fix attribute names
        return InferenceEfficiencyCapabilities(
            prefix_cache=EfficiencyCapability(
                EfficiencyFeature.PREFIX_CACHE, CapabilityState.UNKNOWN, backend="llama_cpp",
                backend_version=version, detail="no_help_text", controlled_by="runtime",
            ),
            kv_cache=EfficiencyCapability(
                EfficiencyFeature.KV_CACHE, CapabilityState.UNKNOWN, backend="llama_cpp",
                backend_version=version, detail="kv_is_runtime_owned", controlled_by="runtime",
            ),
            continuous_batching=EfficiencyCapability(
                EfficiencyFeature.CONTINUOUS_BATCHING, CapabilityState.UNKNOWN, backend="llama_cpp",
                backend_version=version, controlled_by="runtime",
            ),
            speculative_decoding=EfficiencyCapability(
                EfficiencyFeature.SPECULATIVE_DECODING, CapabilityState.UNKNOWN, backend="llama_cpp",
                backend_version=version, controlled_by="runtime",
            ),
            kv_cache_quantization=EfficiencyCapability(
                EfficiencyFeature.KV_CACHE_QUANTIZATION, CapabilityState.UNKNOWN, backend="llama_cpp",
                backend_version=version, controlled_by="runtime",
            ),
            runtime_tokenize=EfficiencyCapability(
                EfficiencyFeature.RUNTIME_TOKENIZE, CapabilityState.UNKNOWN, backend="llama_cpp",
                backend_version=version, controlled_by="runtime",
            ),
            usage_cached_tokens=EfficiencyCapability(
                EfficiencyFeature.USAGE_CACHED_TOKENS, CapabilityState.UNKNOWN, backend="llama_cpp",
                backend_version=version, controlled_by="provider_external",
            ),
        )

    lower = text.lower()

    def _flag(*needles: str) -> CapabilityState:
        return CapabilityState.SUPPORTED if any(n in lower for n in needles) else CapabilityState.UNSUPPORTED

    # KV cache always exists conceptually for autoregressive local runtimes when loaded,
    # but LEVIATHAN does not own tensors — report UNVERIFIED until worker READY.
    caps.kv_cache = EfficiencyCapability(
        EfficiencyFeature.KV_CACHE,
        CapabilityState.UNVERIFIED,
        backend="llama_cpp",
        backend_version=version,
        detail="runtime_owned_when_worker_ready",
        controlled_by="runtime",
        provenance="RUNTIME_REPORTED",
    )
    caps.prefix_cache = EfficiencyCapability(
        EfficiencyFeature.PREFIX_CACHE,
        _flag("--cache-prompt", "--prompt-cache", "prefix cache", "slot save"),
        backend="llama_cpp",
        backend_version=version,
        controlled_by="runtime",
        provenance="MEASURED",
    )
    caps.continuous_batching = EfficiencyCapability(
        EfficiencyFeature.CONTINUOUS_BATCHING,
        _flag("cont-batching", "continuous batch", "--cont-batching"),
        backend="llama_cpp",
        backend_version=version,
        controlled_by="runtime",
        provenance="MEASURED",
    )
    caps.speculative_decoding = EfficiencyCapability(
        EfficiencyFeature.SPECULATIVE_DECODING,
        _flag("--draft", "speculative", "draft-model"),
        backend="llama_cpp",
        backend_version=version,
        controlled_by="runtime",
        provenance="MEASURED",
    )
    caps.kv_cache_quantization = EfficiencyCapability(
        EfficiencyFeature.KV_CACHE_QUANTIZATION,
        _flag("--cache-type-k", "--cache-type-v", "kv cache type"),
        backend="llama_cpp",
        backend_version=version,
        controlled_by="runtime",
        provenance="MEASURED",
    )
    caps.runtime_tokenize = EfficiencyCapability(
        EfficiencyFeature.RUNTIME_TOKENIZE,
        _flag("/tokenize", "tokenize"),
        backend="llama_cpp",
        backend_version=version,
        controlled_by="runtime",
        provenance="MEASURED",
    )
    caps.usage_cached_tokens = EfficiencyCapability(
        EfficiencyFeature.USAGE_CACHED_TOKENS,
        CapabilityState.UNVERIFIED,
        backend="llama_cpp",
        backend_version=version,
        detail="observable_if_openai_compat_emits_usage",
        controlled_by="provider_external",
        provenance="UNKNOWN",
    )
    return caps


def probe_vllm_efficiency(
    *,
    help_text: str | None = None,
    backend_version: str | None = None,
) -> InferenceEfficiencyCapabilities:
    text = (help_text or "").lower()
    if not text:
        return InferenceEfficiencyCapabilities(
            continuous_batching=EfficiencyCapability(
                EfficiencyFeature.CONTINUOUS_BATCHING,
                CapabilityState.UNKNOWN,
                backend="vllm_class",
                backend_version=backend_version,
                detail="no_probe_text",
                controlled_by="runtime",
            ),
            prefix_cache=EfficiencyCapability(
                EfficiencyFeature.PREFIX_CACHE,
                CapabilityState.UNKNOWN,
                backend="vllm_class",
                backend_version=backend_version,
                controlled_by="runtime",
            ),
            speculative_decoding=EfficiencyCapability(
                EfficiencyFeature.SPECULATIVE_DECODING,
                CapabilityState.UNKNOWN,
                backend="vllm_class",
                backend_version=backend_version,
                controlled_by="runtime",
            ),
            kv_cache=EfficiencyCapability(
                EfficiencyFeature.KV_CACHE,
                CapabilityState.UNVERIFIED,
                backend="vllm_class",
                backend_version=backend_version,
                detail="runtime_owned",
                controlled_by="runtime",
            ),
        )

    def _flag(*needles: str) -> CapabilityState:
        return CapabilityState.SUPPORTED if any(n in text for n in needles) else CapabilityState.UNSUPPORTED

    return InferenceEfficiencyCapabilities(
        prefix_cache=EfficiencyCapability(
            EfficiencyFeature.PREFIX_CACHE,
            _flag("enable-prefix-caching", "prefix caching", "prefix_caching"),
            backend="vllm_class",
            backend_version=backend_version,
            controlled_by="runtime",
            provenance="MEASURED",
        ),
        kv_cache=EfficiencyCapability(
            EfficiencyFeature.KV_CACHE,
            CapabilityState.UNVERIFIED,
            backend="vllm_class",
            backend_version=backend_version,
            detail="runtime_owned",
            controlled_by="runtime",
            provenance="RUNTIME_REPORTED",
        ),
        continuous_batching=EfficiencyCapability(
            EfficiencyFeature.CONTINUOUS_BATCHING,
            # vLLM continuous batching is core when server runs — still require evidence in help/API
            _flag("continuous batch", "max-num-seqs", "max_num_seqs", "gpu-memory-utilization"),
            backend="vllm_class",
            backend_version=backend_version,
            controlled_by="runtime",
            provenance="MEASURED",
        ),
        speculative_decoding=EfficiencyCapability(
            EfficiencyFeature.SPECULATIVE_DECODING,
            _flag("speculative", "draft-model", "num-speculative-tokens"),
            backend="vllm_class",
            backend_version=backend_version,
            controlled_by="runtime",
            provenance="MEASURED",
        ),
        kv_cache_quantization=EfficiencyCapability(
            EfficiencyFeature.KV_CACHE_QUANTIZATION,
            _flag("kv-cache-dtype", "kv_cache_dtype"),
            backend="vllm_class",
            backend_version=backend_version,
            controlled_by="runtime",
            provenance="MEASURED",
        ),
        usage_cached_tokens=EfficiencyCapability(
            EfficiencyFeature.USAGE_CACHED_TOKENS,
            CapabilityState.UNVERIFIED,
            backend="vllm_class",
            backend_version=backend_version,
            controlled_by="provider_external",
        ),
        runtime_tokenize=EfficiencyCapability(
            EfficiencyFeature.RUNTIME_TOKENIZE,
            CapabilityState.UNKNOWN,
            backend="vllm_class",
            backend_version=backend_version,
            controlled_by="runtime",
        ),
    )


def external_provider_efficiency(*, observes_usage: bool = True) -> InferenceEfficiencyCapabilities:
    """External LM Studio / OpenAI-compatible: observe only, never claim KV ownership."""
    return InferenceEfficiencyCapabilities(
        prefix_cache=EfficiencyCapability(
            EfficiencyFeature.PREFIX_CACHE,
            CapabilityState.UNKNOWN,
            backend="openai_compatible_external",
            detail="provider_managed_if_any",
            controlled_by="provider_external",
        ),
        kv_cache=EfficiencyCapability(
            EfficiencyFeature.KV_CACHE,
            CapabilityState.UNSUPPORTED,
            backend="openai_compatible_external",
            detail="leviathan_does_not_own_provider_kv",
            controlled_by="provider_external",
            provenance="DETERMINISTIC",
        ),
        continuous_batching=EfficiencyCapability(
            EfficiencyFeature.CONTINUOUS_BATCHING,
            CapabilityState.UNKNOWN,
            backend="openai_compatible_external",
            detail="provider_internal",
            controlled_by="provider_external",
        ),
        speculative_decoding=EfficiencyCapability(
            EfficiencyFeature.SPECULATIVE_DECODING,
            CapabilityState.UNKNOWN,
            backend="openai_compatible_external",
            controlled_by="provider_external",
        ),
        usage_cached_tokens=EfficiencyCapability(
            EfficiencyFeature.USAGE_CACHED_TOKENS,
            CapabilityState.UNVERIFIED if observes_usage else CapabilityState.UNKNOWN,
            backend="openai_compatible_external",
            detail="normalized_when_provider_emits_fields",
            controlled_by="provider_external",
            provenance="PROVIDER_REPORTED",
        ),
        persistent_prompt_cache=EfficiencyCapability(
            EfficiencyFeature.PERSISTENT_PROMPT_CACHE,
            CapabilityState.UNKNOWN,
            backend="openai_compatible_external",
            controlled_by="provider_external",
        ),
    )
