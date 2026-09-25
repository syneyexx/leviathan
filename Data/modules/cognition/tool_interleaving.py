"""Tool ↔ native-reasoning interleaving policy (F18 / R16).

Iterative tools already exist in CognitiveRuntime's loop. This module decides
when a tool/capability round should be inserted *between* native-reasoning
model calls — only when the capability profile claims tool interleaving.

Never invents provider tool-calling support from model names.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def profile_supports_tool_interleaving(profile: Any | None) -> bool:
    """True only when the resolved profile explicitly supports interleaving."""
    if profile is None:
        return False
    if isinstance(profile, Mapping):
        return bool(profile.get("supports_tool_interleaving"))
    return bool(getattr(profile, "supports_tool_interleaving", False))


def last_action_kind(actions: Sequence[Any] | None) -> str | None:
    if not actions:
        return None
    last = actions[-1]
    kind = getattr(last, "kind", None)
    if kind is None and isinstance(last, Mapping):
        kind = last.get("kind")
    if kind is None:
        return None
    return str(getattr(kind, "value", kind))


def observation_kinds(observations: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    for obs in observations or ():
        kind = getattr(obs, "kind", None)
        if kind is None and isinstance(obs, Mapping):
            kind = obs.get("kind")
        if kind is None:
            continue
        out.append(str(getattr(kind, "value", kind)))
    return out


def should_interleave_tool_after_native(
    *,
    capability_profile: Any | None,
    inference_path: str | None,
    native_effort: str | None,
    actions: Sequence[Any] | None,
    observations: Sequence[Any] | None,
    tool_budget_remaining: int,
    task_requires_tools: bool = False,
    strategy: str | None = None,
) -> bool:
    """Prefer a tool/capability round after a native MODEL_CALL when allowed.

    Conditions (all required unless noted):
    - profile.supports_tool_interleaving
    - tool budget remains
    - last action was MODEL_CALL or RESPOND on a native (or high-effort) path
    - no TOOL_RESULT yet for this interleave window, OR task/strategy still needs tools
    """
    if tool_budget_remaining <= 0:
        return False
    if not profile_supports_tool_interleaving(capability_profile):
        return False

    path = (inference_path or "").strip().lower()
    effort = (native_effort or "").strip().upper()
    native_active = path == "native" or effort in {
        "LOW",
        "MEDIUM",
        "HIGH",
        "MAXIMUM",
        "MINIMAL",
    }
    if not native_active:
        return False

    last = last_action_kind(actions)
    if last not in {"MODEL_CALL", "RESPOND"}:
        return False

    kinds = observation_kinds(observations)
    tool_done = "TOOL_RESULT" in kinds
    strategy_s = (strategy or "").strip().upper()
    strategy_wants_tools = strategy_s in {
        "TOOL_DRIVEN",
        "PLAN_EXECUTE_VERIFY",
        "RETRIEVE_THEN_ANSWER",
        "DEBUG_LOOP",
        "CODING_REPAIR",
        "RESEARCH_SYNTHESIS",
    }
    if tool_done and not (task_requires_tools or strategy_wants_tools):
        # One tool round already landed and nothing still demands tools.
        return False
    return True


def interleave_boost(
    *,
    capability_profile: Any | None,
    inference_path: str | None = None,
    native_effort: str | None = None,
    actions: Sequence[Any] | None = None,
    observations: Sequence[Any] | None = None,
    tool_budget_remaining: int = 0,
    task_requires_tools: bool = False,
    strategy: str | None = None,
    base_boost: float = 0.35,
) -> float:
    """Score boost for tool/capability candidates when interleaving is active."""
    if should_interleave_tool_after_native(
        capability_profile=capability_profile,
        inference_path=inference_path,
        native_effort=native_effort,
        actions=actions,
        observations=observations,
        tool_budget_remaining=tool_budget_remaining,
        task_requires_tools=task_requires_tools,
        strategy=strategy,
    ):
        return float(base_boost)
    return 0.0


def interleaving_public_status(
    *,
    capability_profile: Any | None,
    active: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    supported = profile_supports_tool_interleaving(capability_profile)
    return {
        "supports_tool_interleaving": supported,
        "interleave_active": bool(active) and supported,
        "reason": reason,
        "truth": {
            "iterative_tools_exist_in_loop": True,
            "interleaving_requires_profile_support": True,
            "never_invent_tool_interleaving_from_model_name": True,
            "native_reasoning_may_yield_to_tools": True,
        },
    }


__all__ = (
    "interleave_boost",
    "interleaving_public_status",
    "last_action_kind",
    "observation_kinds",
    "profile_supports_tool_interleaving",
    "should_interleave_tool_after_native",
)
