"""User-controlled BehaviorProfile — SYSTEM_PROMPT / behavioral steering.

Separate from AuthorityProfile (technical capability scopes).
The SYSTEM_PROMPT is not a cryptographic authorization mechanism.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .seed import (
    SEED_ASSISTANT_DISPLAY_NAME,
    SEED_GREETING_BEHAVIOR,
    SEED_IDENTITY_DESCRIPTION,
    SEED_INTERNAL_IDENTITY_NAME,
    SEED_LANGUAGE_FALLBACK,
    SEED_LANGUAGE_MODE,
    SEED_MEMORY_RELEVANCE_THRESHOLD,
    SEED_MEMORY_TOP_K,
    SEED_REASONING_MODE,
    SEED_RETRIEVAL_MODE,
    SEED_RETRIEVAL_RELEVANCE_THRESHOLD,
    SEED_RETRIEVAL_TOP_K,
    SEED_SELF_DESCRIPTION_BEHAVIOR,
    SEED_SYSTEM_PROMPT,
    SEED_TOOL_USE_STYLE,
)

LANGUAGE_MODES = frozenset({"auto_follow_user", "explicit", "custom"})
RETRIEVAL_MODES = frozenset({"auto", "forced_on", "forced_off"})
REASONING_MODES = frozenset({"auto", "fast", "standard", "deep"})
TOOL_USE_STYLES = frozenset({"minimal", "balanced", "proactive"})


@dataclass(frozen=True)
class BehaviorProfile:
    """Versioned behavioral steering payload for the context compiler.

    Core remains behavior-policy neutral: no hardcoded moral/political/legal
    content rules belong here as source-enforced refusals.
    """

    id: str
    version: str
    system_prompt: str
    # Identity
    assistant_display_name: str = SEED_ASSISTANT_DISPLAY_NAME
    internal_identity_name: str = SEED_INTERNAL_IDENTITY_NAME
    identity_description: str = SEED_IDENTITY_DESCRIPTION
    project_identity: str = ""
    greeting_behavior: str = SEED_GREETING_BEHAVIOR
    self_description_behavior: str = SEED_SELF_DESCRIPTION_BEHAVIOR
    describe_as_local_ai: bool = True
    aliases: tuple[str, ...] = ()
    # Language
    language_mode: str = SEED_LANGUAGE_MODE
    language_explicit: str = ""
    language_fallback: str = SEED_LANGUAGE_FALLBACK
    language_follow_latest_user: bool = True
    technical_term_handling: str = "preserve"
    language_custom_policy: str = ""
    # Core overlays
    project_prompt_overlays: tuple[str, ...] = ()
    task_prompt_overlays: tuple[str, ...] = ()
    reasoning_mode_default: str = SEED_REASONING_MODE
    tool_use_style: str = SEED_TOOL_USE_STYLE
    # Generation (None = provider/model default)
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    seed: int | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    repetition_penalty: float | None = None
    stop_sequences: tuple[str, ...] = ()
    stream_enabled: bool = True
    timeout_seconds: float | None = None
    chat_template_option: str = ""
    context_output_reserve: int | None = None
    # Brain / retrieval
    retrieval_enabled: bool = True
    retrieval_mode: str = SEED_RETRIEVAL_MODE
    retrieval_top_k: int = SEED_RETRIEVAL_TOP_K
    retrieval_relevance_threshold: float = SEED_RETRIEVAL_RELEVANCE_THRESHOLD
    retrieval_rerank: str = "auto"
    retrieval_query_expansion: bool = True
    retrieval_deep_recall: bool = True
    retrieval_max_context_chars: int = 6000
    retrieval_debug_provenance: bool = False
    retrieval_dataset_scopes: tuple[str, ...] = ()
    # Memory
    memory_enabled: bool = True
    memory_top_k: int = SEED_MEMORY_TOP_K
    memory_relevance_threshold: float = SEED_MEMORY_RELEVANCE_THRESHOLD
    memory_scope: str = "conversation"
    # Context / history
    max_history_messages: int | None = None
    compaction_enabled: bool = True
    context_token_budget: int | None = None
    response_reserve_tokens: int | None = None
    diagnostic_visibility: bool = False
    # Background workers (behavior-plane knobs; JobRuntime owns execution)
    workers_profile_enabled: bool = True
    workers_autostart: bool = False
    workers_pool_concurrency: int | None = None
    workers_cpu_budget: float | None = None
    workers_gpu_budget: float | None = None
    workers_queue_limit: int | None = None
    workers_retry_backoff: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    hash: str | None = None

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "system_prompt": self.system_prompt,
            "assistant_display_name": self.assistant_display_name,
            "internal_identity_name": self.internal_identity_name,
            "identity_description": self.identity_description,
            "project_identity": self.project_identity,
            "greeting_behavior": self.greeting_behavior,
            "self_description_behavior": self.self_description_behavior,
            "describe_as_local_ai": self.describe_as_local_ai,
            "aliases": list(self.aliases),
            "language_mode": self.language_mode,
            "language_explicit": self.language_explicit,
            "language_fallback": self.language_fallback,
            "language_follow_latest_user": self.language_follow_latest_user,
            "technical_term_handling": self.technical_term_handling,
            "language_custom_policy": self.language_custom_policy,
            "project_prompt_overlays": list(self.project_prompt_overlays),
            "task_prompt_overlays": list(self.task_prompt_overlays),
            "reasoning_mode_default": self.reasoning_mode_default,
            "tool_use_style": self.tool_use_style,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_output_tokens": self.max_output_tokens,
            "seed": self.seed,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "repetition_penalty": self.repetition_penalty,
            "stop_sequences": list(self.stop_sequences),
            "stream_enabled": self.stream_enabled,
            "timeout_seconds": self.timeout_seconds,
            "chat_template_option": self.chat_template_option,
            "context_output_reserve": self.context_output_reserve,
            "retrieval_enabled": self.retrieval_enabled,
            "retrieval_mode": self.retrieval_mode,
            "retrieval_top_k": self.retrieval_top_k,
            "retrieval_relevance_threshold": self.retrieval_relevance_threshold,
            "retrieval_rerank": self.retrieval_rerank,
            "retrieval_query_expansion": self.retrieval_query_expansion,
            "retrieval_deep_recall": self.retrieval_deep_recall,
            "retrieval_max_context_chars": self.retrieval_max_context_chars,
            "retrieval_debug_provenance": self.retrieval_debug_provenance,
            "retrieval_dataset_scopes": list(self.retrieval_dataset_scopes),
            "memory_enabled": self.memory_enabled,
            "memory_top_k": self.memory_top_k,
            "memory_relevance_threshold": self.memory_relevance_threshold,
            "memory_scope": self.memory_scope,
            "max_history_messages": self.max_history_messages,
            "compaction_enabled": self.compaction_enabled,
            "context_token_budget": self.context_token_budget,
            "response_reserve_tokens": self.response_reserve_tokens,
            "diagnostic_visibility": self.diagnostic_visibility,
            "workers_profile_enabled": self.workers_profile_enabled,
            "workers_autostart": self.workers_autostart,
            "workers_pool_concurrency": self.workers_pool_concurrency,
            "workers_cpu_budget": self.workers_cpu_budget,
            "workers_gpu_budget": self.workers_gpu_budget,
            "workers_queue_limit": self.workers_queue_limit,
            "workers_retry_backoff": self.workers_retry_backoff,
        }

    def compute_hash(self) -> str:
        blob = json.dumps(self._hash_payload(), sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def with_hash(self) -> BehaviorProfile:
        payload = {k: v for k, v in self.__dict__.items() if k != "hash"}
        payload["hash"] = self.compute_hash()
        return BehaviorProfile(**payload)  # type: ignore[arg-type]

    def settings_blob(self) -> dict[str, Any]:
        """Serializable extended settings (identity/language/generation/retrieval/…)."""
        payload = self._hash_payload()
        # Already in dedicated columns
        for key in ("id", "version", "system_prompt", "reasoning_mode_default", "tool_use_style"):
            payload.pop(key, None)
        payload.pop("project_prompt_overlays", None)
        payload.pop("task_prompt_overlays", None)
        return payload

    def composed_system_prompt(self) -> str:
        """Trusted system identity text derived from editable settings."""
        base = (self.system_prompt or "").strip()
        if base:
            return base
        name = (self.assistant_display_name or SEED_ASSISTANT_DISPLAY_NAME).strip()
        desc = (self.identity_description or SEED_IDENTITY_DESCRIPTION).strip()
        return f"You are {name}, {desc}".strip()

    def public_dict(self, *, include_prompt: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "version": self.version,
            "assistant_display_name": self.assistant_display_name,
            "internal_identity_name": self.internal_identity_name,
            "identity_description": self.identity_description,
            "project_identity": self.project_identity,
            "greeting_behavior": self.greeting_behavior,
            "self_description_behavior": self.self_description_behavior,
            "describe_as_local_ai": self.describe_as_local_ai,
            "aliases": list(self.aliases),
            "language_mode": self.language_mode,
            "language_explicit": self.language_explicit,
            "language_fallback": self.language_fallback,
            "language_follow_latest_user": self.language_follow_latest_user,
            "technical_term_handling": self.technical_term_handling,
            "language_custom_policy": self.language_custom_policy,
            "reasoning_mode_default": self.reasoning_mode_default,
            "tool_use_style": self.tool_use_style,
            "project_prompt_overlays_count": len(self.project_prompt_overlays),
            "task_prompt_overlays_count": len(self.task_prompt_overlays),
            "generation": {
                "temperature": self.temperature,
                "top_p": self.top_p,
                "max_output_tokens": self.max_output_tokens,
                "seed": self.seed,
                "frequency_penalty": self.frequency_penalty,
                "presence_penalty": self.presence_penalty,
                "repetition_penalty": self.repetition_penalty,
                "stop_sequences": list(self.stop_sequences),
                "stream_enabled": self.stream_enabled,
                "timeout_seconds": self.timeout_seconds,
                "chat_template_option": self.chat_template_option,
                "context_output_reserve": self.context_output_reserve,
            },
            "retrieval": {
                "enabled": self.retrieval_enabled,
                "mode": self.retrieval_mode,
                "top_k": self.retrieval_top_k,
                "relevance_threshold": self.retrieval_relevance_threshold,
                "rerank": self.retrieval_rerank,
                "query_expansion": self.retrieval_query_expansion,
                "deep_recall": self.retrieval_deep_recall,
                "max_context_chars": self.retrieval_max_context_chars,
                "debug_provenance": self.retrieval_debug_provenance,
                "dataset_scopes": list(self.retrieval_dataset_scopes),
            },
            "memory": {
                "enabled": self.memory_enabled,
                "top_k": self.memory_top_k,
                "relevance_threshold": self.memory_relevance_threshold,
                "scope": self.memory_scope,
            },
            "context": {
                "max_history_messages": self.max_history_messages,
                "compaction_enabled": self.compaction_enabled,
                "token_budget": self.context_token_budget,
                "response_reserve_tokens": self.response_reserve_tokens,
                "diagnostic_visibility": self.diagnostic_visibility,
            },
            "workers": {
                "profile_enabled": self.workers_profile_enabled,
                "autostart": self.workers_autostart,
                "pool_concurrency": self.workers_pool_concurrency,
                "cpu_budget": self.workers_cpu_budget,
                "gpu_budget": self.workers_gpu_budget,
                "queue_limit": self.workers_queue_limit,
                "retry_backoff": self.workers_retry_backoff,
            },
            "hash": self.hash or self.compute_hash(),
            "metadata": self.metadata,
            "truth": {
                "behavior_is_not_authority": True,
                "system_prompt_is_not_capability_grant": True,
            },
        }
        if include_prompt:
            data["system_prompt"] = self.system_prompt
            data["composed_system_prompt"] = self.composed_system_prompt()
            data["project_prompt_overlays"] = list(self.project_prompt_overlays)
            data["task_prompt_overlays"] = list(self.task_prompt_overlays)
        return data


def validate_behavior_patch(payload: dict[str, Any]) -> list[str]:
    """Return validation error messages (empty = ok)."""
    errors: list[str] = []
    if "language_mode" in payload and payload["language_mode"] not in LANGUAGE_MODES:
        errors.append(f"language_mode must be one of {sorted(LANGUAGE_MODES)}")
    if "retrieval_mode" in payload and payload["retrieval_mode"] not in RETRIEVAL_MODES:
        errors.append(f"retrieval_mode must be one of {sorted(RETRIEVAL_MODES)}")
    if "reasoning_mode_default" in payload and payload["reasoning_mode_default"] not in REASONING_MODES:
        errors.append(f"reasoning_mode_default must be one of {sorted(REASONING_MODES)}")
    if "tool_use_style" in payload and payload["tool_use_style"] not in TOOL_USE_STYLES:
        errors.append(f"tool_use_style must be one of {sorted(TOOL_USE_STYLES)}")
    if "system_prompt" in payload:
        sp = payload["system_prompt"]
        if not isinstance(sp, str) or not sp.strip():
            errors.append("system_prompt must be a non-empty string")
        elif len(sp) > 200_000:
            errors.append("system_prompt exceeds 200000 characters")
    for key in ("temperature", "top_p", "frequency_penalty", "presence_penalty", "repetition_penalty"):
        if key in payload and payload[key] is not None:
            try:
                float(payload[key])
            except (TypeError, ValueError):
                errors.append(f"{key} must be a number or null")
    for key in ("retrieval_top_k", "memory_top_k", "max_output_tokens", "max_history_messages"):
        if key in payload and payload[key] is not None:
            try:
                if int(payload[key]) < 0:
                    errors.append(f"{key} must be >= 0")
            except (TypeError, ValueError):
                errors.append(f"{key} must be an integer or null")
    for key in ("retrieval_relevance_threshold", "memory_relevance_threshold"):
        if key in payload and payload[key] is not None:
            try:
                v = float(payload[key])
                if not 0.0 <= v <= 1.0:
                    errors.append(f"{key} must be between 0 and 1")
            except (TypeError, ValueError):
                errors.append(f"{key} must be a float or null")
    return errors


def merge_behavior_patch(current: BehaviorProfile, patch: dict[str, Any]) -> BehaviorProfile:
    """Apply a validated flat patch onto a BehaviorProfile."""
    data = dict(current.__dict__)
    data.pop("hash", None)
    nested_maps = {
        "generation": {
            "temperature": "temperature",
            "top_p": "top_p",
            "max_output_tokens": "max_output_tokens",
            "seed": "seed",
            "frequency_penalty": "frequency_penalty",
            "presence_penalty": "presence_penalty",
            "repetition_penalty": "repetition_penalty",
            "stop_sequences": "stop_sequences",
            "stream_enabled": "stream_enabled",
            "timeout_seconds": "timeout_seconds",
            "chat_template_option": "chat_template_option",
            "context_output_reserve": "context_output_reserve",
        },
        "retrieval": {
            "enabled": "retrieval_enabled",
            "mode": "retrieval_mode",
            "top_k": "retrieval_top_k",
            "relevance_threshold": "retrieval_relevance_threshold",
            "rerank": "retrieval_rerank",
            "query_expansion": "retrieval_query_expansion",
            "deep_recall": "retrieval_deep_recall",
            "max_context_chars": "retrieval_max_context_chars",
            "debug_provenance": "retrieval_debug_provenance",
            "dataset_scopes": "retrieval_dataset_scopes",
        },
        "memory": {
            "enabled": "memory_enabled",
            "top_k": "memory_top_k",
            "relevance_threshold": "memory_relevance_threshold",
            "scope": "memory_scope",
        },
        "context": {
            "max_history_messages": "max_history_messages",
            "compaction_enabled": "compaction_enabled",
            "token_budget": "context_token_budget",
            "response_reserve_tokens": "response_reserve_tokens",
            "diagnostic_visibility": "diagnostic_visibility",
        },
        "workers": {
            "profile_enabled": "workers_profile_enabled",
            "autostart": "workers_autostart",
            "pool_concurrency": "workers_pool_concurrency",
            "cpu_budget": "workers_cpu_budget",
            "gpu_budget": "workers_gpu_budget",
            "queue_limit": "workers_queue_limit",
            "retry_backoff": "workers_retry_backoff",
        },
    }
    flat = dict(patch)
    for nest_key, mapping in nested_maps.items():
        nested = patch.get(nest_key)
        if isinstance(nested, dict):
            for src, dst in mapping.items():
                if src in nested:
                    flat[dst] = nested[src]
    tuple_fields = {
        "aliases",
        "project_prompt_overlays",
        "task_prompt_overlays",
        "stop_sequences",
        "retrieval_dataset_scopes",
    }
    for key, value in flat.items():
        if key in nested_maps or key in {"hash", "id", "truth", "composed_system_prompt"}:
            continue
        if key not in data and key != "metadata":
            continue
        if key in tuple_fields:
            if value is None:
                data[key] = ()
            elif isinstance(value, (list, tuple)):
                data[key] = tuple(str(v) for v in value)
            else:
                data[key] = (str(value),)
        elif key == "metadata" and isinstance(value, dict):
            data[key] = {**dict(data.get("metadata") or {}), **value}
        else:
            data[key] = value
    try:
        ver_i = int(str(data.get("version") or "1"))
        data["version"] = str(ver_i + 1)
    except ValueError:
        data["version"] = f"{data.get('version')}.1"
    return BehaviorProfile(**data).with_hash()  # type: ignore[arg-type]


DEFAULT_BEHAVIOR_PROFILE = BehaviorProfile(
    id="leviathan.default",
    version="3",
    system_prompt=SEED_SYSTEM_PROMPT,
).with_hash()
