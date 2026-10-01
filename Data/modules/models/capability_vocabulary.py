"""Canonical model capability vocabulary + alias normalization.

Backend is the single authority for capability names. Frontend and routers
must normalize through this module — no parallel taxonomies.
"""

from __future__ import annotations

from typing import Final

from Data.modules.models.contracts import CapabilityName, ModelCapabilities

# Public camelCase names (CapabilityName) — order is stable for APIs/tests.
CANONICAL_CAPABILITIES: Final[tuple[str, ...]] = (
    "chat",
    "reasoning",
    "coding",
    "toolCalling",
    "parallelToolCalls",
    "structuredOutput",
    "jsonSchemaResponse",
    "reasoningEffort",
    "logprobs",
    "streamingToolDeltas",
    "multiCandidate",
    "vision",
    "embeddings",
    "streaming",
)

# Dataclass attribute names on ModelCapabilities.
_CANONICAL_TO_ATTR: Final[dict[str, str]] = {
    "chat": "chat",
    "reasoning": "reasoning",
    "coding": "coding",
    "toolCalling": "tool_calling",
    "parallelToolCalls": "parallel_tool_calls",
    "structuredOutput": "structured_output",
    "jsonSchemaResponse": "json_schema_response",
    "reasoningEffort": "reasoning_effort",
    "logprobs": "logprobs",
    "streamingToolDeltas": "streaming_tool_deltas",
    "multiCandidate": "multi_candidate",
    "vision": "vision",
    "embeddings": "embeddings",
    "streaming": "streaming",
}

_ATTR_TO_CANONICAL: Final[dict[str, str]] = {v: k for k, v in _CANONICAL_TO_ATTR.items()}

# Aliases that normalize to a canonical CapabilityName.
# NOTE: rerank is intentionally NOT mapped to embeddings — it is unsupported
# as a model capability until a dedicated capability exists.
_ALIAS_TO_CANONICAL: Final[dict[str, str]] = {
    # identity
    **{name: name for name in CANONICAL_CAPABILITIES},
    **{attr: _ATTR_TO_CANONICAL[attr] for attr in _ATTR_TO_CANONICAL},
    # common snake / alternate spellings
    "tool_calling": "toolCalling",
    "tool-calling": "toolCalling",
    "tools": "toolCalling",
    "parallel_tool_calls": "parallelToolCalls",
    "parallel-tool-calls": "parallelToolCalls",
    "structured_output": "structuredOutput",
    "structured-output": "structuredOutput",
    "json_schema_response": "jsonSchemaResponse",
    "json_schema": "jsonSchemaResponse",
    "jsonSchema": "jsonSchemaResponse",
    "reasoning_effort": "reasoningEffort",
    "streaming_tool_deltas": "streamingToolDeltas",
    "streaming-tool-deltas": "streamingToolDeltas",
    "multi_candidate": "multiCandidate",
    "multi-candidate": "multiCandidate",
    "n": "multiCandidate",
    "embedding": "embeddings",
    "embed": "embeddings",
    "stream": "streaming",
}

# Explicitly rejected aliases (do not coerce to another capability).
UNSUPPORTED_CAPABILITY_ALIASES: Final[frozenset[str]] = frozenset(
    {
        "rerank",
        "reranking",
        "reranker",
        "cross_encoder",
        "cross-encoder",
    }
)


class UnknownCapabilityAlias(ValueError):
    """Raised when a capability name cannot be normalized."""


def normalize_capability_name(name: str, *, strict: bool = False) -> str | None:
    """Normalize snake_case / camelCase / alias → canonical CapabilityName.

    Returns None for unsupported aliases (e.g. rerank) when strict=False.
    Raises UnknownCapabilityAlias when strict=True and name is unknown/unsupported.
    """
    raw = str(name or "").strip()
    if not raw:
        if strict:
            raise UnknownCapabilityAlias("empty capability name")
        return None
    key = raw
    lower = raw.lower().replace("-", "_")
    if key in UNSUPPORTED_CAPABILITY_ALIASES or lower in UNSUPPORTED_CAPABILITY_ALIASES:
        if strict:
            raise UnknownCapabilityAlias(f"unsupported capability alias: {raw}")
        return None
    # Try exact, then camel as-is, then snake lower.
    if key in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[key]
    if lower in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[lower]
    # camelCase case-insensitive fallback against canonical set
    for canonical in CANONICAL_CAPABILITIES:
        if canonical.lower() == lower:
            return canonical
    if strict:
        raise UnknownCapabilityAlias(f"unknown capability: {raw}")
    return None


def capability_attr(name: str) -> str:
    """Map any recognized capability name to ModelCapabilities attribute.

    Unknown names are returned unchanged (getattr will yield default UNKNOWN
    when callers use a default). Unsupported aliases like ``rerank`` raise.
    """
    raw = str(name or "").strip()
    lower = raw.lower().replace("-", "_")
    if raw in UNSUPPORTED_CAPABILITY_ALIASES or lower in UNSUPPORTED_CAPABILITY_ALIASES:
        raise UnknownCapabilityAlias(
            f"capability '{raw}' is not supported (do not map rerank→embeddings)"
        )
    canonical = normalize_capability_name(raw)
    if canonical is None:
        return raw
    return _CANONICAL_TO_ATTR[canonical]


def is_canonical_capability(name: str) -> bool:
    return normalize_capability_name(name) in CANONICAL_CAPABILITIES


def all_capability_attrs() -> tuple[str, ...]:
    return tuple(_CANONICAL_TO_ATTR[c] for c in CANONICAL_CAPABILITIES)


def empty_capabilities() -> ModelCapabilities:
    return ModelCapabilities()


# Type re-export for callers / type checkers.
CapabilityNameT = CapabilityName
