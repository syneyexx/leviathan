"""Research TEAM quality-driven stop / progress / acceptance helpers.

Extends existing coordinator semantics without a parallel research runtime.
"""

from __future__ import annotations

from typing import Any, Sequence

from Data.modules.verification.quality_contract import (
    AcceptanceOutcome,
    AcceptanceRecord,
    CriterionVerdict,
    CriterionVerdictStatus,
    EvidenceClass,
    QualityContract,
    QualityCriterion,
    CriterionSeverity,
    aggregate_acceptance,
    criterion_progress,
    new_contract_id,
)

from .budgets import effective_round_ceiling
from .citation_audit import CitationAuditReport, CitationAuditStatus
from .gaps import ResearchGap, should_stop as fixed_budget_should_stop
from .types import ResearchBudget, ResearchExecutionMode, ResearchPhase, ResearchPlan, ResearchStatus


def is_team_mode(execution_mode: ResearchExecutionMode | str | None) -> bool:
    raw = (
        execution_mode.value
        if isinstance(execution_mode, ResearchExecutionMode)
        else str(execution_mode or "")
    )
    return raw.lower() == ResearchExecutionMode.TEAM.value


def build_research_quality_contract(
    *,
    run_id: str,
    project_id: str,
    question: str,
    plan: ResearchPlan | None = None,
    created_at: str = "",
) -> QualityContract:
    criteria = [
        QualityCriterion(
            criterion_id="crit:claims_supported",
            description="Material factual claims have inspectable supporting evidence",
            verification_method="claim_to_source_span_audit",
            evidence_class=EvidenceClass.CLAIM_SUPPORT,
            severity=CriterionSeverity.MANDATORY,
            provenance={"source": "research_team_template"},
        ),
        QualityCriterion(
            criterion_id="crit:citation_audit",
            description="Report citations resolve to recorded material and support the claim",
            verification_method="citation_audit",
            evidence_class=EvidenceClass.CITATION_AUDIT,
            severity=CriterionSeverity.MANDATORY,
            provenance={"source": "research_team_template"},
        ),
        QualityCriterion(
            criterion_id="crit:critical_gaps_resolved",
            description="No unresolved critical evidence gaps remain for the accepted scope",
            verification_method="gap_analyzer",
            evidence_class=EvidenceClass.INDEPENDENT_CHECK,
            severity=CriterionSeverity.MANDATORY,
            provenance={"source": "research_team_template"},
        ),
        QualityCriterion(
            criterion_id="crit:synthesis_rechecked",
            description="Final synthesis introduces no unsupported new material claims",
            verification_method="post_synthesis_reverification",
            evidence_class=EvidenceClass.INDEPENDENT_CHECK,
            severity=CriterionSeverity.MANDATORY,
            provenance={"source": "research_team_template"},
        ),
        QualityCriterion(
            criterion_id="crit:conflicts_surfaced",
            description="Material conflicts are preserved with limitations",
            verification_method="conflict_inspection",
            evidence_class=EvidenceClass.INDEPENDENT_CHECK,
            severity=CriterionSeverity.ADVISORY,
            provenance={"source": "research_team_template"},
        ),
    ]
    return QualityContract(
        contract_id=new_contract_id(),
        version=1,
        run_id=run_id,
        request_ref=project_id,
        scope=(plan.scope if plan else question) or question,
        expected_deliverables=["research_report", "dossier"],
        task_category="research",
        assumptions=list(plan.assumptions) if plan else [],
        criteria=criteria,
        provenance={"builder": "build_research_quality_contract"},
        created_at=created_at,
    )


