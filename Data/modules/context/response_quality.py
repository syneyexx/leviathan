"""Deterministic response quality / language post-checks for Chat.

Used as a bounded safety net before persisting assistant output.
Does not rewrite factual content with regex — triggers revision when needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from Data.modules.context.advisory import looks_like_diagnostic_leak
from Data.modules.settings.resolver import detect_message_language

_REPEAT_PARA = re.compile(r"(.{80,}?)(?:\n\n|\n)\1", re.DOTALL)
_SYSTEM_LEAK = re.compile(
    r"(?i)(you are levathan'?s hidden|SYSTEM CONTRACT|private chain-of-thought|"
    r"behavior_snapshot|capability_satisfies_request)"
)
_CANNED = re.compile(
    r"(?i)^(a simple question[, ]+indeed!?|it appears that|based on the provided context)\b"
)


@dataclass(frozen=True)
class QualityIssue:
    type: str
    severity: str  # low | medium | high
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {"type": self.type, "severity": self.severity, "detail": self.detail}


@dataclass(frozen=True)
class QualityCheckResult:
    pass_: bool
    issues: tuple[QualityIssue, ...] = ()
    expected_language: str | None = None
    actual_language: str | None = None
    should_revise: bool = False
    revision_instruction: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "pass": self.pass_,
            "issues": [i.public_dict() for i in self.issues],
            "expected_language": self.expected_language,
            "actual_language": self.actual_language,
            "should_revise": self.should_revise,
            "revision_instruction": self.revision_instruction,
        }


_LANG_NAMES = {"en": "English", "nl": "Dutch", "de": "German", "fr": "French", "es": "Spanish"}


def check_response_quality(
    text: str,
    *,
    expected_language: str | None = None,
    finish_reason: str | None = None,
    min_chars: int = 1,
) -> QualityCheckResult:
    issues: list[QualityIssue] = []
    body = (text or "").strip()
    actual_lang: str | None = None

    if len(body) < min_chars:
        issues.append(QualityIssue("empty_answer", "high", "assistant response empty"))

    if looks_like_diagnostic_leak(body):
        issues.append(
            QualityIssue(
                "diagnostic_leakage",
                "high",
                "raw NeuroSignal / advisory diagnostic representation detected",
            )
        )

    if _SYSTEM_LEAK.search(body):
        issues.append(QualityIssue("system_prompt_leakage", "high", "system internals exposed"))

    if _REPEAT_PARA.search(body):
        issues.append(QualityIssue("paragraph_repetition", "medium", "near-duplicate paragraphs"))

    if _CANNED.search(body) and len(body) < 400:
        issues.append(QualityIssue("canned_filler", "low", "generic canned opener"))

    if finish_reason in {"length", "max_tokens", "token_limit"}:
        issues.append(QualityIssue("severe_truncation", "medium", f"finish_reason={finish_reason}"))

    if expected_language and expected_language not in {"auto", "und", ""}:
        detected, reason = detect_message_language(body)
        actual_lang = detected
        # Only flag clear mismatches on non-trivial answers.
        if (
            detected not in {"und", expected_language}
            and reason in {"marker_score", "dutch_pronoun_tiebreak", "english_tiebreak", "explicit_user_request"}
            and len(body) >= 24
        ):
            issues.append(
                QualityIssue(
                    "language_mismatch",
                    "high",
                    f"expected={expected_language} actual={detected}",
                )
            )

    high = [i for i in issues if i.severity == "high"]
    should_revise = bool(high)
    revision = ""
    if should_revise:
        if any(i.type == "language_mismatch" for i in high):
            label = _LANG_NAMES.get(expected_language or "", expected_language or "the user's language")
            revision = (
                f"Rewrite the answer faithfully in {label}. "
                "Do not add new claims. Keep the same meaning and structure."
            )
        elif any(i.type == "diagnostic_leakage" for i in high):
            revision = (
                "Rewrite the answer as natural assistant prose. "
                "Do not include NeuroSignal dumps, advisory tags, provenance maps, "
                "or other internal diagnostic representations."
            )
        elif any(i.type == "empty_answer" for i in high):
            revision = "Provide a direct, natural answer to the user request."
        else:
            revision = "Revise the answer to fix the detected quality issues without adding new claims."

    return QualityCheckResult(
        pass_=not high,
        issues=tuple(issues),
        expected_language=expected_language,
        actual_language=actual_lang,
        should_revise=should_revise,
        revision_instruction=revision,
    )
