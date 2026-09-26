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