def compute_team_progress(
    *,
    contract: QualityContract | None,
    verdicts: Sequence[CriterionVerdict],
    artifact_revision: str,
    iteration: int,
    phase: ResearchPhase,
) -> dict[str, Any]:
    """Criterion-level progress for TEAM — never '7 of 10 rounds'."""
    if contract is None:
        return {
            "iteration": iteration,
            "phase": phase.value,
            "mandatory_satisfied": 0,
            "mandatory_total": 0,
            "label": "criteria_satisfied",
            "display_pct": None,
            "truth": {
                "not_fixed_round_fraction": True,
                "open_ended_iteration": True,
            },
        }
    base = criterion_progress(contract, verdicts, artifact_revision=artifact_revision)
    # Optional UI hint only — labeled criteria satisfied, not percent truth.
    total = max(1, int(base["mandatory_total"]))
    satisfied = int(base["mandatory_satisfied"])
    display_pct = None
    if phase == ResearchPhase.COMPLETED and satisfied >= total:
        display_pct = 100.0
    return {
        **base,
        "iteration": iteration,
        "phase": phase.value,
        "display_pct": display_pct,
        "criteria_ratio_label": f"{satisfied}/{total} criteria satisfied",
    }


def team_should_stop(
    gaps: list[ResearchGap],
    *,
    budget: ResearchBudget,
    waves_without_gain: int,
    iteration: int,
    acceptance: AcceptanceRecord | None,
    no_progress_window: int = 3,
) -> tuple[bool, str]:
    """TEAM stop policy: quality acceptance or honest blocker — not round exhaustion success."""
    if acceptance is not None and acceptance.outcome == AcceptanceOutcome.ACCEPTED:
        return True, "quality_contract_accepted"

    # Optional user cap → stop incomplete (caller must not mark COMPLETED).
    if budget.max_iterations is not None and iteration >= budget.max_iterations:
        return True, "optional_user_cap_iterations"

    if waves_without_gain >= no_progress_window:
        return True, "no_progress_blocker"

    # Never stop solely because a legacy round ceiling was hit under TEAM.
    ceiling = effective_round_ceiling(budget)
    if ceiling is not None:
        # Should not happen for TEAM budgets; fall back to fixed policy.
        return fixed_budget_should_stop(
            gaps,
            None,
            None,
            waves_without_gain=waves_without_gain,
            max_waves=ceiling,
            budget_exhausted=iteration >= ceiling,
        )

    critical_high = [
        g
        for g in gaps
        if g.severity in {"critical", "high"} and g.expected_information_gain >= 0.45
    ]
    if not critical_high and acceptance is not None:
        # No critical gaps but acceptance not reached → keep verifying/revising unless no-progress.
        return False, "continue_toward_acceptance"

    return False, "continue"


