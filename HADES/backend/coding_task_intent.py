"""Deterministic Coding task-intent classifier.

Public API may still expose coarse task_type values (bugfix/feature/regression/review).
Internal intent distinguishes whether source mutation is required.

CRITICAL RULE: explicit mutation intent wins over investigation language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

CoarseTaskType = Literal["bugfix", "feature", "regression", "review"]
IntentKind = Literal[
    "review_report_only",
    "regression_investigation_only",
    "bugfix",
    "feature",
    "refactor",
    "tests",
    "documentation",
    "ui_style",
    "configuration_build",
]

# Explicit mutation verbs/phrases (EN + NL) — presence forces mutation unless
# an equally explicit "do not modify" / "report only" constraint wins.
_MUTATION_PATTERNS = [
    r"\bfix\b",
    r"\brepair\b",
    r"\brepareer\b",
    r"\bherstel\b",
    r"\bimplement(?:eer|eert|eren|ation|ing)?\b",
    r"\bcreate\b",
    r"\bmaak\b",
    r"\bbouw\b",
    r"\bbuild\b",
    r"\badd\b",
    r"\bvoeg\b",
    r"\btoevoegen\b",
    r"\brefactor\b",
    r"\bherschrijf\b",
    r"\bupdate\b",
    r"\bwijzig\b",
    r"\bchange\b",
    r"\bmodify\b",
    r"\bpatch\b",
    r"\bwrite\b",
    r"\bschrijf\b",
    r"\bintroduce\b",
    r"\benable\b",
    r"\bdisable\b",
    r"\bmigrate\b",
    r"\brenamed?\b",
    r"\bdelete\b",
    r"\bverwijder\b",
    r"\bfix\s+het\b",
    r"\brepareer\s+het\b",
    r"\band\s+fix\b",
    r"\ben\s+(?:fix|repareer|herstel|implementeer)\b",
    r"\bimplementeer\s+de\s+oplossing\b",
    r"\bvoeg\s+tests?\s+toe\b",
    r"\badd\s+tests?\b",
]

# Explicit report-only / no-mutation constraints.
_REPORT_ONLY_PATTERNS = [
    r"\bdo\s+not\s+modify\b",
    r"\bdon'?t\s+modify\b",
    r"\bdo\s+not\s+change\b",
    r"\bdon'?t\s+change\b",
    r"\bno\s+code\s+changes?\b",
    r"\bwithout\s+(?:changing|modifying|editing)\b",
    r"\breport\s+only\b",
    r"\banalys(?:e|is|e)\s+only\b",
    r"\banalyze\s+only\b",
    r"\balleen\s+analyseren\b",
    r"\balleen\s+review\b",
    r"\bniet\s+wijzigen\b",
    r"\bgeen\s+wijzigingen?\b",
    r"\bdo\s+not\s+edit\b",
    r"\bread[\s-]?only\b",
    r"\breview\s+this\s+code\s+only\b",
    r"\broot[\s-]?cause\s+report\s+only\b",
    r"\bgive\s+me\s+a\s+root[\s-]?cause\s+report\s+only\b",
]

_REVIEW_PATTERNS = [
    r"\breview\b",
    r"\bbeoordeel\b",
    r"\bcode\s+review\b",
    r"\bfindings\b",
    r"\baudit\b",
]

_REGRESSION_INVESTIGATE_PATTERNS = [
    r"\bregression\b",
    r"\bdiagnose\b",
    r"\broot\s+cause\b",
    r"\bonderzoek\b",
    r"\banalyse(?:er|ren)?\b",
    r"\banaly[sz]e\b",
    r"\binvestigat(?:e|ion)\b",
    r"\bwaarom\b",
    r"\bwhy\b",
]

_FEATURE_PATTERNS = [
    r"\bfeature\b",
    r"\bimplement(?:eer|eren|ation)?\b",
    r"\badd\b",
    r"\bvoeg\b",
    r"\bmaak\b",
    r"\bbouw\b",
    r"\bbuild\b",
    r"\bcreate\b",
    r"\bnieuwe?\b",
    r"\bnew\b",
    r"\bendpoint\b",
    r"\bcomponent\b",
    r"\bsupport\s+--",
]

_REFACTOR_PATTERNS = [
    r"\brefactor\b",
    r"\bclean\s*up\b",
    r"\bherschrijf\b",
    r"\brestructure\b",
    r"\bextract\b",
]

_TESTS_PATTERNS = [
    r"\badd\s+tests?\b",
    r"\bvoeg\s+tests?\s+toe\b",
    r"\bunit\s*tests?\b",
    r"\bcoverage\b",
    r"\bschrijf\s+tests?\b",
    r"\bwrite\s+tests?\b",
]

_DOCS_PATTERNS = [
    r"\bdocumentation\b",
    r"\bdocs?\b",
    r"\breadme\b",
    r"\bdocstring\b",
    r"\bcommentaar\b",
]

_UI_PATTERNS = [
    r"\bcss\b",
    r"\bstyl(?:e|ing)\b",
    r"\blayout\b",
    r"\bui\b",
    r"\bux\b",
    r"\bscss\b",
    r"\bcomponent\b",
    r"\btsx\b",
    r"\breact\b",
]

_CONFIG_PATTERNS = [
    r"\bconfig(?:uration)?\b",
    r"\bbuild\s+(?:script|config|system)\b",
    r"\bci\b",
    r"\bdocker(?:file)?\b",
    r"\bmakefile\b",
    r"\bpackage\.json\b",
    r"\btsconfig\b",
    r"\bwebpack\b",
    r"\bvite\b",
    r"\bgradle\b",
    r"\bcargo\b",
]


def _any_match(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


@dataclass(slots=True)
class CodingTaskIntent:
    kind: IntentKind
    coarse_task_type: CoarseTaskType
    requires_mutation: bool
    report_only: bool
    reasons: list[str] = field(default_factory=list)
    mutation_signals: list[str] = field(default_factory=list)
    report_only_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "coarse_task_type": self.coarse_task_type,
            "task_type": self.coarse_task_type,  # API compatibility
            "requires_mutation": self.requires_mutation,
            "report_only": self.report_only,
            "reasons": list(self.reasons),
            "mutation_signals": list(self.mutation_signals),
            "report_only_signals": list(self.report_only_signals),
        }


def _matched_patterns(patterns: list[str], text: str) -> list[str]:
    out: list[str] = []
    for pat in patterns:
        if re.search(pat, text, re.I):
            out.append(pat)
    return out


def classify_coding_task_intent(
    goal: str,
    *,
    explicit_task_type: str | None = None,
    autonomy_profile: str | None = None,
) -> CodingTaskIntent:
    """Classify goal into internal intent + coarse public task_type."""
    text = (goal or "").strip()
    lowered = text.lower()
    reasons: list[str] = []

    mutation_hits = _matched_patterns(_MUTATION_PATTERNS, lowered)
    report_hits = _matched_patterns(_REPORT_ONLY_PATTERNS, lowered)
    autonomy = (autonomy_profile or "").strip().lower()

    # analyze_only autonomy forces report-only regardless of goal wording.
    if autonomy == "analyze_only":
        reasons.append("autonomy_analyze_only")
        return CodingTaskIntent(
            kind="review_report_only",
            coarse_task_type="review",
            requires_mutation=False,
            report_only=True,
            reasons=reasons,
            mutation_signals=mutation_hits,
            report_only_signals=report_hits + ["autonomy_analyze_only"],
        )

    # Explicit report-only constraints win when present without conflicting mutation
    # that is stronger — but "do not modify" always wins over investigation+fix.
    if report_hits and not mutation_hits:
        reasons.append("explicit_report_only")
        kind: IntentKind = "review_report_only"
        if _any_match(_REGRESSION_INVESTIGATE_PATTERNS, lowered):
            kind = "regression_investigation_only"
        return CodingTaskIntent(
            kind=kind,
            coarse_task_type="review" if kind == "review_report_only" else "regression",
            requires_mutation=False,
            report_only=True,
            reasons=reasons,
            mutation_signals=mutation_hits,
            report_only_signals=report_hits,
        )

    if report_hits and mutation_hits:
        # "Review and fix" → mutation. "Review; do not modify" → report-only.
        # Explicit no-modify phrases always win.
        hard_block = any(
            re.search(p, lowered, re.I)
            for p in (
                r"\bdo\s+not\s+modify\b",
                r"\bdon'?t\s+modify\b",
                r"\bniet\s+wijzigen\b",
                r"\bgeen\s+wijzigingen?\b",
                r"\breport\s+only\b",
                r"\banalys(?:e|is|e)\s+only\b",
                r"\banalyze\s+only\b",
                r"\balleen\s+analyseren\b",
            )
        )
        if hard_block:
            reasons.append("explicit_no_modify_overrides_mutation_words")
            return CodingTaskIntent(
                kind="review_report_only",
                coarse_task_type="review",
                requires_mutation=False,
                report_only=True,
                reasons=reasons,
                mutation_signals=mutation_hits,
                report_only_signals=report_hits,
            )

    # Explicit API task_type when provided (caller override) — still respect mutation rule.
    explicit = (explicit_task_type or "").strip().lower() or None
    if explicit in {"bugfix", "feature", "regression", "review"} and not mutation_hits:
        if explicit == "review":
            return CodingTaskIntent(
                kind="review_report_only",
                coarse_task_type="review",
                requires_mutation=False,
                report_only=True,
                reasons=["explicit_task_type:review"],
                mutation_signals=mutation_hits,
                report_only_signals=report_hits,
            )
        if explicit == "regression" and not mutation_hits:
            # Legacy "regression" meant report-only investigation unless mutation words present.
            return CodingTaskIntent(
                kind="regression_investigation_only",
                coarse_task_type="regression",
                requires_mutation=False,
                report_only=True,
                reasons=["explicit_task_type:regression"],
                mutation_signals=mutation_hits,
                report_only_signals=report_hits,
            )
        if explicit == "feature":
            return CodingTaskIntent(
                kind="feature",
                coarse_task_type="feature",
                requires_mutation=True,
                report_only=False,
                reasons=["explicit_task_type:feature"],
                mutation_signals=mutation_hits,
                report_only_signals=report_hits,
            )
        return CodingTaskIntent(
            kind="bugfix",
            coarse_task_type="bugfix",
            requires_mutation=True,
            report_only=False,
            reasons=["explicit_task_type:bugfix"],
            mutation_signals=mutation_hits,
            report_only_signals=report_hits,
        )

    # CRITICAL: mutation intent wins over investigation language.
    if mutation_hits:
        reasons.append("mutation_intent_wins")
        if _any_match(_TESTS_PATTERNS, lowered):
            return CodingTaskIntent(
                kind="tests",
                coarse_task_type="feature",
                requires_mutation=True,
                report_only=False,
                reasons=reasons + ["tests"],
                mutation_signals=mutation_hits,
                report_only_signals=report_hits,
            )
        if _any_match(_REFACTOR_PATTERNS, lowered):
            return CodingTaskIntent(
                kind="refactor",
                coarse_task_type="bugfix",
                requires_mutation=True,
                report_only=False,
                reasons=reasons + ["refactor"],
                mutation_signals=mutation_hits,
                report_only_signals=report_hits,
            )
        if _any_match(_DOCS_PATTERNS, lowered) and not _any_match(_FEATURE_PATTERNS + _MUTATION_PATTERNS[:8], lowered):
            return CodingTaskIntent(
                kind="documentation",
                coarse_task_type="feature",
                requires_mutation=True,
                report_only=False,
                reasons=reasons + ["documentation"],
                mutation_signals=mutation_hits,
                report_only_signals=report_hits,
            )
        if _any_match(_UI_PATTERNS, lowered) and _any_match(
            [r"\bcss\b", r"\bstyl", r"\bscss\b", r"\blayout\b"], lowered
        ):
            return CodingTaskIntent(
                kind="ui_style",
                coarse_task_type="feature" if _any_match(_FEATURE_PATTERNS, lowered) else "bugfix",
                requires_mutation=True,
                report_only=False,
                reasons=reasons + ["ui_style"],
                mutation_signals=mutation_hits,
                report_only_signals=report_hits,
            )
        if _any_match(_CONFIG_PATTERNS, lowered) and _any_match(
            [r"\bconfig", r"\bdocker", r"\bmakefile", r"\bgradle", r"\bci\b"], lowered
        ):
            return CodingTaskIntent(
                kind="configuration_build",
                coarse_task_type="feature",
                requires_mutation=True,
                report_only=False,
                reasons=reasons + ["configuration_build"],
                mutation_signals=mutation_hits,
                report_only_signals=report_hits,
            )
        if _any_match(_FEATURE_PATTERNS, lowered):
            return CodingTaskIntent(
                kind="feature",
                coarse_task_type="feature",
                requires_mutation=True,
                report_only=False,
                reasons=reasons + ["feature"],
                mutation_signals=mutation_hits,
                report_only_signals=report_hits,
            )
        return CodingTaskIntent(
            kind="bugfix",
            coarse_task_type="bugfix",
            requires_mutation=True,
            report_only=False,
            reasons=reasons + ["bugfix"],
            mutation_signals=mutation_hits,
            report_only_signals=report_hits,
        )

    # No mutation signals: review / regression investigation / default bugfix.
    if _any_match(_REVIEW_PATTERNS, lowered):
        return CodingTaskIntent(
            kind="review_report_only",
            coarse_task_type="review",
            requires_mutation=False,
            report_only=True,
            reasons=["review_language_without_mutation"],
            mutation_signals=mutation_hits,
            report_only_signals=report_hits,
        )
    if _any_match(_REGRESSION_INVESTIGATE_PATTERNS, lowered):
        return CodingTaskIntent(
            kind="regression_investigation_only",
            coarse_task_type="regression",
            requires_mutation=False,
            report_only=True,
            reasons=["investigation_without_mutation"],
            mutation_signals=mutation_hits,
            report_only_signals=report_hits,
        )
    if _any_match(_FEATURE_PATTERNS, lowered):
        return CodingTaskIntent(
            kind="feature",
            coarse_task_type="feature",
            requires_mutation=True,
            report_only=False,
            reasons=["feature_language"],
            mutation_signals=mutation_hits,
            report_only_signals=report_hits,
        )

    # Default: treat as bugfix (mutation) — safer than silent report-only.
    return CodingTaskIntent(
        kind="bugfix",
        coarse_task_type="bugfix",
        requires_mutation=True,
        report_only=False,
        reasons=["default_bugfix"],
        mutation_signals=mutation_hits,
        report_only_signals=report_hits,
    )
