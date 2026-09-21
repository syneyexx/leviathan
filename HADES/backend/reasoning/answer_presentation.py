"""Answer presentation helpers — style only; never substitutes for verification."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


VerificationDisplay = Literal[
    "not_checked",
    "provisional",
    "unverified",
    "partial",
    "verified",
    "factual_verified",
    "contradicted",
]


@dataclass(slots=True)
class AnswerPresentation:
    content: str
    verification_display: VerificationDisplay
    material_correction: bool = False
    uncertainty_notes: list[str] = field(default_factory=list)
    pipeline_jargon_stripped: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PIPELINE_METADATA_LINE = re.compile(
    r"^\s*(?:[-*]\s*)?[\"']?(?:criteria_checklist|evidence_refs|parse_status|route_decision|"
    r"compiler_pack|acceptance_hints|speech_act|model_calls_expected)[\"']?\s*[:=].*$",
    flags=re.I | re.M,
)


def map_verification_display(
    *,
    verification_called: bool,
    allowed: bool | None,
    factual_label: str | None = None,
    provisional: bool = False,
) -> VerificationDisplay:
    """Internal draft vs verification status — never show verified before checks."""
    if provisional:
        return "provisional"
    if not verification_called:
        return "not_checked"
    if factual_label == "factual_verified":
        return "factual_verified"
    if factual_label == "contradicted":
        return "contradicted"
    if allowed is True:
        return "verified"
    if allowed is False:
        return "unverified"
    return "partial"


def strip_pipeline_jargon(text: str) -> tuple[str, bool]:
    """Remove standalone internal metadata rows without altering technical prose.

    HADES users may legitimately discuss identifiers such as ``evidence_refs`` or
    ``speech_act``. Presentation is a style layer, so deleting those words from
    ordinary sentences would change meaning. Only rows that look like leaked
    internal key/value metadata are stripped.
    """
    if not text:
        return text, False
    cleaned, count = _PIPELINE_METADATA_LINE.subn("", text)
    if count == 0:
        return text, False
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, True


def qualify_unchecked_claims(text: str, *, verification_display: VerificationDisplay) -> list[str]:
    notes: list[str] = []
    if verification_display in {"not_checked", "provisional", "unverified"}:
        if re.search(r"\b(zeker|definitely|always|always true|100%)\b", text, flags=re.I):
            notes.append("Sterke zekerheid zonder uitgevoerde controle — behandel als ongeverifieerd")
    return notes


def prefer_direct_answer(text: str, *, speech_act: str, asked_output: str) -> str:
    """Light touch: avoid forcing a universal heading template on every reply."""
    _ = asked_output
    stripped = (text or "").strip()
    if not stripped:
        return stripped
    # Do not inject boilerplate sections for simple Q&A.
    if speech_act in {"question", "explain", "inform"} and stripped.startswith("## "):
        # Leave as-is — model may have used headings intentionally for complex asks.
        return stripped
    return stripped


def present_answer(
    draft: str,
    *,
    verification_called: bool = False,
    allowed: bool | None = None,
    factual_label: str | None = None,
    provisional: bool = False,
    speech_act: str = "inform",
    asked_output: str = "answer",
    material_correction: bool = False,
) -> AnswerPresentation:
    display = map_verification_display(
        verification_called=verification_called,
        allowed=allowed,
        factual_label=factual_label,
        provisional=provisional,
    )
    content = prefer_direct_answer(draft, speech_act=speech_act, asked_output=asked_output)
    content, stripped = strip_pipeline_jargon(content)
    uncertainty = qualify_unchecked_claims(content, verification_display=display)
    notes: list[str] = []
    if display == "not_checked":
        notes.append("Geen feitenverificatie uitgevoerd")
    if display == "provisional":
        notes.append("Conceptstatus — nog niet geverifieerd")
    if material_correction:
        notes.append("Materiële correctie t.o.v. eerdere concepttekst")
    return AnswerPresentation(
        content=content,
        verification_display=display,
        material_correction=material_correction,
        uncertainty_notes=uncertainty,
        pipeline_jargon_stripped=stripped,
        notes=notes,
    )
