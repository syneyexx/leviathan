"""Reasoning mode semantics for Chat — maps BehaviorProfile modes to runtime.

Canonical values: auto | fast | standard | deep
(also accepts cognition-style FAST/STANDARD/DEEP/ADAPTIVE)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from Data.modules.reasoning.engine import ReasoningPlan

CANONICAL_MODES = frozenset({"auto", "fast", "standard", "deep"})


def normalize_reasoning_mode(value: str | None) -> str:
    raw = (value or "auto").strip().lower()
    aliases = {
        "adaptive": "auto",
        "adadaptive": "auto",
        "maximum": "deep",
        "max": "deep",
    }
    raw = aliases.get(raw, raw)
    if raw in CANONICAL_MODES:
        return raw
    upper = (value or "").strip().upper()
    if upper in {"FAST", "STANDARD", "DEEP", "ADAPTIVE", "MAXIMUM"}:
        return {
            "FAST": "fast",
            "STANDARD": "standard",
            "DEEP": "deep",
            "ADAPTIVE": "auto",
            "MAXIMUM": "deep",
        }[upper]
    return "auto"


def to_cognition_depth(mode: str) -> str:
    mapped = {
        "auto": "ADAPTIVE",
        "fast": "FAST",
        "standard": "STANDARD",
        "deep": "DEEP",
    }
    return mapped.get(normalize_reasoning_mode(mode), "ADAPTIVE")


@dataclass(frozen=True)
class EffectiveReasoningMode:
    requested: str
    effective: str
    source: str
    prefer_reasoning_model: bool
    allow_retrieval: bool
    allow_deep_recall: bool
    allow_verification: bool
    allow_agents: bool
    max_generations: int
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "effective": self.effective,
            "source": self.source,
            "prefer_reasoning_model": self.prefer_reasoning_model,
            "allow_retrieval": self.allow_retrieval,
            "allow_deep_recall": self.allow_deep_recall,
            "allow_verification": self.allow_verification,
            "allow_agents": self.allow_agents,
            "max_generations": self.max_generations,
            "notes": list(self.notes),
        }


def resolve_effective_mode(
    *,
    settings_default: str | None,
    session_override: str | None = None,
    plan: ReasoningPlan | None = None,
    message: str = "",
) -> EffectiveReasoningMode:
    """Resolve one effective mode for the turn.

    AUTO chooses from turn properties (deterministic heuristics — no LLM call).
    """
    requested = normalize_reasoning_mode(session_override or settings_default or "auto")
    source = "session" if session_override else "settings"

    if requested != "auto":
        return _materialize(requested, source=source, requested=requested)

    # AUTO heuristics
    intent = (plan.intent if plan else "") or ""
    complexity = (plan.complexity if plan else "") or ""
    text = (message or "").strip()
    lower = text.lower()
    notes: list[str] = []

    simple_intents = {"greeting", "smalltalk", "self_identity", "chitchat", "translate"}
    if intent in simple_intents or complexity in {"trivial", "low", "simple"}:
        notes.append("auto→fast: simple intent/complexity")
        return _materialize("fast", source="auto", requested=requested, notes=tuple(notes))

    if len(text) < 40 and not any(ch in lower for ch in "?:"):
        # Very short without question mark — still may be a command; prefer fast when greeting-like.
        if any(w in lower for w in ("hoi", "hallo", "hi", "hey", "hello", "oke", "ja", "nee")):
            notes.append("auto→fast: short greeting/ack")
            return _materialize("fast", source="auto", requested=requested, notes=tuple(notes))

    deep_markers = (
        "analyseer",
        "analyze",
        "research",
        "onderzoek",
        "vergelijk",
        "compare",
        "architect",
        "debug",
        "prove",
        "waarom precies",
        "step by step",
        "uitgebreid",
        "comprehensive",
        "trade-off",
        "tradeoff",
    )
    if complexity in {"high", "complex", "deep"} or any(m in lower for m in deep_markers):
        notes.append("auto→deep: complexity/markers")
        return _materialize("deep", source="auto", requested=requested, notes=tuple(notes))

    if intent in {"coding", "research", "analysis"} or complexity in {"medium", "moderate"}:
        notes.append("auto→standard: substantive turn")
        return _materialize("standard", source="auto", requested=requested, notes=tuple(notes))

    notes.append("auto→standard: default")
    return _materialize("standard", source="auto", requested=requested, notes=tuple(notes))


def _materialize(
    effective: str,
    *,
    source: str,
    requested: str,
    notes: tuple[str, ...] = (),
) -> EffectiveReasoningMode:
    mode = normalize_reasoning_mode(effective)
    if mode == "fast":
        return EffectiveReasoningMode(
            requested=requested,
            effective="fast",
            source=source,
            prefer_reasoning_model=False,
            allow_retrieval=False,
            allow_deep_recall=False,
            allow_verification=False,
            allow_agents=False,
            max_generations=1,
            notes=notes,
        )
    if mode == "deep":
        return EffectiveReasoningMode(
            requested=requested,
            effective="deep",
            source=source,
            prefer_reasoning_model=True,
            allow_retrieval=True,
            allow_deep_recall=True,
            allow_verification=True,
            allow_agents=True,
            max_generations=3,  # plan + answer + optional revision
            notes=notes,
        )
    # standard
    return EffectiveReasoningMode(
        requested=requested,
        effective="standard",
        source=source,
        prefer_reasoning_model=False,
        allow_retrieval=True,
        allow_deep_recall=True,
        allow_verification=False,
        allow_agents=False,
        max_generations=1,
        notes=notes,
    )


def apply_mode_to_plan(plan: ReasoningPlan, mode: EffectiveReasoningMode) -> ReasoningPlan:
    """Return a plan adjusted for the effective reasoning mode (no mutation)."""
    use_knowledge = bool(plan.use_knowledge) and mode.allow_retrieval
    use_deep = bool(plan.use_deep_recall) and mode.allow_deep_recall and use_knowledge
    use_atlas = bool(plan.use_atlas) and mode.allow_retrieval
    use_memory = bool(getattr(plan, "use_memory", True))
    if mode.effective == "fast":
        use_memory = False
        use_knowledge = False
        use_deep = False
        use_atlas = False
    return ReasoningPlan(
        intent=plan.intent,
        complexity=plan.complexity,
        use_knowledge=use_knowledge,
        steps=plan.steps,
        use_deep_recall=use_deep,
        use_atlas=use_atlas,
        economy=plan.economy,
        retrieval_reason=(
            f"{plan.retrieval_reason}|mode={mode.effective}"
            if plan.retrieval_reason
            else f"mode={mode.effective}"
        ),
        use_memory=use_memory,
        policy_version=plan.policy_version,
    )
