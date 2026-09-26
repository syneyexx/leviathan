"""Paper-forward drift detection and continual research hook (W24)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


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

    def public_dict(self) -> dict[str, Any]:
        return {
            "ticketId": self.ticket_id,
            "reason": self.reason,
            "signals": [s.public_dict() for s in self.signals],
            "status": self.status,
            "truth": {"does_not_auto_promote": True, "live_trading_blocked": True},
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
) -> dict[str, Any]:
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
        ticket = ContinualResearchTicket(
            ticket_id=f"drift-{drifted[0].metric}",
            reason="paper_forward_metric_drift",
            signals=drifted,
        )
    return {
        "signals": [s.public_dict() for s in signals],
        "driftCount": len(drifted),
        "continualResearch": ticket.public_dict() if ticket else None,
        "truth": {
            "drift_detection_implemented": True,
            "auto_live_promotion_forbidden": True,
        },
    }
