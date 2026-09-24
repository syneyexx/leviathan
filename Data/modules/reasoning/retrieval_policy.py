"""Retrieval-need classification — replaces word-count gating.

Greeting / identity / exact-output / casual chat must not activate Brain
merely because the message has eight or more words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


INTENT_GREETING = "greeting"
INTENT_IDENTITY = "identity"
INTENT_EXACT_OUTPUT = "exact_output"
INTENT_CASUAL = "casual_conversation"
INTENT_FORMATTING = "formatting"
INTENT_SETTINGS = "settings_control"
INTENT_FACTUAL = "factual_question"
INTENT_PROJECT = "project_knowledge"
INTENT_RESEARCH = "research"
INTENT_CODING = "coding"
INTENT_ANALYSIS = "analysis"
INTENT_CONVERSATION = "conversation"
INTENT_QUESTION = "question"
INTENT_KNOWLEDGE = "knowledge"

NO_RETRIEVAL_INTENTS = frozenset(
    {
        INTENT_GREETING,
        INTENT_IDENTITY,
        INTENT_EXACT_OUTPUT,
        INTENT_CASUAL,
        INTENT_FORMATTING,
        INTENT_SETTINGS,
    }
)

_GREETING = re.compile(
    r"^\s*(hi|hello|hey|hallo|hoi|goedemorgen|goedemiddag|goedenavond|dag|"
    r"how are you|hoe gaat het|hoe gaat.?s|how.?s it going)"
    r"[\s\!\?\.,]*$",
    re.IGNORECASE,
)
_IDENTITY = re.compile(
    r"\b("
    r"what(?:'?s| is) your name|who are you|what are you|"
    r"wat is (jouw|je|jou) naam|wie ben jij|wie ben je|hoe heet je|"
    r"your name|jouw naam|jou naam"
    r")\b",
    re.IGNORECASE,
)
_EXACT_OUTPUT = re.compile(
    r"(?i)("
    r"antwoord\s+alleen\s+met|"
    r"antwoord\s+exact\s+met|"
    r"reply\s+exactly\s+with|"
    r"answer\s+exactly\s+with|"
    r"only\s+output|"
    r"output\s+only|"
    r"respond\s+only\s+with|"
    r"antwoord\s+enkel\s+met"
    r")"
)
_SETTINGS = re.compile(
    r"(?i)\b(settings|instellingen|change (?:your|the) (?:name|prompt|language)|"
    r"pas (?:je|jouw) (?:naam|taal|prompt) aan)\b"
)
_FORMATTING = re.compile(
    r"(?i)\b(format|herformat|reformat|uppercase|lowercase|translate this|"
    r"vertaal dit|samenvat|summarize this)\b"
)
_CODING = re.compile(
    r"(?i)\b(code|python|javascript|typescript|c\+\+|bug|debug|repo|"
    r"repository|function|class|api|database|sql|refactor)\b"
)
_RESEARCH = re.compile(
    r"(?i)\b(research|onderzoek|analyseer|analyze|compare|vergelijk|"
    r"latest|recent|bron|source|evidence)\b"
)
_KNOWLEDGE = re.compile(
    r"(?i)\b(knowledge|kennis|remember|memory|project|leviathan|"
    r"hades|document|atlas|recall|in (?:my|the) (?:brain|notes|docs))\b"
)
_FACTUAL_Q = re.compile(
    r"(?i)^\s*(what|who|when|where|why|how|wat|wie|wanneer|waar|waarom|hoe)\b.+\?"
)


@dataclass(frozen=True)
class RetrievalDecision:
    intent: str
    use_knowledge: bool
    use_memory: bool
    use_deep_recall: bool
    use_atlas: bool
    reason: str
    complexity: str
    steps: tuple[str, ...]
    policy_version: str = "retrieval_policy.v1"

    def public_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "use_knowledge": self.use_knowledge,
            "use_memory": self.use_memory,
            "use_deep_recall": self.use_deep_recall,
            "use_atlas": self.use_atlas,
            "reason": self.reason,
            "complexity": self.complexity,
            "steps": list(self.steps),
            "policy_version": self.policy_version,
        }


def classify_intent(message: str) -> tuple[str, str]:
    """Return (intent, reason)."""
    text = (message or "").strip()
    if not text:
        return INTENT_CASUAL, "empty"
    if _EXACT_OUTPUT.search(text):
        return INTENT_EXACT_OUTPUT, "exact_output_pattern"
    if _GREETING.match(text) or (
        len(text.split()) <= 12
        and re.search(r"(?i)\b(hoe gaat het|how are you|hallo|hello|hi)\b", text)
        and not re.search(r"(?i)\b(because|want|onderzoek|research|document)\b", text)
    ):
        # Combined greeting + identity still identity/greeting, not retrieval.
        if _IDENTITY.search(text):
            return INTENT_IDENTITY, "identity_with_greeting"
        return INTENT_GREETING, "greeting_pattern"
    if _IDENTITY.search(text):
        return INTENT_IDENTITY, "identity_pattern"
    if _SETTINGS.search(text) and len(text.split()) < 40:
        return INTENT_SETTINGS, "settings_control"
    if _FORMATTING.search(text) and len(text) < 2000:
        return INTENT_FORMATTING, "formatting_transform"
    if _CODING.search(text):
        return INTENT_CODING, "coding_terms"
    if _RESEARCH.search(text):
        return INTENT_RESEARCH, "research_terms"
    if _KNOWLEDGE.search(text):
        return INTENT_PROJECT, "project_knowledge_terms"
    if text.endswith("?") or _FACTUAL_Q.search(text):
        # Short social questions stay casual/identity, not factual.
        if _IDENTITY.search(text) or re.search(r"(?i)\b(hoe gaat het|how are you)\b", text):
            return INTENT_CASUAL, "social_question"
        return INTENT_FACTUAL, "factual_question"
    # Long casual chitchat without knowledge/research markers
    word_count = len(text.split())
    if word_count >= 8 and not (_CODING.search(text) or _RESEARCH.search(text) or _KNOWLEDGE.search(text)):
        # Still casual unless clearly asking for facts / project data.
        if re.search(r"(?i)\b(vertel|tell me about|what do you know|wat weet je)\b", text):
            return INTENT_FACTUAL, "tell_me_about"
        return INTENT_CASUAL, "long_chitchat"
    return INTENT_CONVERSATION, "default_conversation"


def decide_retrieval(
    message: str,
    *,
    has_knowledge: bool,
    retrieval_enabled: bool = True,
    retrieval_mode: str = "auto",
    deep_recall_enabled: bool = False,
    economy_allow_deep_recall: bool = False,
    memory_enabled: bool = True,
    memory_coverage: float = 1.0,
) -> RetrievalDecision:
    intent, reason = classify_intent(message)
    word_count = len((message or "").split())
    complexity = "high" if word_count > 120 else "medium" if word_count > 35 else "low"

    mode = (retrieval_mode or "auto").strip().lower()
    if not retrieval_enabled or mode == "forced_off":
        use_knowledge = False
        gate_reason = "retrieval_forced_off" if mode == "forced_off" else "retrieval_disabled"
    elif mode == "forced_on":
        use_knowledge = bool(has_knowledge)
        gate_reason = "retrieval_forced_on"
    elif intent in NO_RETRIEVAL_INTENTS:
        use_knowledge = False
        gate_reason = f"no_retrieval_intent:{intent}:{reason}"
    else:
        use_knowledge = bool(has_knowledge) and intent in {
            INTENT_FACTUAL,
            INTENT_PROJECT,
            INTENT_RESEARCH,
            INTENT_CODING,
            INTENT_ANALYSIS,
            INTENT_KNOWLEDGE,
            INTENT_QUESTION,
        }
        gate_reason = f"eligible:{intent}" if use_knowledge else f"not_eligible:{intent}:{reason}"

    use_memory = bool(memory_enabled) and intent not in {
        INTENT_EXACT_OUTPUT,
        INTENT_GREETING,
        INTENT_FORMATTING,
    }
    if intent == INTENT_EXACT_OUTPUT:
        use_memory = False

    use_atlas = use_knowledge and intent in {
        INTENT_PROJECT,
        INTENT_RESEARCH,
        INTENT_FACTUAL,
        INTENT_KNOWLEDGE,
        INTENT_ANALYSIS,
        INTENT_QUESTION,
    }
    wants_precision = bool(
        re.search(r"(?i)\b(exactly|exact|detail|cite|citation|quote|precise|deep recall|hydrate)\b", message or "")
    )
    use_deep_recall = bool(
        deep_recall_enabled
        and use_knowledge
        and (
            economy_allow_deep_recall
            or wants_precision
            or (memory_coverage < 0.35 and complexity in {"medium", "high"})
        )
    )

    steps: list[str] = ["understand_request"]
    if use_atlas and not use_deep_recall:
        steps.append("retrieve_atlas_context")
    if use_deep_recall:
        steps.append("deep_recall_hydrate")
    elif use_knowledge:
        steps.append("retrieve_relevant_knowledge")
    if complexity in {"medium", "high"} and intent != INTENT_EXACT_OUTPUT:
        steps.append("structure_response")
    steps.append("generate_answer")

    return RetrievalDecision(
        intent=intent,
        use_knowledge=use_knowledge,
        use_memory=use_memory,
        use_deep_recall=use_deep_recall,
        use_atlas=use_atlas,
        reason=gate_reason,
        complexity=complexity,
        steps=tuple(steps),
    )
