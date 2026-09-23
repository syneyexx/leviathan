"""Consumer truth reports for Settings diagnostics.

Desired vs effective vs live consumer wiring — never claim success from flags alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConsumerTruthReport:
    """Truthful posture for one capability/feature consumer."""

    feature_key: str
    desired: Any
    effective: Any
    consumer: str
    consumer_active: bool
    capability_available: bool
    degraded_reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def aligned(self) -> bool:
        return self.desired == self.effective and not self.degraded_reason

    @property
    def degraded(self) -> bool:
        return bool(self.degraded_reason) or (
            bool(self.desired) is True and bool(self.effective) is False
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "feature_key": self.feature_key,
            "desired": self.desired,
            "effective": self.effective,
            "consumer": self.consumer,
            "consumer_active": self.consumer_active,
            "capability_available": self.capability_available,
            "degraded_reason": self.degraded_reason,
            "aligned": self.aligned,
            "degraded": self.degraded,
            "detail": dict(self.detail),
            "notes": list(self.notes),
            "truth": {
                "desired_is_not_effective": True,
                "flag_on_is_not_capability": True,
                "unavailable_is_not_success": True,
                "consumer_inactive_is_not_operational": True,
            },
        }


def build_consumer_truth(
    *,
    feature_key: str,
    desired: Any,
    effective: Any,
    consumer: str,
    consumer_active: bool,
    capability_available: bool,
    degraded_reason: str | None = None,
    detail: dict[str, Any] | None = None,
    notes: tuple[str, ...] | list[str] | None = None,
) -> ConsumerTruthReport:
    """Build a desired/effective consumer report for Settings diagnostics."""
    reason = degraded_reason
    if reason is None:
        if bool(desired) and not bool(effective):
            if not capability_available:
                reason = "capability_unavailable"
            elif not consumer_active:
                reason = "consumer_inactive"
            else:
                reason = "desired_not_effective"
    return ConsumerTruthReport(
        feature_key=feature_key,
        desired=desired,
        effective=effective,
        consumer=consumer,
        consumer_active=bool(consumer_active),
        capability_available=bool(capability_available),
        degraded_reason=reason,
        detail=dict(detail or {}),
        notes=tuple(notes or ()),
    )


def feature_section_from_report(report: ConsumerTruthReport) -> dict[str, Any]:
    """Flatten a ConsumerTruthReport into a health-payload section dict."""
    payload = report.public_dict()
    return {
        "desired": payload["desired"],
        "effective": payload["effective"],
        "consumer": payload["consumer"],
        "consumer_active": payload["consumer_active"],
        "capability_available": payload["capability_available"],
        "degraded_reason": payload["degraded_reason"],
        "aligned": payload["aligned"],
        "degraded": payload["degraded"],
        "detail": payload["detail"],
        "notes": payload["notes"],
        "truth": payload["truth"],
    }
