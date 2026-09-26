"""Critic mesh for Cognition (W5).

Critic output is advisory analysis — NOT verification proof.
Critics cannot perform unauthorized side effects.

IntegrityCritic is TECHNICAL only (same boundary as IntegrityScorer).
ProcessCritic may reuse neuro ProcessCritic when available; otherwise local.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class CriticFinding:
    critic: str
    severity: str  # info | low | medium | high
    message: str
    refs: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "critic": self.critic,
            "severity": self.severity,
            "message": self.message,
            "refs": list(self.refs),
        }


@dataclass
class CriticReport:
    findings: list[CriticFinding] = field(default_factory=list)
    recommend: str = "continue"  # continue | replan | verify | stop
    reason: str = ""
    scores: dict[str, float] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.public_dict() for f in self.findings],
            "recommend": self.recommend,
            "reason": self.reason,
            "scores": dict(self.scores),
            "truth": {
                "critic_is_not_verification_proof": True,
                "critics_cannot_authorize_side_effects": True,
            },
        }


class ProcessCritic:
    name = "ProcessCritic"

    def critique(self, *, text: str, plan_steps: Sequence[str] | None = None) -> CriticFinding | None:
        if not text.strip():
            return CriticFinding(self.name, "medium", "empty response mid-process")
        steps = list(plan_steps or ())
        if steps:
            lowered = text.lower()
            covered = sum(1 for s in steps if any(tok in lowered for tok in str(s).lower().split()[:3]))
            if covered == 0 and len(steps) >= 2:
                return CriticFinding(
                    self.name,
                    "medium",
                    "response does not reference plan steps",
                    refs=tuple(str(s)[:40] for s in steps[:3]),
                )
        return None


class FactualCritic:
    name = "FactualCritic"

    def critique(
        self,
        *,
        text: str,
        evidence_ids: Sequence[str] | None = None,
        require_evidence: bool = False,
    ) -> CriticFinding | None:
        ids = list(evidence_ids or [])
        if require_evidence and not ids:
            return CriticFinding(self.name, "high", "factual claim path lacks evidence ids")
        if require_evidence and ids:
            blob = text.lower()
            if not any(str(i).lower() in blob for i in ids):
                return CriticFinding(
                    self.name,
                    "medium",
                    "evidence ids not cited in answer",
                    refs=tuple(str(i) for i in ids[:5]),
                )
        return None


class PlanCritic:
    name = "PlanCritic"

    def critique(self, *, plan_steps: Sequence[str] | None, acceptance: Sequence[str] | None) -> CriticFinding | None:
        steps = list(plan_steps or [])
        if not steps:
            return CriticFinding(self.name, "low", "plan has no steps")
        if acceptance is not None and not list(acceptance):
            return CriticFinding(self.name, "medium", "plan lacks acceptance conditions")
        return None


class IntegrityCritic:
    """Technical integrity — not moral/political content moderation."""

    name = "IntegrityCritic"

    def critique(self, *, text: str) -> CriticFinding | None:
        lowered = text.lower()
        if "i will ignore" in lowered and "system" in lowered:
            return CriticFinding(self.name, "high", "prompt-injection boundary risk in output")
        if re.search(r"(api[_-]?key|password)\s*[:=]\s*\S+", text, re.I):
            return CriticFinding(self.name, "high", "secret leakage pattern")
        if re.search(r"\bi (?:ran|executed) (?:the )?tests?\b", lowered) and "receipt" not in lowered:
            return CriticFinding(self.name, "medium", "possible fabricated test claim")
        return None


class CodeCritic:
    name = "CodeCritic"

    def critique(self, *, text: str, domain: str | None = None) -> CriticFinding | None:
        if domain != "coding":
            return None
        lowered = text.lower()
        if "fixed" in lowered and "test" not in lowered:
            return CriticFinding(
                self.name,
                "medium",
                "claims fixed without mentioning tests/evidence",
            )
        return None


class ConsistencyCritic:
    name = "ConsistencyCritic"

    def critique(self, *, text: str, prior: str | None = None) -> CriticFinding | None:
        if not prior or not text:
            return None
        a = set(re.findall(r"[a-z0-9]{4,}", text.lower()))
        b = set(re.findall(r"[a-z0-9]{4,}", prior.lower()))
        if not a or not b:
            return None
        jaccard = len(a & b) / max(1, len(a | b))
        # Extremely low overlap after a follow-up can be fine; flag only total contradiction markers.
        if "actually the opposite" in text.lower() or "ignore what i said" in text.lower():
            return CriticFinding(self.name, "medium", "self-contradiction marker", refs=(f"jaccard={jaccard:.2f}",))
        return None


class CriticMesh:
    """Bounded mesh — advisory only."""

    def __init__(self) -> None:
        self.process = ProcessCritic()
        self.factual = FactualCritic()
        self.plan = PlanCritic()
        self.integrity = IntegrityCritic()
        self.code = CodeCritic()
        self.consistency = ConsistencyCritic()

    def run(
        self,
        *,
        text: str,
        plan_steps: Sequence[str] | None = None,
        acceptance: Sequence[str] | None = None,
        evidence_ids: Sequence[str] | None = None,
        require_evidence: bool = False,
        domain: str | None = None,
        prior_text: str | None = None,
    ) -> CriticReport:
        findings: list[CriticFinding] = []
        for result in (
            self.process.critique(text=text, plan_steps=plan_steps),
            self.factual.critique(
                text=text, evidence_ids=evidence_ids, require_evidence=require_evidence
            ),
            self.plan.critique(plan_steps=plan_steps, acceptance=acceptance),
            self.integrity.critique(text=text),
            self.code.critique(text=text, domain=domain),
            self.consistency.critique(text=text, prior=prior_text),
        ):
            if result is not None:
                findings.append(result)

        recommend = "continue"
        reason = "no blocking critic findings"
        high = [f for f in findings if f.severity == "high"]
        medium = [f for f in findings if f.severity == "medium"]
        if high:
            recommend = "verify" if any("evidence" in f.message or "fabricated" in f.message for f in high) else "replan"
            reason = high[0].message
        elif len(medium) >= 2:
            recommend = "replan"
            reason = "multiple medium critic findings"

        scores = {
            "finding_count": float(len(findings)),
            "high_count": float(len(high)),
            "medium_count": float(len(medium)),
        }
        return CriticReport(
            findings=findings,
            recommend=recommend,
            reason=reason,
            scores=scores,
        )
