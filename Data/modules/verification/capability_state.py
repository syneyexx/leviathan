"""System capability self-knowledge (W6).

Honest snapshot of what LEVIATHAN can do *now*. Missing measurements stay
UNMEASURED — never invent brain percentages or fake availability.

Named SystemCapabilityState to avoid colliding with models.CapabilityState
(provider feature support enum). Public docs call this capability self-knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


UNMEASURED = "UNMEASURED"
AVAILABLE = "AVAILABLE"
UNAVAILABLE = "UNAVAILABLE"
NOT_CONFIGURED = "NOT_CONFIGURED"
FEATURE_GATED = "FEATURE_GATED"
DEGRADED = "DEGRADED"


def _status_field(value: Any, *, status: str, reason: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": status, "value": value}
    if reason:
        out["reason"] = reason
    return out


@dataclass
class SystemCapabilityState:
    """Point-in-time capability self-knowledge for Cognition / Chat honesty."""

    available_capabilities: list[str] = field(default_factory=list)
    model_capabilities: dict[str, Any] = field(default_factory=dict)
    worker_health: dict[str, Any] = field(default_factory=dict)
    web_availability: str = UNMEASURED
    browser_availability: str = UNMEASURED
    network_authority: str = UNMEASURED
    gpu_resource_state: dict[str, Any] = field(default_factory=dict)
    behavior_version: str | None = None
    feature_flags: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "available_capabilities": list(self.available_capabilities),
            "model_capabilities": dict(self.model_capabilities),
            "worker_health": dict(self.worker_health),
            "web_availability": self.web_availability,
            "browser_availability": self.browser_availability,
            "network_authority": self.network_authority,
            "gpu_resource_state": dict(self.gpu_resource_state),
            "behavior_version": self.behavior_version,
            "feature_flags": dict(self.feature_flags),
            "notes": list(self.notes),
            "brain_percentage": _status_field(
                None,
                status=UNMEASURED,
                reason="brain_percentage_is_not_a_supported_metric",
            ),
            "truth": {
                "unmeasured_is_not_available": True,
                "not_configured_is_not_broken": True,
                "never_invents_brain_percentage": True,
                "same_model_critique_is_not_independent_verification": True,
            },
        }


def build_system_capability_state(
    *,
    capability_ids: list[str] | None = None,
    model_capabilities: dict[str, Any] | None = None,
    worker_health: dict[str, Any] | None = None,
    web_configured: bool | None = None,
    web_reachable: bool | None = None,
    browser_ready: bool | None = None,
    browser_configured: bool | None = None,
    network_allow_outbound: bool | None = None,
    gpu_snapshot: dict[str, Any] | None = None,
    behavior_version: str | None = None,
    feature_flags: dict[str, Any] | None = None,
) -> SystemCapabilityState:
    notes: list[str] = []

    if web_configured is False:
        web = NOT_CONFIGURED
    elif web_reachable is True:
        web = AVAILABLE
    elif web_reachable is False:
        web = UNAVAILABLE
    elif web_configured is True:
        web = UNMEASURED
        notes.append("web configured but reachability UNMEASURED")
    else:
        web = UNMEASURED

    if browser_configured is False:
        browser = NOT_CONFIGURED
    elif browser_ready is True:
        browser = AVAILABLE
    elif browser_ready is False and browser_configured is True:
        browser = UNAVAILABLE
    elif browser_configured is True:
        browser = FEATURE_GATED
        notes.append("browser package may be present but readiness unproven")
    else:
        browser = UNMEASURED

    if network_allow_outbound is True:
        network = AVAILABLE
    elif network_allow_outbound is False:
        network = "BLOCKED"
    else:
        network = UNMEASURED

    gpu = dict(gpu_snapshot or {})
    if not gpu:
        gpu = {"status": UNMEASURED, "reason": "gpu_telemetry_unavailable"}

    workers = dict(worker_health or {})
    if not workers:
        workers = {"status": UNMEASURED, "reason": "worker_health_unavailable"}

    return SystemCapabilityState(
        available_capabilities=list(capability_ids or []),
        model_capabilities=dict(model_capabilities or {"status": UNMEASURED}),
        worker_health=workers,
        web_availability=web,
        browser_availability=browser,
        network_authority=network,
        gpu_resource_state=gpu,
        behavior_version=behavior_version,
        feature_flags=dict(feature_flags or {}),
        notes=notes,
    )
