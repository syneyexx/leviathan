"""Pillar 1 — Machine Self-Model.

Evidence-backed runtime capability snapshot. Reuses host_capability,
capability_intel, sandbox honesty labels, neural status, and node probes.
Never claims verified/operational from import success alone.
"""

from __future__ import annotations

from typing import Any, Callable

from .contracts import AdaptiveDecision, CapabilityEntry, utc_now
from .modes import CognitiveMode


def _entry(**kwargs: Any) -> CapabilityEntry:
    return CapabilityEntry(**kwargs)


def _status_from_flags(
    *,
    implemented: bool,
    available: bool,
    verified: bool = False,
    operationally_tested: bool = False,
    degraded: bool = False,
    unsupported: bool = False,
    unverified_on_host: bool = False,
) -> str:
    if unsupported:
        return "unsupported"
    if degraded:
        return "degraded"
    if operationally_tested:
        return "operationally_tested"
    if verified:
        return "verified"
    if unverified_on_host and implemented:
        return "unverified_on_host"
    if available:
        return "available"
    if implemented:
        return "implemented"
    return "unknown"


def probe_sandbox() -> CapabilityEntry:
    try:
        from gen2.sandbox import detect_host_sandbox_capabilities, sandbox_honesty_labels

        caps = detect_host_sandbox_capabilities()
        honesty = sandbox_honesty_labels(caps)
        job = bool(caps.get("job_objects"))
        implemented = bool(caps.get("job_object_enforcement_implemented") or job)
        operationally_tested = bool(caps.get("operationally_tested"))
        verification = str(caps.get("verification_status") or honesty.get("verification_status") or "")
        unverified = verification in {"UNVERIFIED_ON_HOST", "API_PRESENT_UNTESTED"} or not operationally_tested
        status = _status_from_flags(
            implemented=implemented or True,  # tier 0/1 always implemented in-process
            available=True,
            verified=False,
            operationally_tested=operationally_tested,
            unverified_on_host=unverified,
        )
        # Tier 0/1 are always available; Tier 2 Job Objects need honest labeling.
        notes = list(honesty.get("notes") or caps.get("notes") or [])
        if job and not operationally_tested:
            notes.append("Windows Job Object API present — host execution not operationally_tested")
            status = "unverified_on_host"
        return _entry(
            component="sandbox",
            capability="process_isolation",
            status=status,
            implemented=True,
            available=True,
            verified=operationally_tested,
            operationally_tested=operationally_tested,
            evidence_refs=["gen2.sandbox.detect_host_sandbox_capabilities"],
            details={
                "job_objects": job,
                "verification_status": verification,
                "tiers": caps.get("available_tiers") or caps.get("tiers"),
                "honesty": honesty,
            },
            notes=notes,
        )
    except Exception as exc:
        return _entry(
            component="sandbox",
            capability="process_isolation",
            status="unknown",
            implemented=True,
            available=False,
            notes=[f"probe_failed:{type(exc).__name__}"],
            evidence_refs=["gen2.sandbox"],
        )


def probe_neural(*, neural_status: dict[str, Any] | None = None) -> list[CapabilityEntry]:
    entries: list[CapabilityEntry] = []
    status_payload = neural_status
    if status_payload is None:
        try:
            from reasoning.neural_settings import resolve_neural_settings

            settings = resolve_neural_settings({})
            status_payload = {
                "allow": bool(settings.get("neural_allow")),
                "mode": str(settings.get("neural_mode") or "off"),
                "settings_source": "reasoning.neural_settings",
            }
        except Exception as exc:
            status_payload = {"error": type(exc).__name__, "mode": "off", "allow": False}

    mode = str(status_payload.get("mode") or "off").lower()
    allow = bool(status_payload.get("allow"))
    ready = bool(status_payload.get("ready") or status_payload.get("healthy"))
    implemented = True
    available = allow and mode not in {"off", ""}
    verified = ready and available
    degraded = bool(status_payload.get("degraded") or status_payload.get("oom"))
    status = _status_from_flags(
        implemented=implemented,
        available=available,
        verified=verified,
        operationally_tested=verified,
        degraded=degraded,
        unsupported=False,
    )
    if not allow or mode == "off":
        status = "implemented"  # present but not enabled
    entries.append(
        _entry(
            component="neural",
            capability="associative_memory",
            status=status,
            implemented=True,
            available=available,
            verified=verified,
            operationally_tested=verified,
            degraded=degraded,
            version=str(status_payload.get("checkpoint_id") or status_payload.get("version") or ""),
            evidence_refs=["neural.product_controller", "reasoning.neural_settings"],
            details={
                "mode": mode,
                "allow": allow,
                "ready": ready,
                "limitations": [
                    "Default OFF — never authority for permissions",
                    "LEARN disabled unless explicitly enabled",
                    "Associations are not verified evidence",
                ],
            },
            notes=list(status_payload.get("notes") or []),
        )
    )
    entries.append(
        _entry(
            component="neural",
            capability="streaming",
            status="unsupported" if not available else ("available" if ready else "implemented"),
            implemented=True,
            available=available and ready,
            unsupported=not available,
            evidence_refs=["neural.runtime"],
            notes=["Neural path does not replace Standard streaming chat"],
        )
    )
    return entries