def verdicts_from_research_state(
    contract: QualityContract,
    *,
    artifact_revision: str,
    claims_supported: int,
    claims_total: int,
    citation_report: CitationAuditReport | None,
    critical_gaps: Sequence[ResearchGap],
    synthesis_has_unsupported_claim: bool,
    evidence_ids: Sequence[str],
    conflicts_recorded: bool,
    created_at: str = "",
) -> list[CriterionVerdict]:
    """Map research artifacts to typed verdicts. Fail closed without evidence."""
    out: list[CriterionVerdict] = []
    ev = tuple(str(e) for e in evidence_ids)

    def add(cid: str, status: CriterionVerdictStatus, justification: str, use_ev: bool = True) -> None:
        evidence = ev[:12] if use_ev and status == CriterionVerdictStatus.SATISFIED else ()
        if status == CriterionVerdictStatus.SATISFIED and not evidence:
            status = CriterionVerdictStatus.UNVERIFIABLE
            justification = f"{justification} (blocked: no evidence ids)"
        out.append(
            CriterionVerdict(
                criterion_id=cid,
                contract_version=contract.version,
                artifact_revision=artifact_revision,
                status=status,
                verifier_identity="research.team_policy",
                verifier_type="deterministic_research_mapper",
                evidence_ids=evidence if status == CriterionVerdictStatus.SATISFIED else (),
                public_justification=justification,
                created_at=created_at,
            )
        )

    # claims supported
    claims_ok = claims_total > 0 and claims_supported >= max(1, claims_total) and bool(ev)
    # Allow partial material support only when ALL material claims supported.
    add(
        "crit:claims_supported",
        CriterionVerdictStatus.SATISFIED if claims_ok else CriterionVerdictStatus.UNSATISFIED,
        (
            f"{claims_supported}/{claims_total} claims supported with evidence"
            if claims_total
            else "no claims extracted"
        ),
    )

    # citation audit
    if citation_report is None or not citation_report.items:
        add(
            "crit:citation_audit",
            CriterionVerdictStatus.UNVERIFIABLE,
            "citation audit missing — UNMEASURED is not perfect",
            use_ev=False,
        )
    elif citation_report.critical_unsupported:
        add(
            "crit:citation_audit",
            CriterionVerdictStatus.UNSATISFIED,
            f"{len(citation_report.critical_unsupported)} critical unsupported citations",
        )
    else:
        supportedish = sum(
            1
            for i in citation_report.items
            if i.status
            in {
                CitationAuditStatus.SUPPORTED,
                CitationAuditStatus.PARTIALLY_SUPPORTED,
                CitationAuditStatus.INTERPRETATION,
            }
        )
        ok = supportedish == len(citation_report.items) and bool(ev)
        add(
            "crit:citation_audit",
            CriterionVerdictStatus.SATISFIED if ok else CriterionVerdictStatus.UNSATISFIED,
            f"citation audit {supportedish}/{len(citation_report.items)}",
        )

    # critical gaps
    if critical_gaps:
        add(
            "crit:critical_gaps_resolved",
            CriterionVerdictStatus.UNSATISFIED,
            f"{len(critical_gaps)} critical/high gaps remain",
            use_ev=False,
        )
    else:
        add(
            "crit:critical_gaps_resolved",
            CriterionVerdictStatus.SATISFIED,
            "no critical/high gaps remaining",
            use_ev=True,
        )

    # synthesis recheck
    if synthesis_has_unsupported_claim:
        add(
            "crit:synthesis_rechecked",
            CriterionVerdictStatus.UNSATISFIED,
            "synthesis introduced unsupported claim — gate reopened",
            use_ev=False,
        )
    elif claims_ok and not critical_gaps and citation_report and not citation_report.critical_unsupported:
        add(
            "crit:synthesis_rechecked",
            CriterionVerdictStatus.SATISFIED,
            "post-synthesis recheck clean",
        )
    else:
        add(
            "crit:synthesis_rechecked",
            CriterionVerdictStatus.PENDING,
            "awaiting clean synthesis material",
            use_ev=False,
        )

    # advisory conflicts
    add(
        "crit:conflicts_surfaced",
        CriterionVerdictStatus.SATISFIED if conflicts_recorded else CriterionVerdictStatus.PENDING,
        "conflicts recorded" if conflicts_recorded else "no conflict records yet",
        use_ev=conflicts_recorded,
    )

    return out


def accept_or_block_research(
    contract: QualityContract,
    verdicts: Sequence[CriterionVerdict],
    *,
    artifact_revision: str,
    stop_reason: str,
) -> tuple[ResearchStatus, AcceptanceRecord]:
    """Map acceptance to research status. COMPLETED only on quality acceptance."""
    record = aggregate_acceptance(
        contract,
        verdicts,
        artifact_revision=artifact_revision,
    )
    if record.outcome == AcceptanceOutcome.ACCEPTED:
        return ResearchStatus.COMPLETED, record
    if stop_reason in {"optional_user_cap_iterations", "no_progress_blocker"}:
        return ResearchStatus.BLOCKED, record
    if stop_reason.startswith("missing") or "input" in stop_reason:
        return ResearchStatus.WAITING_FOR_INPUT, record
    if record.outcome == AcceptanceOutcome.BLOCKED:
        return ResearchStatus.BLOCKED, record
    # Still working
    return ResearchStatus.RESEARCHING, record
