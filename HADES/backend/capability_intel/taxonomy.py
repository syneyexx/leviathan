"""First-class HADES capability kinds and shared enumerations.

A plugin is a container. These kinds are semantic routing types — never
inferred solely from ``plugin_type``.
"""

from __future__ import annotations

from typing import Final, Literal

CONTRACT_VERSION: Final[int] = 1

CapabilityKind = Literal[
    "skill",
    "knowledge",
    "tool",
    "tool_provider",
    "mcp_provider",
    "agent",
    "service",
    "workflow",
    "resource",
]

CAPABILITY_KINDS: Final[tuple[CapabilityKind, ...]] = (
    "skill",
    "knowledge",
    "tool",
    "tool_provider",
    "mcp_provider",
    "agent",
    "service",
    "workflow",
    "resource",
)

HealthState = Literal["available", "degraded", "unavailable", "needs_setup", "blocked", "unknown"]
HEALTH_STATES: Final[tuple[HealthState, ...]] = (
    "available",
    "degraded",
    "unavailable",
    "needs_setup",
    "blocked",
    "unknown",
)

CostClass = Literal["cheap", "moderate", "expensive"]
LatencyClass = Literal["fast", "normal", "slow"]
SideEffectClass = Literal["none", "read", "write", "network", "process"]

COST_RANK: Final[dict[str, int]] = {"cheap": 0, "moderate": 1, "expensive": 2}
LATENCY_RANK: Final[dict[str, int]] = {"fast": 0, "normal": 1, "slow": 2}
SIDE_EFFECT_RANK: Final[dict[str, int]] = {"none": 0, "read": 1, "write": 2, "network": 3, "process": 4}

# Kinds that never constitute an external side-effect by themselves.
REASONING_KINDS: Final[frozenset[str]] = frozenset({"skill", "knowledge", "resource"})

# Kinds that may execute through PluginManager / MCP / native runtimes.
EXECUTABLE_KINDS: Final[frozenset[str]] = frozenset(
    {"tool", "tool_provider", "mcp_provider", "agent", "service", "workflow"}
)

# Built-in HADES providers participate in the same registry.
NATIVE_PROVIDER_ID: Final[str] = "hades.native"

MESSAGE_TYPES: Final[tuple[str, ...]] = (
    "task_assignment",
    "task_handoff",
    "finding",
    "question",
    "answer",
    "proposal",
    "critique",
    "artifact_reference",
    "evidence_reference",
    "verification_request",
    "verification_result",
    "blocked",
    "completed",
)

AGENT_ROLES: Final[tuple[str, ...]] = (
    "lead",
    "planner",
    "researcher",
    "specialist",
    "implementation_owner",
    "reviewer",
    "verifier",
)

# Conservative default composition budgets. Escalation is explicit.
DEFAULT_BUDGETS: Final[dict[str, int]] = {
    "max_agents": 3,
    "max_delegation_depth": 2,
    "max_messages": 24,
    "max_critique_cycles": 2,
    "max_retries": 2,
    "max_tool_rounds": 8,
    "max_consultations": 4,
    "max_model_calls": 12,
    "max_context_chars": 24_000,
    "skill_fragment_chars": 1_200,
    "skill_max_items": 4,
}


def is_capability_kind(value: str | None) -> bool:
    return str(value or "").strip().lower() in CAPABILITY_KINDS


def normalize_kind(value: str | None) -> CapabilityKind | None:
    text = str(value or "").strip().lower()
    return text if text in CAPABILITY_KINDS else None


def normalize_health(value: str | None) -> HealthState:
    text = str(value or "unknown").strip().lower()
    return text if text in HEALTH_STATES else "unknown"


def normalize_cost(value: str | None) -> CostClass:
    text = str(value or "moderate").strip().lower()
    return text if text in COST_RANK else "moderate"


def normalize_latency(value: str | None) -> LatencyClass:
    text = str(value or "normal").strip().lower()
    return text if text in LATENCY_RANK else "normal"


def normalize_side_effect(value: str | None) -> SideEffectClass:
    text = str(value or "none").strip().lower()
    return text if text in SIDE_EFFECT_RANK else "none"