def probe_host() -> list[CapabilityEntry]:
    entries: list[CapabilityEntry] = []
    try:
        from host_capability import check_host_capabilities

        host = check_host_capabilities()
    except Exception as exc:
        return [
            _entry(
                component="host",
                capability="runtime",
                status="unknown",
                notes=[f"probe_failed:{type(exc).__name__}"],
            )
        ]
    checks = host.get("checks") if isinstance(host.get("checks"), dict) else host
    if isinstance(checks, dict):
        for name, payload in checks.items():
            if name in {"cpu", "ram", "gpu", "vram"}:
                continue
            if not isinstance(payload, dict):
                continue
            available = bool(payload.get("available"))
            status = _status_from_flags(
                implemented=True,
                available=available,
                unverified_on_host=available,  # presence != operationally tested
            )
            if not available:
                status = "unsupported" if name in {"docker", "wsl"} else "implemented"
            entries.append(
                _entry(
                    component="host",
                    capability=str(name),
                    status=status,
                    implemented=True,
                    available=available,
                    verified=False,
                    operationally_tested=False,
                    evidence_refs=["host_capability.check_host_capabilities"],
                    details={"detail": payload.get("detail"), "remediation": payload.get("remediation")},
                    notes=[] if available else [str(payload.get("remediation") or "unavailable")],
                )
            )
    # Resource probes — measurable where available, else unknown
    for metric in ("cpu", "ram", "gpu", "vram"):
        value = host.get(metric)
        known = value not in (None, "", "unknown")
        entries.append(
            _entry(
                component="host",
                capability=metric,
                status="available" if known else "unknown",
                implemented=True,
                available=known,
                evidence_refs=["host_capability", "hades_brain.node"],
                details={"value": value if known else "unknown"},
            )
        )
    return entries


def probe_capabilities(*, intel_overview: dict[str, Any] | None = None) -> list[CapabilityEntry]:
    overview = intel_overview
    if overview is None:
        try:
            from capability_intel.service import get_service

            overview = get_service(None).overview()
        except Exception as exc:
            return [
                _entry(
                    component="capability_intel",
                    capability="registry",
                    status="unknown",
                    notes=[f"probe_failed:{type(exc).__name__}"],
                )
            ]
    count = 0
    if isinstance(overview, dict):
        caps = overview.get("capabilities") or overview.get("items") or overview.get("registry")
        if isinstance(caps, list):
            count = len(caps)
        elif isinstance(caps, dict):
            count = len(caps)
        elif isinstance(overview.get("counts"), dict):
            count = int(overview["counts"].get("capabilities") or 0)
    return [
        _entry(
            component="capability_intel",
            capability="canonical_registry",
            status="available" if count >= 0 else "unknown",
            implemented=True,
            available=True,
            verified=False,
            evidence_refs=["capability_intel.registry"],
            details={"capability_count": count, "overview_keys": sorted(overview.keys()) if isinstance(overview, dict) else []},
        )
    ]


def probe_providers(*, provider_health: dict[str, Any] | None = None) -> list[CapabilityEntry]:
    entries: list[CapabilityEntry] = []
    # LM Studio / local provider — availability from health if provided
    if provider_health is None:
        provider_health = {}
    lm = provider_health.get("lm_studio") if isinstance(provider_health, dict) else None
    if isinstance(lm, dict):
        available = bool(lm.get("available") or lm.get("ok") or lm.get("reachable"))
        entries.append(
            _entry(
                component="provider",
                capability="lm_studio",
                status=_status_from_flags(implemented=True, available=available, unverified_on_host=not available),
                implemented=True,
                available=available,
                evidence_refs=["lm_studio", "model_discovery"],
                details=lm,
                last_failure=str(lm.get("error") or "") or None,
            )
        )
    else:
        entries.append(
            _entry(
                component="provider",
                capability="lm_studio",
                status="unknown",
                implemented=True,
                available=False,
                evidence_refs=["lm_studio"],
                notes=["Provider health not probed in this snapshot"],
            )
        )
    return entries


