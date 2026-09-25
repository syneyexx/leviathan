"""Cognitive CapabilityState — generate / execute / network / authority matrix.

Distinct from models.contracts.CapabilityState (provider feature probes).
This object answers what the *cognitive run* may do right now.
Discoverable ≠ authorized; model text never grants axes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class AxisState(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    REQUIRES_APPROVAL = "requires_approval"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class CapabilityAxis(str, Enum):
    GENERATE = "generate"
    EXECUTE = "execute"
    NETWORK = "network"
    DELEGATE = "delegate"
    WRITE_FILESYSTEM = "write_filesystem"


@dataclass(frozen=True)
class CapabilityState:
    """First-class cognition capability matrix for a run.

    Axes:
      generate — model/text generation
      execute — tool / capability invocation via ExecutionGateway
      network — outbound network (web research, remote APIs)
      delegate — agent / specialist delegation
      write_filesystem — filesystem mutation side effects
    """

    generate: AxisState = AxisState.UNKNOWN
    execute: AxisState = AxisState.UNKNOWN
    network: AxisState = AxisState.UNKNOWN
    delegate: AxisState = AxisState.UNKNOWN
    write_filesystem: AxisState = AxisState.UNKNOWN
    authority_ceiling: str = "LOW"
    approval_required: bool = False
    reasons: tuple[str, ...] = ()
    source: str = "derived"

    def axis(self, name: CapabilityAxis | str) -> AxisState:
        key = name.value if isinstance(name, CapabilityAxis) else str(name)
        return getattr(self, key, AxisState.UNKNOWN)

    def allows(self, name: CapabilityAxis | str) -> bool:
        return self.axis(name) == AxisState.ALLOWED

    def blocks(self, name: CapabilityAxis | str) -> bool:
        return self.axis(name) in {AxisState.DENIED, AxisState.UNAVAILABLE}

    def public_dict(self) -> dict[str, Any]:
        return {
            "generate": self.generate.value,
            "execute": self.execute.value,
            "network": self.network.value,
            "delegate": self.delegate.value,
            "write_filesystem": self.write_filesystem.value,
            "authority_ceiling": self.authority_ceiling,
            "approval_required": self.approval_required,
            "reasons": list(self.reasons),
            "source": self.source,
            "matrix": {
                "generate": self.generate.value,
                "execute": self.execute.value,
                "network": self.network.value,
                "delegate": self.delegate.value,
                "write_filesystem": self.write_filesystem.value,
            },
            "truth": {
                "capability_state_is_cognition_matrix": True,
                "discoverable_is_not_authorized": True,
                "model_text_cannot_grant_axes": True,
                "not_provider_capability_probe": True,
            },
        }

    @classmethod
    def from_public_dict(cls, raw: Mapping[str, Any] | None) -> "CapabilityState":
        if not isinstance(raw, Mapping):
            return cls()

        def _axis(key: str) -> AxisState:
            try:
                return AxisState(str(raw.get(key) or "unknown").lower())
            except ValueError:
                return AxisState.UNKNOWN

        reasons = raw.get("reasons") or []
        return cls(
            generate=_axis("generate"),
            execute=_axis("execute"),
            network=_axis("network"),
            delegate=_axis("delegate"),
            write_filesystem=_axis("write_filesystem"),
            authority_ceiling=str(raw.get("authority_ceiling") or "LOW"),
            approval_required=bool(raw.get("approval_required")),
            reasons=tuple(str(r) for r in reasons if r)[:24],
            source=str(raw.get("source") or "hydrated"),
        )


def derive_capability_state(
    *,
    task: Any | None = None,
    model_available: bool = False,
    execution_gateway_available: bool = False,
    delegation_enabled: bool = False,
    network_outbound_allowed: bool = False,
    cognition_enabled: bool = True,
    permissions: Mapping[str, Any] | None = None,
) -> CapabilityState:
    """Derive the run CapabilityState from task + runtime affordances.

    Never invents authority from model text. Task.metadata.permissions are a
    soft policy hint; hard denies come from missing gateways / feature flags.
    """
    reasons: list[str] = []
    perms = dict(permissions or {})
    if not perms and task is not None:
        meta = getattr(task, "metadata", None) or {}
        if isinstance(meta, Mapping):
            raw_perms = meta.get("permissions")
            if isinstance(raw_perms, Mapping):
                perms = dict(raw_perms)

    risk = getattr(task, "risk_class", None)
    risk_s = str(getattr(risk, "value", risk) or "LOW").upper()
    approval_required = bool(perms.get("approval_required")) or risk_s in {
        "HIGH",
        "CRITICAL",
    }

    if not cognition_enabled:
        reasons.append("cognition_disabled")
        denied = AxisState.DENIED
        return CapabilityState(
            generate=denied,
            execute=denied,
            network=denied,
            delegate=denied,
            write_filesystem=denied,
            authority_ceiling=risk_s,
            approval_required=True,
            reasons=tuple(reasons),
            source="derived",
        )

    # generate
    if model_available:
        generate = AxisState.ALLOWED
    else:
        generate = AxisState.UNAVAILABLE
        reasons.append("model_caller_unavailable")

    # execute
    if not execution_gateway_available:
        execute = AxisState.UNAVAILABLE
        reasons.append("execution_gateway_unavailable")
    elif approval_required:
        execute = AxisState.REQUIRES_APPROVAL
        reasons.append("execution_requires_approval")
    else:
        execute = AxisState.ALLOWED

    # network
    requires_net = bool(getattr(task, "requires_current_information", False)) or bool(
        getattr(task, "requires_external_information", False)
    )
    if not network_outbound_allowed:
        network = AxisState.DENIED
        if requires_net:
            reasons.append("outbound_network_denied")
    elif approval_required and requires_net:
        network = AxisState.REQUIRES_APPROVAL
        reasons.append("network_requires_approval")
    elif network_outbound_allowed:
        network = AxisState.ALLOWED
    else:
        network = AxisState.DENIED

    # delegate
    if not delegation_enabled:
        delegate = AxisState.DENIED
        reasons.append("delegation_feature_disabled")
    elif approval_required:
        delegate = AxisState.REQUIRES_APPROVAL
    else:
        delegate = AxisState.ALLOWED

    # write_filesystem
    fs_hint = perms.get("filesystem_write")
    if fs_hint is False:
        write_fs = AxisState.DENIED
        reasons.append("filesystem_write_blocked_by_constraints")
    elif not execution_gateway_available:
        write_fs = AxisState.UNAVAILABLE
    elif fs_hint is True or approval_required:
        write_fs = (
            AxisState.REQUIRES_APPROVAL if approval_required else AxisState.ALLOWED
        )
        if write_fs == AxisState.REQUIRES_APPROVAL:
            reasons.append("filesystem_write_requires_approval")
    else:
        # No explicit write intent — keep unavailable until a side-effect task asks.
        write_fs = AxisState.DENIED

    return CapabilityState(
        generate=generate,
        execute=execute,
        network=network,
        delegate=delegate,
        write_filesystem=write_fs,
        authority_ceiling=risk_s,
        approval_required=approval_required,
        reasons=tuple(dict.fromkeys(reasons)),
        source="derived",
    )


def capability_state_from_mapping(raw: Mapping[str, Any] | None) -> CapabilityState:
    return CapabilityState.from_public_dict(raw)
