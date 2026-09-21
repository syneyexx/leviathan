"""Targeted verification issues and bounded repair — no whole-answer rewrite by default."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


IssueSeverity = Literal["low", "medium", "high"]
IssueKind = Literal[
    "calculation",
    "unit",
    "code_test",
    "fact",
    "comparison",
    "advice_assumption",
    "summary_fidelity",
    "execution_state",
    "format",
    "missing_evidence",
    "other",
]


@dataclass(slots=True)
class VerificationIssue:
    claim_id: str
    passage: str
    kind: IssueKind
    severity: IssueSeverity
    missing_or_contrary: str
    repair_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RepairPlan:
    issues: list[VerificationIssue] = field(default_factory=list)
    rewrite_whole_answer: bool = False
    qualify_claims: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    max_repairs: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [item.to_dict() for item in self.issues],
            "rewrite_whole_answer": self.rewrite_whole_answer,
            "qualify_claims": list(self.qualify_claims),
            "instructions": list(self.instructions),
            "max_repairs": self.max_repairs,
        }


def detect_issue_kind(text: str, speech_act: str = "") -> IssueKind:
    lower = (text or "").lower()
    if re.search(r"\d", lower) and any(tok in lower for tok in ("som", "total", "€", "$", "%", "kg", "km", "mb")):
        return "calculation" if any(tok in lower for tok in ("som", "total", "+", "*", "bereken")) else "unit"
    if "```" in text or "pytest" in lower or "unittest" in lower:
        return "code_test"
    if speech_act == "compare" or " versus " in lower or " vs " in lower:
        return "comparison"
    if any(tok in lower for tok in ("samenvatting", "summary", "vat samen")):
        return "summary_fidelity"
    if any(tok in lower for tok in ("raad", "advies", "should", "aanbeveel")):
        return "advice_assumption"
    if any(tok in lower for tok in ("json", "schema", "format", "markdown table")):
        return "format"
    return "fact"


def build_repair_plan(
    *,
    draft: str,
    critic_issues: list[str] | None = None,
    unmet_criteria: list[str] | None = None,
    coverage_notes: list[str] | None = None,
    speech_act: str = "",
    max_repairs: int = 2,
) -> RepairPlan:
    issues: list[VerificationIssue] = []
    for index, raw in enumerate(critic_issues or []):
        kind = detect_issue_kind(raw, speech_act=speech_act)
        issues.append(
            VerificationIssue(
                claim_id=f"issue_{index + 1}",
                passage=raw[:240],
                kind=kind,
                severity="high" if kind in {"calculation", "code_test", "execution_state"} else "medium",
                missing_or_contrary=raw[:240],
                repair_action=_action_for(kind),
            )
        )
    for index, crit in enumerate(unmet_criteria or []):
        issues.append(
            VerificationIssue(
                claim_id=f"crit_{index + 1}",
                passage=crit[:240],
                kind="missing_evidence",
                severity="high",
                missing_or_contrary=f"Criterium niet aangetoond: {crit[:200]}",
                repair_action="Beperk of kwalificeer de claim; genereer geen sterker bewijs uit herhaling",
            )
        )
    for note in coverage_notes or []:
        if "draft_cannot_prove" in note or "insufficient" in note:
            issues.append(
                VerificationIssue(
                    claim_id="coverage_gap",
                    passage=draft[:160],
                    kind="missing_evidence",
                    severity="high",
                    missing_or_contrary=note,
                    repair_action="Markeer als niet gecontroleerd; geen factual_verified",
                )
            )

    issues = issues[: max(1, max_repairs) * 3]
    instructions = [item.repair_action for item in issues[:max_repairs]]
    qualify = [item.passage for item in issues if item.kind == "missing_evidence"][:max_repairs]
    return RepairPlan(
        issues=issues,
        rewrite_whole_answer=False,
        qualify_claims=qualify,
        instructions=instructions,
        max_repairs=max_repairs,
    )


def _action_for(kind: IssueKind) -> str:
    return {
        "calculation": "Herbereken het geraakte getal/eenheid; herschrijf niet het hele antwoord",
        "unit": "Corrigeer eenheden en totalen in de betreffende zin",
        "code_test": "Koppel aan relevante testuitvoer; claim geen groen zonder observatie",
        "fact": "Beperk de claim of voeg bronpassage toe; geen circulaire draft-refs",
        "comparison": "Zet dezelfde criteria naast elkaar voor beide opties",
        "advice_assumption": "Maak aannames en trade-offs zichtbaar",
        "summary_fidelity": "Herstel trouw aan broninclusief voorbehouden/negaties",
        "execution_state": "Beschrijf alleen uitgevoerde eindtoestand",
        "format": "Herstel gevraagd schema/structuur in het geraakte blok",
        "missing_evidence": "Kwalificeer of verwijder ongeverifyerde claim",
        "other": "Gerichte reparatie van de genoemde passage",
    }.get(kind, "Gerichte reparatie van de genoemde passage")


def apply_targeted_qualifiers(draft: str, plan: RepairPlan) -> str:
    """Qualify missing-evidence claims without regenerating the whole answer."""
    text = draft or ""
    if not plan.qualify_claims:
        return text
    suffix = "\n\n---\nNiet gecontroleerd / beperkt door ontbrekend bewijs: " + "; ".join(
        item[:120] for item in plan.qualify_claims[:3]
    )
    if suffix.strip() in text:
        return text
    return text.rstrip() + suffix