def build_self_model(
    *,
    extras: dict[str, Any] | None = None,
    neural_status: dict[str, Any] | None = None,
    intel_overview: dict[str, Any] | None = None,
    provider_health: dict[str, Any] | None = None,
    models: list[str] | None = None,
    agents: list[str] | None = None,
    tools: list[str] | None = None,
) -> dict[str, Any]:
    """Produce one coherent evidence-backed runtime capability snapshot."""
    extras = extras or {}
    capabilities: list[CapabilityEntry] = []
    capabilities.extend(probe_host())
    capabilities.append(probe_sandbox())
    capabilities.extend(probe_neural(neural_status=neural_status or extras.get("neural_status")))
    capabilities.extend(probe_capabilities(intel_overview=intel_overview or extras.get("intel_overview")))
    capabilities.extend(probe_providers(provider_health=provider_health or extras.get("provider_health")))

    # Streaming: Standard chat streaming is implemented; do not pretend Neural streaming.
    capabilities.append(
        _entry(
            component="chat",
            capability="streaming",
            status="implemented",
            implemented=True,
            available=True,
            verified=False,
            operationally_tested=False,
            evidence_refs=["lm_studio.chat_stream", "reasoning.model_chat_dispatch"],
            notes=["Standard streaming path; Neural OFF preserves this path"],
        )
    )

    node: dict[str, Any] = {}
    try:
        from hades_brain.node import advertise_local_node

        node = advertise_local_node(
            extras={
                "models": models or extras.get("models") or [],
                "plugins": extras.get("plugins") or [],
                "mcp_providers": extras.get("mcp_providers") or [],
            }
        )
    except Exception as exc:
        node = {"error": type(exc).__name__}

    by_status: dict[str, int] = {}
    for cap in capabilities:
        by_status[cap.status] = by_status.get(cap.status, 0) + 1

    snapshot = {
        "schema_version": 1,
        "controller": "cognitive.self_model",
        "version": "cognitive.v1",
        "generated_at": utc_now(),
        "node": node,
        "models": list(models or extras.get("models") or []),
        "agents": list(agents or extras.get("agents") or []),
        "tools": list(tools or extras.get("tools") or []),
        "capabilities": [c.to_dict() for c in capabilities],
        "counts_by_status": by_status,
        "routing_hints": routing_hints_from_capabilities(capabilities),
        "decision": AdaptiveDecision(
            controller="cognitive.self_model",
            decision="snapshot",
            reason_code="EVIDENCE_BACKED_PROBE",
            mode=CognitiveMode.ACTIVE.value,
            confidence=1.0,
        ).to_dict(),
    }
    return snapshot


def routing_hints_from_capabilities(capabilities: list[CapabilityEntry]) -> dict[str, Any]:
    """Derive conservative routing constraints from the self-model."""
    hints: dict[str, Any] = {
        "prefer_neural": False,
        "streaming_available": True,
        "sandbox_tier2_safe": False,
        "block_reasons": [],
    }
    for cap in capabilities:
        if cap.component == "neural" and cap.capability == "associative_memory":
            hints["prefer_neural"] = bool(cap.available and cap.verified and not cap.degraded)
            if not cap.available:
                hints["block_reasons"].append("neural_unavailable")
            if cap.degraded:
                hints["block_reasons"].append("neural_degraded")
        if cap.component == "chat" and cap.capability == "streaming":
            hints["streaming_available"] = bool(cap.available or cap.implemented)
        if cap.component == "sandbox" and cap.capability == "process_isolation":
            hints["sandbox_tier2_safe"] = bool(cap.operationally_tested)
            if cap.status == "unverified_on_host":
                hints["block_reasons"].append("sandbox_tier2_unverified_on_host")
        if cap.component == "provider" and cap.capability == "lm_studio" and not cap.available:
            if cap.status == "unknown":
                hints["block_reasons"].append("provider_health_unknown")
            else:
                hints["block_reasons"].append("lm_studio_unavailable")
    return hints


def capability_allows(snapshot: dict[str, Any], *, component: str, capability: str) -> bool:
    for raw in snapshot.get("capabilities") or []:
        if not isinstance(raw, dict):
            continue
        if raw.get("component") == component and raw.get("capability") == capability:
            if raw.get("degraded") or raw.get("unsupported"):
                return False
            return bool(raw.get("available") or raw.get("operationally_tested") or raw.get("verified"))
    return False
