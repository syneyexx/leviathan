"""Canonical TEAM task profile — adapts existing intent classification for TEAM.

Does not create a second competing intent system. Reuses ``classify_intent``
from reasoning.retrieval_policy and TaskModelBuilder signals where useful.
TEAM collaboration remains TEAM; this only chooses contracts/roles/intensity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from Data.modules.reasoning.retrieval_policy import (
    INTENT_CASUAL,
    INTENT_CODING,
    INTENT_CONVERSATION,
    INTENT_EXACT_OUTPUT,
    INTENT_FACTUAL,
    INTENT_FORMATTING,
    INTENT_GREETING,
    INTENT_IDENTITY,
    INTENT_PROJECT,
    INTENT_RESEARCH,
    INTENT_SETTINGS,
    classify_intent,
)

# Lightweight / conversational TEAM categories — no external evidence by default.
LIGHTWEIGHT_CATEGORIES = frozenset(
    {
        "conversational",
        "self_description",
        "system_meta",
        "general_advice",
    }
)

# Strict evidence categories retain research/coding/calc gates.
STRICT_CATEGORIES = frozenset(
    {
        "factual",
        "research",
        "coding",
        "repair",
        "quantitative",
        "high_assurance",
        "tool_task",
    }
)

_CAPABILITY_SELF = re.compile(
    r"(?i)\b("
    r"what can you(?:\s+all)?(?:\s+do)?|"
    r"wat kan(?:nen)? (?:je|jij|u)(?:\s+allemaal)?|"
    r"wat kun(?:nen)? (?:je|jij|u)|"
    r"your capabilities|jouw mogelijkheden|"
    r"tell me about yourself|vertel (?:eens )?over jezelf|"
    r"what are you (?:able|good) at|waar ben je goed in"
    r")\b"
)

_CALC = re.compile(
    r"(?i)("
    r"\b\d+([.,]\d+)?\s*%\s*(van|of)\b|"
    r"\b(bereken|calculate|compute|percentage van|som van|sqrt)\b|"
    r"\b\d+\s*[\+\-\*/×÷]\s*\d+\b"
    r")"
)

_CURRENT_FACT = re.compile(
    r"(?i)\b("
    r"huidige|current|live|latest|newest|nieuwste|prijs|price|"
    r"today|vandaag|right now|op dit moment"
    r")\b"
)

_CODING = re.compile(
    r"(?i)\b("
    r"fix|bug|test|pytest|implement|refactor|code|function|class|"
    r"bewijs met tests|prove with tests|unit test"
    r")\b"
)

_RESEARCH = re.compile(
    r"(?i)\b("
    r"research|onderzoek|sources|cite|evidence|investigate|"
    r"kwartaalresultaten|earnings|vergelijk|compare"
    r")\b"
)


@dataclass(frozen=True)
class TeamTaskProfile:
    """Narrow TEAM adapter over canonical intent classification."""

    category: str
    answer_kind: str
    requires_external_research: bool = False
    requires_tools: bool = False
    requires_code_execution: bool = False
    requires_calculation: bool = False
    requires_artifact: bool = True
    material_factual_claims_expected: bool = False
    runtime_state_claims_expected: bool = False
    verification_intensity: str = "standard"
    intent: str = "conversation"
    intent_reason: str = ""
    lightweight: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "answer_kind": self.answer_kind,
            "requires_external_research": self.requires_external_research,
            "requires_tools": self.requires_tools,
            "requires_code_execution": self.requires_code_execution,
            "requires_calculation": self.requires_calculation,
            "requires_artifact": self.requires_artifact,
            "material_factual_claims_expected": self.material_factual_claims_expected,
            "runtime_state_claims_expected": self.runtime_state_claims_expected,
            "verification_intensity": self.verification_intensity,
            "intent": self.intent,
            "intent_reason": self.intent_reason,
            "lightweight": self.lightweight,
            "truth": {
                "profile_does_not_satisfy_criteria": True,
                "team_remains_team_for_explicit_collaboration": True,
                "reasoning_depth_is_orthogonal": True,
            },
        }


def build_team_task_profile(request_text: str) -> TeamTaskProfile:
    """Build a TEAM task profile from the user request.

    Uses the existing retrieval-policy intent classifier as the primary owner.
    Conservative on uncertainty: ambiguous factual/current requests stay strict.
    """
    text = (request_text or "").strip()
    intent, reason = classify_intent(text)
    lowered = text.lower()

    requires_calc = bool(_CALC.search(text))
    requires_coding = bool(_CODING.search(text)) or intent == INTENT_CODING
    requires_research = bool(_RESEARCH.search(text)) or intent == INTENT_RESEARCH
    requires_current = bool(_CURRENT_FACT.search(text)) and (
        intent in {INTENT_FACTUAL, INTENT_RESEARCH, INTENT_PROJECT, INTENT_CONVERSATION}
        or "?" in text
    )
    capability_q = bool(_CAPABILITY_SELF.search(text))
    identity_q = intent == INTENT_IDENTITY or capability_q

    # --- Strict paths first ---
    if requires_coding:
        cat = "repair" if any(t in lowered for t in ("fix", "bug", "broken")) else "coding"
        return TeamTaskProfile(
            category=cat,
            answer_kind="code_fix",
            requires_code_execution=True,
            requires_tools=True,
            requires_artifact=True,
            material_factual_claims_expected=False,
            verification_intensity="strict",
            intent=intent,
            intent_reason=reason,
            lightweight=False,
        )

    if requires_calc and not requires_research:
        return TeamTaskProfile(
            category="quantitative",
            answer_kind="calculation",
            requires_calculation=True,
            requires_tools=True,
            requires_artifact=True,
            material_factual_claims_expected=True,
            verification_intensity="strict",
            intent=intent,
            intent_reason=reason,
            lightweight=False,
        )

    if requires_research or (requires_current and intent in {INTENT_FACTUAL, INTENT_RESEARCH}):
        return TeamTaskProfile(
            category="research" if requires_research else "factual",
            answer_kind="research_report" if requires_research else "factual_answer",
            requires_external_research=True,
            requires_tools=True,
            requires_artifact=True,
            material_factual_claims_expected=True,
            verification_intensity="strict",
            intent=intent,
            intent_reason=reason,
            lightweight=False,
        )

    if intent == INTENT_FACTUAL and requires_current:
        return TeamTaskProfile(
            category="factual",
            answer_kind="factual_answer",
            requires_external_research=True,
            requires_tools=True,
            material_factual_claims_expected=True,
            verification_intensity="strict",
            intent=intent,
            intent_reason=reason,
            lightweight=False,
        )

    # --- Lightweight conversational / self-description ---
    if identity_q or capability_q:
        return TeamTaskProfile(
            category="self_description",
            answer_kind="identity_or_capabilities",
            requires_artifact=True,
            material_factual_claims_expected=False,
            runtime_state_claims_expected=capability_q,
            verification_intensity="light",
            intent=intent if intent != INTENT_CONVERSATION else INTENT_IDENTITY,
            intent_reason=reason if not capability_q else "capability_self_description",
            lightweight=True,
        )

    if intent in {
        INTENT_GREETING,
        INTENT_CASUAL,
        INTENT_EXACT_OUTPUT,
        INTENT_FORMATTING,
        INTENT_SETTINGS,
    }:
        return TeamTaskProfile(
            category="conversational",
            answer_kind="prose_reply",
            requires_artifact=True,
            verification_intensity="light",
            intent=intent,
            intent_reason=reason,
            lightweight=True,
        )

    if intent == INTENT_CONVERSATION and not requires_current:
        # Short general / explanatory chat without research markers.
        return TeamTaskProfile(
            category="general_advice" if len(text.split()) > 6 else "conversational",
            answer_kind="prose_reply",
            requires_artifact=True,
            verification_intensity="light",
            intent=intent,
            intent_reason=reason,
            lightweight=True,
        )

    if intent == INTENT_FACTUAL and not requires_current and not requires_research:
        # General explanation / static knowledge — no web citation gate by default.
        return TeamTaskProfile(
            category="general_advice",
            answer_kind="explanation",
            requires_artifact=True,
            material_factual_claims_expected=False,
            verification_intensity="standard",
            intent=intent,
            intent_reason=reason,
            lightweight=True,
        )

    # Conservative default: general TEAM contract (deliverable + synthesis).
    return TeamTaskProfile(
        category="general",
        answer_kind="prose_reply",
        requires_artifact=True,
        verification_intensity="standard",
        intent=intent,
        intent_reason=reason,
        lightweight=False,
    )
