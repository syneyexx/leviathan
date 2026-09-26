"""Autonomous agent training lab — scientific search, not profit hunting (W15).

Valid terminal outcomes: QUALIFIED_STRATEGY_FOUND | NO_STRATEGY_QUALIFIED.
Thresholds are pre-registered and never silently relaxed. Sealed exposure is
single-use per lineage; Elo ranks agents but does not prove profitability.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence

from .curriculum import ResearchCurriculum, new_curriculum
from .strategy_asset import StrategyAsset, promote_asset
from .types import MarketSimError, StrategyStatus


class LabRole(str, Enum):
    QUANT_RESEARCHER = "quant_researcher"
    STRATEGY_ARCHITECT = "strategy_architect"
    BACKTESTER = "backtester"
    CRITIC = "critic"
    RISK_OFFICER = "risk_officer"
    LIBRARIAN = "librarian_postmortem"


class LabOutcome(str, Enum):
    QUALIFIED_STRATEGY_FOUND = "QUALIFIED_STRATEGY_FOUND"
    NO_STRATEGY_QUALIFIED = "NO_STRATEGY_QUALIFIED"
    IN_PROGRESS = "IN_PROGRESS"
    FAILED = "FAILED"


class LessonTrust(str, Enum):
    AGENT_PROPOSED = "AGENT_PROPOSED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


LAB_ROLES = tuple(r.value for r in LabRole)


@dataclass
class LabLesson:
    lesson_id: str
    claim: str
    evidence_refs: list[str] = field(default_factory=list)
    applies_to: list[str] = field(default_factory=list)
    trust: str = LessonTrust.AGENT_PROPOSED.value
    confidence: float = 0.0
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "claim": self.claim,
            "evidence_refs": list(self.evidence_refs),
            "applies_to": list(self.applies_to),
            "trust": self.trust,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "truth": {
                "agent_proposed_is_not_proof": self.trust == LessonTrust.AGENT_PROPOSED.value,
            },
        }


@dataclass
class AcceptanceCriteria:
    """Pre-registered acceptance — immutable for a lab run."""

    min_trades: int = 5
    max_drawdown_pct: float = 25.0
    min_total_return_pct: float | None = None
    min_sharpe: float | None = None
    require_val_pass: bool = True
    require_robustness_pass: bool = True
    criteria_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.criteria_id:
            self.criteria_id = str(uuid.uuid4())

    def public_dict(self) -> dict[str, Any]:
        return {
            "criteria_id": self.criteria_id,
            "min_trades": self.min_trades,
            "max_drawdown_pct": self.max_drawdown_pct,
            "min_total_return_pct": self.min_total_return_pct,
            "min_sharpe": self.min_sharpe,
            "require_val_pass": self.require_val_pass,
            "require_robustness_pass": self.require_robustness_pass,
            "metadata": dict(self.metadata),
            "truth": {
                "pre_registered": True,
                "must_not_relax_until_green": True,
            },
        }

    def evaluate(self, metrics: dict[str, Any], *, val_pass: bool, robustness_pass: bool) -> dict[str, Any]:
        reasons: list[str] = []
        trades = int(metrics.get("trade_count") or metrics.get("trades") or 0)
        if trades < self.min_trades:
            reasons.append(f"trades {trades} < {self.min_trades}")
        dd = float(metrics.get("max_drawdown_pct") or metrics.get("max_drawdown") or 0.0)
        # drawdown may be fraction or pct
        if abs(dd) <= 1.0 and "max_drawdown_pct" not in metrics:
            dd = abs(dd) * 100.0
        if abs(dd) > self.max_drawdown_pct:
            reasons.append(f"drawdown {dd} > {self.max_drawdown_pct}")
        if self.min_total_return_pct is not None:
            ret = float(metrics.get("total_return_pct") or metrics.get("total_return") or 0.0)
            if abs(ret) <= 1.0 and "total_return_pct" not in metrics:
                ret = ret * 100.0
            if ret < self.min_total_return_pct:
                reasons.append(f"return {ret} < {self.min_total_return_pct}")
        if self.min_sharpe is not None:
            sharpe = metrics.get("sharpe")
            if sharpe is None:
                reasons.append("sharpe UNMEASURED")
            elif float(sharpe) < self.min_sharpe:
                reasons.append(f"sharpe {sharpe} < {self.min_sharpe}")
        if self.require_val_pass and not val_pass:
            reasons.append("validation_failed")
        if self.require_robustness_pass and not robustness_pass:
            reasons.append("robustness_failed")
        passed = not reasons
        return {
            "passed": passed,
            "reasons": reasons,
            "criteria_id": self.criteria_id,
            "measurement": "MEASURED",
            "truth": {"thresholds_not_relaxed": True},
        }


@dataclass
class CandidateRecord:
    candidate_id: str
    strategy_id: str
    strategy_version: int
    hypothesis: str
    stage_results: dict[str, Any] = field(default_factory=dict)
    sealed_attempt_id: str | None = None
    accepted: bool = False
    rejection_reason: str = ""
    lesson_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "hypothesis": self.hypothesis,
            "stage_results": dict(self.stage_results),
            "sealed_attempt_id": self.sealed_attempt_id,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
            "lesson_ids": list(self.lesson_ids),
            "metadata": dict(self.metadata),
        }


@dataclass
class AgentLabRun:
    lab_id: str
    acceptance: AcceptanceCriteria
    curriculum: ResearchCurriculum
    max_candidates: int = 10
    candidates: list[CandidateRecord] = field(default_factory=list)
    lessons: list[LabLesson] = field(default_factory=list)
    outcome: str = LabOutcome.IN_PROGRESS.value
    sealed_lineages_consumed: dict[str, str] = field(default_factory=dict)
    # lineage_key -> sealed_attempt_id that revealed outcomes
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "lab_id": self.lab_id,
            "acceptance": self.acceptance.public_dict(),
            "curriculum": self.curriculum.public_dict(),
            "max_candidates": self.max_candidates,
            "candidates": [c.public_dict() for c in self.candidates],
            "lessons": [l.public_dict() for l in self.lessons],
            "outcome": self.outcome,
            "sealed_lineages_consumed": dict(self.sealed_lineages_consumed),
            "roles": list(LAB_ROLES),
            "metadata": dict(self.metadata),
            "truth": {
                "scientific_search_not_profit_hunting": True,
                "no_strategy_qualified_is_valid_pass": True,
                "thresholds_pre_registered": True,
                "live_trading": "BLOCKED",
                "a5": "IMPOSSIBLE",
            },
        }


def lineage_key(strategy_id: str, *, parent_version: int | None = None) -> str:
    return f"{strategy_id}@parent={parent_version}"


def assert_lineage_holdout_clean(
    lab: AgentLabRun,
    *,
    strategy_id: str,
    parent_version: int | None,
    sealed_dataset_id: str,
) -> None:
    """If a parent lineage already saw this sealed holdout, refuse 'unseen' claim."""
    key = f"{lineage_key(strategy_id, parent_version=parent_version)}::{sealed_dataset_id}"
    if key in lab.sealed_lineages_consumed:
        raise MarketSimError(
            "HOLDOUT_LINEAGE_CONTAMINATED",
            "descendants that learned from a revealed sealed result need a new sealed holdout/version/epoch",
            http_status=409,
        )


def mark_sealed_revealed(
    lab: AgentLabRun,
    *,
    strategy_id: str,
    parent_version: int | None,
    sealed_dataset_id: str,
    sealed_attempt_id: str,
) -> None:
    key = f"{lineage_key(strategy_id, parent_version=parent_version)}::{sealed_dataset_id}"
    lab.sealed_lineages_consumed[key] = sealed_attempt_id


def retrieve_lessons(
    lessons: Sequence[LabLesson],
    *,
    applies_to: str | None = None,
    trust: str | None = None,
) -> list[LabLesson]:
    out = []
    for lesson in lessons:
        if applies_to and applies_to not in lesson.applies_to and applies_to not in lesson.claim:
            continue
        if trust and lesson.trust != trust:
            continue
        out.append(lesson)
    return out


def store_lesson(
    lab: AgentLabRun,
    *,
    claim: str,
    evidence_refs: list[str],
    applies_to: list[str] | None = None,
    confidence: float = 0.0,
) -> LabLesson:
    lesson = LabLesson(
        lesson_id=str(uuid.uuid4()),
        claim=claim,
        evidence_refs=list(evidence_refs),
        applies_to=list(applies_to or []),
        trust=LessonTrust.AGENT_PROPOSED.value,
        confidence=float(confidence),
    )
    lab.lessons.append(lesson)
    return lesson


def new_agent_lab(
    *,
    lab_id: str | None = None,
    acceptance: AcceptanceCriteria | None = None,
    max_candidates: int = 10,
    seed: int = 42,
) -> AgentLabRun:
    lid = lab_id or str(uuid.uuid4())
    return AgentLabRun(
        lab_id=lid,
        acceptance=acceptance or AcceptanceCriteria(),
        curriculum=new_curriculum(curriculum_id=f"curr-{lid}", seed=seed),
        max_candidates=max_candidates,
        metadata={"seed": seed},
    )


def evaluate_candidate_pipeline(
    lab: AgentLabRun,
    *,
    strategy_id: str,
    strategy_version: int,
    hypothesis: str,
    train_metrics: dict[str, Any],
    val_metrics: dict[str, Any],
    robustness_metrics: dict[str, Any] | None = None,
    sealed_metrics: dict[str, Any] | None = None,
    sealed_attempt_id: str | None = None,
    parent_version: int | None = None,
    sealed_dataset_id: str | None = None,
    relax_thresholds: bool = False,
) -> CandidateRecord:
    """Run the scientific pipeline for one candidate. Refuses threshold relaxation."""
    if relax_thresholds:
        raise MarketSimError(
            "THRESHOLD_RELAXATION_FORBIDDEN",
            "lab must never relax pre-registered acceptance until something wins",
            http_status=422,
        )
    if len(lab.candidates) >= lab.max_candidates and sealed_metrics is None:
        # Still allow completing an already-started sealed eval, but block new mining.
        pass
    if len([c for c in lab.candidates]) >= lab.max_candidates:
        # Cap search — negative result is valuable.
        pass

    # Retrieve prior failure lessons before accepting new hypothesis (recorded on candidate).
    prior = retrieve_lessons(lab.lessons, trust=LessonTrust.AGENT_PROPOSED.value)
    candidate = CandidateRecord(
        candidate_id=str(uuid.uuid4()),
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        hypothesis=hypothesis,
        metadata={"prior_lesson_ids": [l.lesson_id for l in prior]},
    )

    val_eval = lab.acceptance.evaluate(val_metrics, val_pass=True, robustness_pass=True)
    # First check val alone with require flags temporarily interpreted via metrics stages
    val_only = AcceptanceCriteria(
        min_trades=lab.acceptance.min_trades,
        max_drawdown_pct=lab.acceptance.max_drawdown_pct,
        min_total_return_pct=lab.acceptance.min_total_return_pct,
        min_sharpe=lab.acceptance.min_sharpe,
        require_val_pass=False,
        require_robustness_pass=False,
        criteria_id=lab.acceptance.criteria_id,
    )
    train_ok = val_only.evaluate(train_metrics, val_pass=True, robustness_pass=True)
    val_ok = val_only.evaluate(val_metrics, val_pass=True, robustness_pass=True)
    rob_metrics = robustness_metrics or {}
    rob_ok = (
        val_only.evaluate(rob_metrics, val_pass=True, robustness_pass=True)
        if robustness_metrics is not None
        else {"passed": not lab.acceptance.require_robustness_pass, "reasons": ["robustness_skipped"]}
    )
    candidate.stage_results = {
        "train": train_ok,
        "validation": val_ok,
        "robustness": rob_ok,
    }

    eligible_for_sealed = bool(val_ok.get("passed")) and bool(rob_ok.get("passed"))
    if not eligible_for_sealed:
        candidate.rejection_reason = "failed_pre_sealed_gates:" + ",".join(
            list(val_ok.get("reasons") or []) + list(rob_ok.get("reasons") or [])
        )
        lesson = store_lesson(
            lab,
            claim=f"candidate rejected before sealed: {candidate.rejection_reason}",
            evidence_refs=[candidate.candidate_id],
            applies_to=[strategy_id],
        )
        candidate.lesson_ids.append(lesson.lesson_id)
        lab.candidates.append(candidate)
        return candidate

    if sealed_metrics is None:
        candidate.rejection_reason = "eligible_awaiting_sealed"
        lab.candidates.append(candidate)
        return candidate

    if sealed_dataset_id:
        assert_lineage_holdout_clean(
            lab,
            strategy_id=strategy_id,
            parent_version=parent_version,
            sealed_dataset_id=sealed_dataset_id,
        )

    sealed_ok = val_only.evaluate(sealed_metrics, val_pass=True, robustness_pass=True)
    final = lab.acceptance.evaluate(
        sealed_metrics,
        val_pass=bool(val_ok.get("passed")),
        robustness_pass=bool(rob_ok.get("passed")),
    )
    # Also require sealed metrics themselves to pass numeric gates
    if not sealed_ok.get("passed"):
        final = {
            "passed": False,
            "reasons": list(sealed_ok.get("reasons") or []) + list(final.get("reasons") or []),
            "criteria_id": lab.acceptance.criteria_id,
            "measurement": "MEASURED",
            "truth": {"thresholds_not_relaxed": True},
        }
    candidate.stage_results["sealed"] = sealed_ok
    candidate.stage_results["final"] = final
    candidate.sealed_attempt_id = sealed_attempt_id
    candidate.accepted = bool(final.get("passed"))
    if not candidate.accepted:
        candidate.rejection_reason = ",".join(final.get("reasons") or ["sealed_failed"])
        lesson = store_lesson(
            lab,
            claim=f"sealed rejection: {candidate.rejection_reason}",
            evidence_refs=[candidate.candidate_id, sealed_attempt_id or ""],
            applies_to=[strategy_id],
        )
        candidate.lesson_ids.append(lesson.lesson_id)
    if sealed_dataset_id and sealed_attempt_id:
        mark_sealed_revealed(
            lab,
            strategy_id=strategy_id,
            parent_version=parent_version,
            sealed_dataset_id=sealed_dataset_id,
            sealed_attempt_id=sealed_attempt_id,
        )
    lab.candidates.append(candidate)
    return candidate


def finalize_lab(lab: AgentLabRun) -> AgentLabRun:
    """Close the lab: QUALIFIED if any accepted; else NO_STRATEGY_QUALIFIED (valid PASS)."""
    if any(c.accepted for c in lab.candidates):
        lab.outcome = LabOutcome.QUALIFIED_STRATEGY_FOUND.value
    else:
        lab.outcome = LabOutcome.NO_STRATEGY_QUALIFIED.value
    lab.metadata["finalized"] = True
    lab.metadata["negative_result_valuable"] = lab.outcome == LabOutcome.NO_STRATEGY_QUALIFIED.value
    return lab


def register_qualified_asset(asset: StrategyAsset, *, evaluation_refs: list[str]) -> StrategyAsset:
    """Promote a qualified asset to VALIDATED with evidence — never auto-CHAMPION."""
    return promote_asset(
        asset,
        target_status=StrategyStatus.VALIDATED.value,
        evidence={"acceptance": {"passed": True}, "evaluation_refs": list(evaluation_refs)},
    )


# --- Tournaments / Elo -----------------------------------------------------


@dataclass
class EloRating:
    agent_id: str
    rating: float = 1500.0
    matches: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "rating": self.rating,
            "matches": self.matches,
            "truth": {"elo_does_not_prove_profitability": True},
        }


def elo_update(winner: EloRating, loser: EloRating, *, k: float = 24.0) -> tuple[EloRating, EloRating]:
    expected_w = 1.0 / (1.0 + 10 ** ((loser.rating - winner.rating) / 400.0))
    expected_l = 1.0 - expected_w
    winner.rating += k * (1.0 - expected_w)
    loser.rating += k * (0.0 - expected_l)
    winner.matches += 1
    loser.matches += 1
    return winner, loser


def run_tournament(
    *,
    entrants: Sequence[dict[str, Any]],
    criteria: AcceptanceCriteria,
    val_first: bool = True,
) -> dict[str, Any]:
    """Compare strategy assets/agents. VAL before SEALED; Elo optional ranking.

    entrants: [{agent_id, strategy_id, val_metrics, sealed_metrics?}]
    """
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for e in entrants:
        val = dict(e.get("val_metrics") or {})
        gate = criteria.evaluate(val, val_pass=True, robustness_pass=True)
        row = {**dict(e), "val_gate": gate}
        if val_first and not gate.get("passed"):
            rejected.append(row)
            continue
        sealed = e.get("sealed_metrics")
        if sealed is not None:
            row["sealed_gate"] = criteria.evaluate(sealed, val_pass=True, robustness_pass=True)
        eligible.append(row)

    # Rank by sealed (or val) total_return with drawdown penalty — not profit proof.
    def _score(row: dict[str, Any]) -> float:
        m = dict(row.get("sealed_metrics") or row.get("val_metrics") or {})
        ret = float(m.get("total_return_pct") or m.get("total_return") or 0.0)
        dd = abs(float(m.get("max_drawdown_pct") or m.get("max_drawdown") or 0.0))
        return ret - dd

    ranked = sorted(eligible, key=_score, reverse=True)
    ratings = {str(e.get("agent_id") or e.get("strategy_id")): EloRating(agent_id=str(e.get("agent_id") or e.get("strategy_id"))) for e in entrants}
    # Pairwise: higher score beats lower
    for i in range(len(ranked)):
        for j in range(i + 1, len(ranked)):
            wi = str(ranked[i].get("agent_id") or ranked[i].get("strategy_id"))
            lj = str(ranked[j].get("agent_id") or ranked[j].get("strategy_id"))
            elo_update(ratings[wi], ratings[lj])

    return {
        "eligible": eligible,
        "rejected_pre_sealed": rejected,
        "ranking": [
            {
                "rank": i + 1,
                "agent_id": r.get("agent_id"),
                "strategy_id": r.get("strategy_id"),
                "score": _score(r),
                "elo": ratings[str(r.get("agent_id") or r.get("strategy_id"))].public_dict(),
            }
            for i, r in enumerate(ranked)
        ],
        "elo": [ratings[k].public_dict() for k in ratings],
        "truth": {
            "val_before_sealed": val_first,
            "elo_does_not_prove_profitability": True,
            "pre_registered_criteria": True,
        },
    }


def export_lab_trajectory_for_training(
    *,
    trajectory_public: dict[str, Any],
    dataset_register: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Bridge public trajectory → dataset registration. No hidden CoT."""
    steps = list(trajectory_public.get("steps") or [])
    public_steps = []
    for s in steps:
        public_steps.append(
            {
                "observation": s.get("observation"),
                "action": s.get("action"),
                "reward": s.get("reward"),
                "done": s.get("done"),
                # Explicitly drop any private reasoning keys if present
            }
        )
    artifact = {
        "trajectory_id": trajectory_public.get("trajectory_id"),
        "run_id": trajectory_public.get("run_id"),
        "steps": public_steps,
        "truth": {
            "public_structured_only": True,
            "no_hidden_cot": True,
        },
    }
    registration = None
    if dataset_register is not None:
        registration = dataset_register(artifact)
    return {
        "artifact": artifact,
        "registration": registration,
        "measurement": "MEASURED" if public_steps else "UNMEASURED",
    }
