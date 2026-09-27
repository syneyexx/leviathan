"""Paper-forward drift detection and continual research hook (W24 / W127).

Detects performance decay vs validation/backtest baselines.
Raises research/governance tickets — never auto-promotes or auto-disables
unless an existing policy explicitly permits it. Live trading remains BLOCKED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class DriftSignal:
    metric: str
    baseline: float
    observed: float
    threshold: float
    drifted: bool
    status: str = "MEASURED"

    def public_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "observed": self.observed,
            "threshold": self.threshold,
            "drifted": self.drifted,
            "status": self.status,
            "truth": {"drift_from_paper_forward_evidence": True},
        }


@dataclass
class ContinualResearchTicket:
    ticket_id: str
    reason: str
    signals: list[DriftSignal] = field(default_factory=list)
    status: str = "OPEN"
    research_question: str | None = None
    strategy_id: str | None = None
    strategy_version: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "ticketId": self.ticket_id,
            "reason": self.reason,
            "signals": [s.public_dict() for s in self.signals],
            "status": self.status,
            "researchQuestion": self.research_question,
            "strategyId": self.strategy_id,
            "strategyVersion": self.strategy_version,
            "truth": {
                "does_not_auto_promote": True,
                "does_not_auto_disable": True,
                "live_trading_blocked": True,
            },
        }


def detect_metric_drift(
    *,
    metric: str,
    baseline: float,
    observed: float,
    relative_threshold: float = 0.25,
) -> DriftSignal:
    if baseline == 0:
        drifted = observed != 0
        thr = relative_threshold
    else:
        thr = abs(baseline) * relative_threshold
        drifted = abs(observed - baseline) > thr
    return DriftSignal(
        metric=metric,
        baseline=baseline,
        observed=observed,
        threshold=thr if baseline != 0 else relative_threshold,
        drifted=drifted,
    )


def paper_forward_drift_review(
    *,
    baseline_metrics: dict[str, float],
    observed_metrics: dict[str, float],
    relative_threshold: float = 0.25,
    strategy_id: str | None = None,
    strategy_version: str | None = None,
    sample_size: int | None = None,
    min_sample_size: int = 5,
) -> dict[str, Any]:
    """Compare backtest/validation expectation vs paper-forward observation.

    Insufficient sample → UNMEASURED (no fabricated drift).
    """
    if sample_size is not None and int(sample_size) < int(min_sample_size):
        return {
            "signals": [],
            "driftCount": 0,
            "continualResearch": None,
            "status": "UNMEASURED",
            "reason": "insufficient_paper_sample",
            "sampleSize": sample_size,
            "minSampleSize": min_sample_size,
            "truth": {
                "drift_detection_implemented": True,
                "auto_live_promotion_forbidden": True,
                "insufficient_sample_not_fabricated": True,
            },
        }
    signals = [
        detect_metric_drift(
            metric=k,
            baseline=float(baseline_metrics[k]),
            observed=float(observed_metrics.get(k, baseline_metrics[k])),
            relative_threshold=relative_threshold,
        )
        for k in baseline_metrics
    ]
    drifted = [s for s in signals if s.drifted]
    ticket = None
    if drifted:
        metric = drifted[0].metric
        question = (
            f"Investigate paper-forward drift on {metric} for strategy "
            f"{strategy_id or 'unknown'}@{strategy_version or 'unknown'}: "
            f"baseline={drifted[0].baseline} observed={drifted[0].observed}."
        )
        ticket = ContinualResearchTicket(
            ticket_id=f"drift-{metric}-{_utc_now()}",
            reason="paper_forward_metric_drift",
            signals=drifted,
            research_question=question,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
        )
    return {
        "signals": [s.public_dict() for s in signals],
        "driftCount": len(drifted),
        "continualResearch": ticket.public_dict() if ticket else None,
        "status": "DRIFT_DETECTED" if drifted else "STABLE",
        "truth": {
            "drift_detection_implemented": True,
            "auto_live_promotion_forbidden": True,
            "auto_disable_forbidden_unless_policy": True,
        },
    }


@dataclass(frozen=True)
class ForwardEvidencePolicy:
    """Minimum evidence required before paper-forward can claim PASS/FAIL.

    Five observations or steps alone must never PASS.
    """

    policy_id: str = "forward_evidence_v1"
    version: int = 1
    min_closed_trades: int = 30
    min_observations: int = 100
    min_elapsed_seconds: int = 86400
    min_effective_sample_size: int = 30
    min_regime_coverage: float | None = None
    max_drawdown_drift: float | None = 0.25
    max_execution_gap_bps: float | None = None
    min_feed_health_ratio: float | None = 0.95

    def public_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "min_closed_trades": self.min_closed_trades,
            "min_observations": self.min_observations,
            "min_elapsed_seconds": self.min_elapsed_seconds,
            "min_effective_sample_size": self.min_effective_sample_size,
            "min_regime_coverage": self.min_regime_coverage,
            "max_drawdown_drift": self.max_drawdown_drift,
            "max_execution_gap_bps": self.max_execution_gap_bps,
            "min_feed_health_ratio": self.min_feed_health_ratio,
            "truth": {
                "five_steps_alone_never_pass": True,
                "no_single_sample_auto_disable": True,
            },
        }


def evaluate_forward_evidence(
    *,
    policy: ForwardEvidencePolicy,
    closed_trades: int,
    observations: int,
    elapsed_seconds: float,
    effective_sample_size: float | None = None,
    regime_coverage: float | None = None,
    drawdown_drift: float | None = None,
    execution_gap_bps: float | None = None,
    feed_health_ratio: float | None = None,
) -> dict[str, Any]:
    """Evaluate whether paper-forward evidence is sufficient and within policy.

    Returns state in {PASS, FAIL, INSUFFICIENT_HISTORY, UNMEASURED}.
    """
    blockers: list[str] = []
    history_blockers: list[str] = []

    if int(closed_trades) < int(policy.min_closed_trades):
        history_blockers.append("MIN_CLOSED_TRADES")
    if int(observations) < int(policy.min_observations):
        history_blockers.append("MIN_OBSERVATIONS")
    if float(elapsed_seconds) < float(policy.min_elapsed_seconds):
        history_blockers.append("MIN_ELAPSED_SECONDS")

    ess = effective_sample_size
    if ess is None:
        # Conservative proxy — never invent a large ESS from tiny samples.
        ess = float(min(int(closed_trades), int(observations)))
    if float(ess) < float(policy.min_effective_sample_size):
        history_blockers.append("MIN_EFFECTIVE_SAMPLE_SIZE")

    if history_blockers:
        return {
            "state": "INSUFFICIENT_HISTORY",
            "passed": False,
            "blockers": history_blockers,
            "policy": policy.public_dict(),
            "evidence": {
                "closed_trades": int(closed_trades),
                "observations": int(observations),
                "elapsed_seconds": float(elapsed_seconds),
                "effective_sample_size": float(ess),
                "regime_coverage": regime_coverage,
                "drawdown_drift": drawdown_drift,
                "execution_gap_bps": execution_gap_bps,
                "feed_health_ratio": feed_health_ratio,
            },
            "truth": {
                "five_steps_alone_never_pass": True,
                "no_single_sample_auto_disable": True,
            },
        }

    unmeasured = False
    if policy.min_regime_coverage is not None:
        if regime_coverage is None:
            unmeasured = True
            blockers.append("REGIME_COVERAGE_UNMEASURED")
        elif float(regime_coverage) < float(policy.min_regime_coverage):
            blockers.append("REGIME_COVERAGE_BELOW_MIN")

    if policy.max_drawdown_drift is not None:
        if drawdown_drift is None:
            unmeasured = True
            blockers.append("DRAWDOWN_DRIFT_UNMEASURED")
        elif float(drawdown_drift) > float(policy.max_drawdown_drift):
            blockers.append("DRAWDOWN_DRIFT_EXCEEDED")

    if policy.max_execution_gap_bps is not None:
        if execution_gap_bps is None:
            unmeasured = True
            blockers.append("EXECUTION_GAP_UNMEASURED")
        elif float(execution_gap_bps) > float(policy.max_execution_gap_bps):
            blockers.append("EXECUTION_GAP_EXCEEDED")

    if policy.min_feed_health_ratio is not None:
        if feed_health_ratio is None:
            unmeasured = True
            blockers.append("FEED_HEALTH_UNMEASURED")
        elif float(feed_health_ratio) < float(policy.min_feed_health_ratio):
            blockers.append("FEED_HEALTH_BELOW_MIN")

    if unmeasured and not any(
        b.endswith("_EXCEEDED") or b.endswith("_BELOW_MIN") for b in blockers
    ):
        state = "UNMEASURED"
        passed = False
    elif blockers:
        state = "FAIL"
        passed = False
    else:
        state = "PASS"
        passed = True

    return {
        "state": state,
        "passed": passed,
        "blockers": blockers,
        "policy": policy.public_dict(),
        "evidence": {
            "closed_trades": int(closed_trades),
            "observations": int(observations),
            "elapsed_seconds": float(elapsed_seconds),
            "effective_sample_size": float(ess),
            "regime_coverage": regime_coverage,
            "drawdown_drift": drawdown_drift,
            "execution_gap_bps": execution_gap_bps,
            "feed_health_ratio": feed_health_ratio,
        },
        "truth": {
            "five_steps_alone_never_pass": True,
            "no_single_sample_auto_disable": True,
        },
    }


def classify_drift(
    *,
    closed_trades: int | None = None,
    observations: int | None = None,
    sample_size: int | None = None,
    min_sample_size: int = 5,
    alpha_drifted: bool | None = None,
    execution_gap_bps: float | None = None,
    max_execution_gap_bps: float | None = None,
    drawdown_drift: float | None = None,
    max_drawdown_drift: float | None = None,
    feed_health_ratio: float | None = None,
    min_feed_health_ratio: float | None = None,
    regime_coverage: float | None = None,
    min_regime_coverage: float | None = None,
    signals: list[DriftSignal] | None = None,
) -> dict[str, Any]:
    """Classify drift class from available evidence — never force confidence.

    Classes: ALPHA_DRIFT | EXECUTION_DRIFT | DRAWDOWN_DRIFT | FEED_DRIFT |
    REGIME_DRIFT | STABLE | INSUFFICIENT_EVIDENCE

    Does not auto-disable on a single sample.
    """
    n = sample_size
    if n is None:
        parts = [x for x in (closed_trades, observations) if x is not None]
        n = int(min(parts)) if parts else None
    if n is None or int(n) < int(min_sample_size):
        return {
            "class": "INSUFFICIENT_EVIDENCE",
            "confidence": "NONE",
            "auto_disable": False,
            "reason": "insufficient_sample",
            "sample_size": n,
            "min_sample_size": min_sample_size,
            "truth": {
                "no_single_sample_auto_disable": True,
                "forced_class_forbidden_when_insufficient": True,
            },
        }

    drifted_metrics = [s for s in (signals or []) if s.drifted]
    if alpha_drifted is None and drifted_metrics:
        alpha_drifted = True

    classes: list[str] = []
    if execution_gap_bps is not None and max_execution_gap_bps is not None:
        if float(execution_gap_bps) > float(max_execution_gap_bps):
            classes.append("EXECUTION_DRIFT")
    if drawdown_drift is not None and max_drawdown_drift is not None:
        if float(drawdown_drift) > float(max_drawdown_drift):
            classes.append("DRAWDOWN_DRIFT")
    if feed_health_ratio is not None and min_feed_health_ratio is not None:
        if float(feed_health_ratio) < float(min_feed_health_ratio):
            classes.append("FEED_DRIFT")
    if regime_coverage is not None and min_regime_coverage is not None:
        if float(regime_coverage) < float(min_regime_coverage):
            classes.append("REGIME_DRIFT")
    if alpha_drifted:
        classes.append("ALPHA_DRIFT")

    if not classes:
        return {
            "class": "STABLE",
            "confidence": "MEASURED",
            "auto_disable": False,
            "classes": [],
            "sample_size": int(n),
            "truth": {
                "no_single_sample_auto_disable": True,
                "forced_class_forbidden_when_insufficient": True,
            },
        }

    # Prefer most specific non-alpha class when multiple apply.
    priority = (
        "EXECUTION_DRIFT",
        "FEED_DRIFT",
        "DRAWDOWN_DRIFT",
        "REGIME_DRIFT",
        "ALPHA_DRIFT",
    )
    primary = next((c for c in priority if c in classes), classes[0])
    return {
        "class": primary,
        "classes": classes,
        "confidence": "MEASURED" if int(n) >= int(min_sample_size) * 2 else "LOW",
        "auto_disable": False,
        "sample_size": int(n),
        "drifted_metrics": [s.public_dict() for s in drifted_metrics],
        "truth": {
            "no_single_sample_auto_disable": True,
            "forced_class_forbidden_when_insufficient": True,
        },
    }


def persist_drift_lesson(
    review: dict[str, Any],
    *,
    strategy_memory_writer: Callable[[dict[str, Any]], Any] | None = None,
    research_requester: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Persist drift as PAPER_OBSERVED StrategyMemory + optional research request.

    Does not auto-disable strategies. Does not promote to verified knowledge.
    """
    out: dict[str, Any] = {
        "memoryId": None,
        "researchRequest": None,
        "status": review.get("status"),
    }
    ticket = review.get("continualResearch")
    if not ticket:
        return out
    if strategy_memory_writer is not None:
        try:
            from Data.modules.market_sim.experiments import build_strategy_memory_record

            mem = build_strategy_memory_record(
                strategy_id=str(ticket.get("strategyId") or "unknown"),
                strategy_version=None,
                outcome_summary=(
                    f"PAPER_DRIFT: {ticket.get('reason')} — "
                    f"{ticket.get('researchQuestion') or ''}"
                )[:2000],
                rejected=False,
                available_at=_utc_now(),
                origin="PAPER_FORWARD_DRIFT",
                epistemic_state="PAPER_OBSERVED",
                validation_stage="PAPER_FORWARD",
                extra_metadata={
                    "driftSignals": ticket.get("signals") or [],
                    "ticketId": ticket.get("ticketId"),
                    "strategyVersionLabel": ticket.get("strategyVersion"),
                    "measurement_state": "PAPER_OBSERVED",
                    "does_not_auto_disable": True,
                },
            )
            saved = strategy_memory_writer(mem)
            if isinstance(saved, dict):
                out["memoryId"] = saved.get("memory_id") or saved.get("id")
            else:
                out["memoryId"] = getattr(saved, "memory_id", None)
        except Exception as exc:  # noqa: BLE001 — observable, non-fatal
            out["memoryError"] = str(exc)[:300]
    if research_requester is not None and ticket.get("researchQuestion"):
        try:
            out["researchRequest"] = research_requester(str(ticket["researchQuestion"]))
        except Exception as exc:  # noqa: BLE001
            out["researchError"] = str(exc)[:300]
    return out
