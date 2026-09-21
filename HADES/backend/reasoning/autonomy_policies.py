"""Autonomy / write / reflection policies for Gen2 monster C1–C15 characterization.

Deterministic gates only — never decide permissions via model prompts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


# C1 — structured pipeline stages (understand → … → optional memory/knowledge)
PIPELINE_STAGES: tuple[str, ...] = (
    "understand",
    "retrieve",
    "plan",
    "execute",
    "verify",
    "answer",
    "memory_update",
)


def pipeline_stage_index(stage: str) -> int:
    key = str(stage or "").strip().lower()
    if key not in PIPELINE_STAGES:
        raise ValueError(f"unknown_pipeline_stage:{stage}")
    return PIPELINE_STAGES.index(key)


def validate_pipeline_progress(completed: list[str]) -> dict[str, Any]:
    """Ensure completed stages are a prefix of PIPELINE_STAGES (no skipping ahead)."""
    indices: list[int] = []
    for stage in completed:
        indices.append(pipeline_stage_index(stage))
    ok = indices == list(range(len(indices)))
    return {
        "ok": ok,
        "completed": list(completed),
        "expected_prefix": list(PIPELINE_STAGES[: len(completed)]) if ok else list(PIPELINE_STAGES[: max(indices) + 1] if indices else []),
        "pipeline": list(PIPELINE_STAGES),
        "note": "ordered_prefix" if ok else "out_of_order_or_skip",
    }


ReflectionAction = Literal["continue", "escape_to_human", "stop"]


@dataclass(slots=True)
class ReflectionDecision:
    action: ReflectionAction
    reason: str
    replans: int
    max_replans: int | None
    repair_attempts: int
    max_repair_attempts: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reflection_gate(
    *,
    replans: int = 0,
    max_replans: int | None = 0,
    repair_attempts: int = 0,
    max_repair_attempts: int | None = 2,
) -> ReflectionDecision:
    """C12 — hard caps on self-reflection; escape to human when exhausted."""
    if max_replans is not None and int(replans) > int(max_replans):
        return ReflectionDecision(
            action="escape_to_human",
            reason=f"max_replans_exceeded:{replans}>{max_replans}",
            replans=int(replans),
            max_replans=max_replans,
            repair_attempts=int(repair_attempts),
            max_repair_attempts=max_repair_attempts,
        )
    if max_replans is not None and int(replans) >= int(max_replans) and int(replans) > 0:
        # At cap after a failed cycle — do not start another silent replan.
        if max_repair_attempts is not None and int(repair_attempts) >= int(max_repair_attempts):
            return ReflectionDecision(
                action="escape_to_human",
                reason="reflection_and_repair_exhausted",
                replans=int(replans),
                max_replans=max_replans,
                repair_attempts=int(repair_attempts),
                max_repair_attempts=max_repair_attempts,
            )
    if max_repair_attempts is not None and int(repair_attempts) > int(max_repair_attempts):
        return ReflectionDecision(
            action="stop",
            reason=f"max_repair_attempts_exceeded:{repair_attempts}>{max_repair_attempts}",
            replans=int(replans),
            max_replans=max_replans,
            repair_attempts=int(repair_attempts),
            max_repair_attempts=max_repair_attempts,
        )
    if max_replans is not None and int(replans) >= int(max_replans) and int(max_replans) == 0 and int(repair_attempts) == 0:
        # Profile forbids replan; first failure → ask human rather than loop.
        return ReflectionDecision(
            action="continue",
            reason="no_replan_budget_first_pass",
            replans=int(replans),
            max_replans=max_replans,
            repair_attempts=int(repair_attempts),
            max_repair_attempts=max_repair_attempts,
        )
    return ReflectionDecision(
        action="continue",
        reason="within_caps",
        replans=int(replans),
        max_replans=max_replans,
        repair_attempts=int(repair_attempts),
        max_repair_attempts=max_repair_attempts,
    )


def should_escape_to_human_after_failure(
    *,
    replans: int,
    max_replans: int | None,
    repair_attempts: int = 0,
    max_repair_attempts: int | None = 2,
) -> bool:
    decision = reflection_gate(
        replans=replans,
        max_replans=max_replans,
        repair_attempts=repair_attempts,
        max_repair_attempts=max_repair_attempts,
    )
    if decision.action == "escape_to_human":
        return True
    if max_replans is not None and int(replans) >= int(max_replans):
        return True
    return False


StopAskAction = Literal["proceed", "stop_and_ask"]


@dataclass(slots=True)
class StopAndAskDecision:
    action: StopAskAction
    reason: str
    ambiguity: str
    risk_level: str
    questions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stop_and_ask_gate(
    *,
    ambiguity: str = "low",
    risk_level: str = "low",
    conflicting_constraints: bool = False,
    missing_required_inputs: list[str] | None = None,
) -> StopAndAskDecision:
    """C13 — when uncertain, do not steamroll; surface clarifying questions."""
    missing = [str(x) for x in (missing_required_inputs or []) if str(x).strip()]
    questions: list[str] = []
    if missing:
        questions.append(f"Bevestig ontbrekende invoer: {', '.join(missing[:6])}")
    if conflicting_constraints:
        questions.append("Welke constraint heeft voorrang bij conflict?")
    if ambiguity == "high":
        questions.append("Welke interpretatie bedoel je precies?")
    if risk_level == "high" and ambiguity in {"medium", "high"}:
        questions.append("Mag ik doorgaan met side effects, of eerst een plan ter review?")

    if missing or conflicting_constraints or (ambiguity == "high" and risk_level != "low"):
        return StopAndAskDecision(
            action="stop_and_ask",
            reason="uncertainty_or_missing_inputs",
            ambiguity=str(ambiguity),
            risk_level=str(risk_level),
            questions=questions or ["Kun je de opdracht aanscherpen?"],
        )
    if ambiguity == "high":
        return StopAndAskDecision(
            action="stop_and_ask",
            reason="high_ambiguity",
            ambiguity=ambiguity,
            risk_level=str(risk_level),
            questions=questions or ["Welke optie kies je?"],
        )
    return StopAndAskDecision(
        action="proceed",
        reason="clear_enough",
        ambiguity=str(ambiguity),
        risk_level=str(risk_level),
        questions=[],
    )


MemoryWriteAction = Literal["deny", "propose", "persist"]


@dataclass(slots=True)
class MemoryWriteDecision:
    action: MemoryWriteAction
    reason: str
    confidence: float
    provenance: str
    origin_kind: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_memory_write(
    *,
    mode: str = "project",
    explicit_remember: bool = False,
    auto_promote: bool = False,
    origin_kind: str = "model_inference",
    memory_write_enabled: bool = True,
    has_project_markers: bool = False,
) -> MemoryWriteDecision:
    """C14 — what may persist, with confidence + provenance (not model-granted)."""
    if not memory_write_enabled or mode == "off":
        return MemoryWriteDecision(
            action="deny",
            reason="memory_write_disabled",
            confidence=0.0,
            provenance="policy:memory.write_enabled|auto_memory_mode=off",
            origin_kind=origin_kind,
        )
    if mode == "project" and not explicit_remember and not has_project_markers:
        return MemoryWriteDecision(
            action="deny",
            reason="no_project_markers",
            confidence=0.0,
            provenance="policy:auto_memory_mode=project",
            origin_kind=origin_kind,
        )
    if explicit_remember:
        return MemoryWriteDecision(
            action="persist",
            reason="explicit_user_remember",
            confidence=0.95,
            provenance="user:explicit_remember",
            origin_kind="user_fact",
        )
    if auto_promote:
        return MemoryWriteDecision(
            action="persist",
            reason="auto_promote_enabled",
            confidence=0.55,
            provenance="policy:memory_auto_promote",
            origin_kind=origin_kind or "model_inference",
        )
    return MemoryWriteDecision(
        action="propose",
        reason="model_inference_requires_review",
        confidence=0.45,
        provenance="policy:proposal_gate",
        origin_kind=origin_kind or "model_inference",
    )


KnowledgeWriteAction = Literal["deny", "allow"]


@dataclass(slots=True)
class KnowledgeWriteDecision:
    action: KnowledgeWriteAction
    reason: str
    verified: bool
    user_or_policy_allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_knowledge_write_back(
    *,
    verified: bool = False,
    user_allowed: bool = False,
    policy_allow: bool = False,
    write_enabled: bool = True,
) -> KnowledgeWriteDecision:
    """C15 — Knowledge write-back only after verification + user/policy allow."""
    if not write_enabled:
        return KnowledgeWriteDecision(
            action="deny",
            reason="knowledge_write_disabled",
            verified=bool(verified),
            user_or_policy_allowed=False,
        )
    allowed = bool(user_allowed or policy_allow)
    if not verified:
        return KnowledgeWriteDecision(
            action="deny",
            reason="unverified",
            verified=False,
            user_or_policy_allowed=allowed,
        )
    if not allowed:
        return KnowledgeWriteDecision(
            action="deny",
            reason="awaiting_user_or_policy_allow",
            verified=True,
            user_or_policy_allowed=False,
        )
    return KnowledgeWriteDecision(
        action="allow",
        reason="verified_and_allowed",
        verified=True,
        user_or_policy_allowed=True,
    )
