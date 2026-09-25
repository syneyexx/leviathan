"""Named domain critic mesh — public critique signals, not private CoT.

Critics are deterministic heuristics over run state. They recommend actions
(continue / retrieve / replan / verify / compact) without inventing facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class CriticFinding:
    critic_id: str
    domain: str
    severity: str  # info | warn | high
    finding: str
    recommend: str  # continue | retrieve | replan | verify | compact
    evidence_refs: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "critic_id": self.critic_id,
            "domain": self.domain,
            "severity": self.severity,
            "finding": self.finding,
            "recommend": self.recommend,
            "evidence_refs": list(self.evidence_refs),
            "truth": {
                "critic_is_not_private_cot": True,
                "finding_is_not_verified_fact": True,
            },
        }


@dataclass(frozen=True)
class CriticMeshReport:
    findings: tuple[CriticFinding, ...]
    recommend: str
    reason: str
    critics_run: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.public_dict() for f in self.findings],
            "recommend": self.recommend,
            "reason": self.reason,
            "critics_run": list(self.critics_run),
            "finding_count": len(self.findings),
            "truth": {
                "critic_mesh_is_named_domain_critics": True,
                "not_a_second_runtime": True,
                "not_private_cot": True,
            },
        }


class DomainCritic(Protocol):
    critic_id: str
    domain: str

    def critique(self, ctx: Mapping[str, Any]) -> CriticFinding | None: ...


@dataclass
class EvidenceCoverageCritic:
    critic_id: str = "evidence_coverage"
    domain: str = "evidence"

    def critique(self, ctx: Mapping[str, Any]) -> CriticFinding | None:
        coverage = float(ctx.get("evidence_coverage") or 0.0)
        requires_research = bool(ctx.get("requires_research"))
        open_hypotheses = int(ctx.get("open_hypothesis_count") or 0)
        uncertainty = float(ctx.get("belief_uncertainty") or 0.0)
        if requires_research and coverage < 0.35:
            return CriticFinding(
                critic_id=self.critic_id,
                domain=self.domain,
                severity="high",
                finding="research task has low evidence coverage",
                recommend="retrieve",
            )
        if open_hypotheses > 0 and coverage < 0.25:
            return CriticFinding(
                critic_id=self.critic_id,
                domain=self.domain,
                severity="warn",
                finding="open hypotheses lack supporting evidence",
                recommend="retrieve",
            )
        if uncertainty > 0.75 and coverage < 0.5:
            return CriticFinding(
                critic_id=self.critic_id,
                domain=self.domain,
                severity="warn",
                finding="high belief uncertainty with thin evidence",
                recommend="retrieve",
            )
        return None


@dataclass
class ConsistencyCritic:
    critic_id: str = "consistency"
    domain: str = "consistency"

    def critique(self, ctx: Mapping[str, Any]) -> CriticFinding | None:
        density = float(ctx.get("contradiction_density") or 0.0)
        unresolved = int(ctx.get("unresolved_hypothesis_count") or 0)
        if density >= 0.4 or unresolved >= 2:
            return CriticFinding(
                critic_id=self.critic_id,
                domain=self.domain,
                severity="high" if density >= 0.5 else "warn",
                finding="contradictions or unresolved competing hypotheses",
                recommend="replan",
            )
        return None


@dataclass
class RiskGateCritic:
    critic_id: str = "risk_gate"
    domain: str = "risk"

    def critique(self, ctx: Mapping[str, Any]) -> CriticFinding | None:
        risk = str(ctx.get("risk_class") or "LOW").upper()
        verified = ctx.get("verification_passed")
        side_effects = bool(ctx.get("has_side_effects"))
        if risk in {"HIGH", "CRITICAL"} and verified is not True:
            return CriticFinding(
                critic_id=self.critic_id,
                domain=self.domain,
                severity="high",
                finding="high-risk task lacks verification pass",
                recommend="verify",
            )
        if side_effects and verified is not True:
            return CriticFinding(
                critic_id=self.critic_id,
                domain=self.domain,
                severity="warn",
                finding="side-effect path without verification",
                recommend="verify",
            )
        return None


@dataclass
class CompletenessCritic:
    critic_id: str = "completeness"
    domain: str = "completeness"

    def critique(self, ctx: Mapping[str, Any]) -> CriticFinding | None:
        criteria = int(ctx.get("success_criteria_count") or 0)
        has_response = bool(ctx.get("has_response"))
        plan_progress = float(ctx.get("plan_progress") or 0.0)
        if bool(ctx.get("plan_stale")):
            return CriticFinding(
                critic_id=self.critic_id,
                domain=self.domain,
                severity="high",
                finding="plan is stale",
                recommend="replan",
            )
        if criteria > 0 and has_response and plan_progress < 0.4:
            return CriticFinding(
                critic_id=self.critic_id,
                domain=self.domain,
                severity="warn",
                finding="response present but plan progress incomplete vs criteria",
                recommend="continue",
            )
        fail_count = int(ctx.get("failure_observation_count") or 0)
        if fail_count >= 2:
            return CriticFinding(
                critic_id=self.critic_id,
                domain=self.domain,
                severity="high",
                finding="repeated failed observations",
                recommend="replan",
            )
        return None


@dataclass
class FreshnessCritic:
    critic_id: str = "freshness"
    domain: str = "freshness"

    def critique(self, ctx: Mapping[str, Any]) -> CriticFinding | None:
        if not bool(ctx.get("requires_current_information")):
            return None
        coverage = float(ctx.get("evidence_coverage") or 0.0)
        if coverage < 0.5:
            return CriticFinding(
                critic_id=self.critic_id,
                domain=self.domain,
                severity="warn",
                finding="freshness required but evidence coverage is thin",
                recommend="retrieve",
            )
        return None


@dataclass
class WorkingMemoryCritic:
    critic_id: str = "working_memory"
    domain: str = "memory"

    def critique(self, ctx: Mapping[str, Any]) -> CriticFinding | None:
        sat = float(ctx.get("working_memory_saturation") or 0.0)
        if sat > 0.9:
            return CriticFinding(
                critic_id=self.critic_id,
                domain=self.domain,
                severity="warn",
                finding="working memory saturated",
                recommend="compact",
            )
        return None


_RECOMMEND_PRIORITY = {
    "replan": 5,
    "verify": 4,
    "retrieve": 3,
    "compact": 2,
    "continue": 1,
}


@dataclass
class CriticMesh:
    """Run named domain critics and merge recommendations."""

    critics: tuple[Any, ...] = field(
        default_factory=lambda: (
            EvidenceCoverageCritic(),
            ConsistencyCritic(),
            RiskGateCritic(),
            CompletenessCritic(),
            FreshnessCritic(),
            WorkingMemoryCritic(),
        )
    )

    def evaluate(self, ctx: Mapping[str, Any]) -> CriticMeshReport:
        findings: list[CriticFinding] = []
        ran: list[str] = []
        for critic in self.critics:
            ran.append(str(getattr(critic, "critic_id", type(critic).__name__)))
            try:
                finding = critic.critique(ctx)
            except Exception:  # noqa: BLE001
                continue
            if finding is not None:
                findings.append(finding)

        if not findings:
            return CriticMeshReport(
                findings=(),
                recommend="continue",
                reason="ok",
                critics_run=tuple(ran),
            )

        # Highest-priority recommendation wins; ties prefer higher severity.
        def _key(f: CriticFinding) -> tuple[int, int]:
            sev = {"high": 2, "warn": 1, "info": 0}.get(f.severity, 0)
            return (_RECOMMEND_PRIORITY.get(f.recommend, 0), sev)

        top = max(findings, key=_key)
        return CriticMeshReport(
            findings=tuple(findings),
            recommend=top.recommend,
            reason=top.finding,
            critics_run=tuple(ran),
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "critic_ids": [getattr(c, "critic_id", type(c).__name__) for c in self.critics],
            "domains": [getattr(c, "domain", "unknown") for c in self.critics],
            "truth": {"named_domain_critics": True},
        }
