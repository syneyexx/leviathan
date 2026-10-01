"""Effective capability resolution — single truth for routing + UI.

Precedence (strongest → weakest):
  1. Operator override / configured (provenance operator_configured)
  2. Recent verified probe result (SUPPORTED or UNSUPPORTED)
  3. Authoritative provider/runtime report
  4. Declared model metadata
  5. Bounded family inference
  6. UNKNOWN

Verified UNSUPPORTED always beats name heuristics / inferred SUPPORTED.
Inferred capability may never be stronger than verified truth.
Stale probes are recognizable and do not silently win forever.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from Data.modules.models.capability_vocabulary import (
    CANONICAL_CAPABILITIES,
    capability_attr,
    normalize_capability_name,
)
from Data.modules.models.contracts import (
    CapabilityState,
    ModelCapabilities,
    ModelDescriptor,
    VerifiedCapability,
)


# Default max age for a verified probe to remain routing-authoritative.
DEFAULT_PROBE_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days


class EffectiveProvenance(str, Enum):
    OPERATOR_OVERRIDE = "operator_override"
    VERIFIED_PROBE = "verified_probe"
    VERIFIED_PROBE_STALE = "verified_probe_stale"
    PROVIDER_REPORTED = "provider_reported"
    DECLARED_METADATA = "declared_metadata"
    FAMILY_INFERENCE = "family_inference"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EffectiveCapability:
    capability: str  # canonical camelCase
    state: CapabilityState
    provenance: EffectiveProvenance
    declared: CapabilityState
    verified: CapabilityState | None = None
    last_tested_at: str | None = None
    detail: str | None = None
    stale: bool = False
    fingerprint: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "state": self.state.value,
            "provenance": self.provenance.value,
            "declared": self.declared.value,
            "verified": self.verified.value if self.verified is not None else None,
            "lastTestedAt": self.last_tested_at,
            "detail": self.detail,
            "stale": self.stale,
            "fingerprint": self.fingerprint,
        }


def _parse_ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (TypeError, ValueError):
        return None


def _is_stale(
    last_tested_at: str | None,
    *,
    max_age_seconds: float,
    now: float | None = None,
) -> bool:
    ts = _parse_ts(last_tested_at)
    if ts is None:
        return True
    return (now if now is not None else time.time()) - ts > max_age_seconds


def _operator_overrides(model: ModelDescriptor) -> dict[str, CapabilityState]:
    meta = dict(model.metadata or {})
    raw = meta.get("capabilityOverrides") or meta.get("capability_overrides") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, CapabilityState] = {}
    for key, value in raw.items():
        canonical = normalize_capability_name(str(key))
        if canonical is None:
            continue
        try:
            out[canonical] = CapabilityState(str(value))
        except ValueError:
            continue
    return out


def _fingerprint_mismatch(model: ModelDescriptor, stored_fp: str | None) -> bool:
    """Invalidate verification when provider version / model revision changed."""
    if not stored_fp:
        return False
    meta = dict(model.metadata or {})
    current = (
        meta.get("capabilityFingerprint")
        or meta.get("provider_version")
        or meta.get("model_revision")
        or model.quantization
    )
    if current is None:
        return False
    return str(current) != str(stored_fp)


def resolve_effective_capability(
    model: ModelDescriptor,
    capability: str,
    *,
    verified: VerifiedCapability | None = None,
    max_age_seconds: float = DEFAULT_PROBE_MAX_AGE_SECONDS,
    now: float | None = None,
) -> EffectiveCapability:
    """Resolve one capability with explicit precedence + provenance."""
    canonical = normalize_capability_name(capability)
    if canonical is None:
        return EffectiveCapability(
            capability=str(capability),
            state=CapabilityState.UNSUPPORTED,
            provenance=EffectiveProvenance.UNKNOWN,
            declared=CapabilityState.UNKNOWN,
            detail="unsupported_or_unknown_capability_alias",
        )

    attr = capability_attr(canonical)
    declared_raw = getattr(model.capabilities, attr, CapabilityState.UNKNOWN)
    if not isinstance(declared_raw, CapabilityState):
        try:
            declared_raw = CapabilityState(str(declared_raw))
        except ValueError:
            declared_raw = CapabilityState.UNKNOWN

    overrides = _operator_overrides(model)
    if canonical in overrides:
        return EffectiveCapability(
            capability=canonical,
            state=overrides[canonical],
            provenance=EffectiveProvenance.OPERATOR_OVERRIDE,
            declared=declared_raw,
            verified=verified.verified if verified else None,
            last_tested_at=verified.last_tested_at if verified else None,
            detail="operator_capability_override",
        )

    if verified is not None and verified.verified in {
        CapabilityState.SUPPORTED,
        CapabilityState.UNSUPPORTED,
    }:
        stale = _is_stale(verified.last_tested_at, max_age_seconds=max_age_seconds, now=now)
        fp = None
        detail = verified.detail
        meta = dict(model.metadata or {})
        fp = meta.get("lastProbeFingerprint")
        if isinstance(verified.detail, str) and verified.detail.startswith("fp:"):
            fp = verified.detail.split(":", 1)[1].split(";", 1)[0] or fp
        if _fingerprint_mismatch(model, str(fp) if fp else None):
            stale = True
            detail = f"fingerprint_mismatch:{detail or ''}"
        if not stale:
            return EffectiveCapability(
                capability=canonical,
                state=verified.verified,
                provenance=EffectiveProvenance.VERIFIED_PROBE,
                declared=declared_raw,
                verified=verified.verified,
                last_tested_at=verified.last_tested_at,
                detail=detail,
                stale=False,
                fingerprint=str(fp) if fp else None,
            )
        # Stale verified: keep visible but do not let heuristics override UNSUPPORTED.
        if verified.verified == CapabilityState.UNSUPPORTED:
            return EffectiveCapability(
                capability=canonical,
                state=CapabilityState.UNSUPPORTED,
                provenance=EffectiveProvenance.VERIFIED_PROBE_STALE,
                declared=declared_raw,
                verified=verified.verified,
                last_tested_at=verified.last_tested_at,
                detail=detail or "stale_verified_unsupported",
                stale=True,
                fingerprint=str(fp) if fp else None,
            )
        # Stale SUPPORTED falls through to declared/inference (do not claim verified).
        # Continue below with declared.

    # Declared provider/runtime states (not family inference).
    if declared_raw in {CapabilityState.SUPPORTED, CapabilityState.UNSUPPORTED}:
        return EffectiveCapability(
            capability=canonical,
            state=declared_raw,
            provenance=EffectiveProvenance.PROVIDER_REPORTED,
            declared=declared_raw,
            verified=verified.verified if verified else None,
            last_tested_at=verified.last_tested_at if verified else None,
            detail="declared_provider_state",
        )

    if declared_raw in {
        CapabilityState.UNVERIFIED,
        CapabilityState.UNMEASURED,
        CapabilityState.UNKNOWN,
    }:
        return EffectiveCapability(
            capability=canonical,
            state=declared_raw,
            provenance=EffectiveProvenance.DECLARED_METADATA,
            declared=declared_raw,
            verified=verified.verified if verified else None,
            last_tested_at=verified.last_tested_at if verified else None,
            detail="declared_unresolved",
        )

    return EffectiveCapability(
        capability=canonical,
        state=CapabilityState.UNKNOWN,
        provenance=EffectiveProvenance.UNKNOWN,
        declared=declared_raw,
        detail="unresolved",
    )


def apply_effective_to_capabilities(
    model: ModelDescriptor,
    *,
    verified_by_cap: dict[str, VerifiedCapability] | None = None,
    max_age_seconds: float = DEFAULT_PROBE_MAX_AGE_SECONDS,
    now: float | None = None,
) -> tuple[ModelCapabilities, dict[str, EffectiveCapability]]:
    """Build ModelCapabilities from effective decisions for every canonical cap."""
    verified_by_cap = verified_by_cap or {}
    decisions: dict[str, EffectiveCapability] = {}
    caps = model.capabilities
    updates: dict[str, CapabilityState] = {}
    for name in CANONICAL_CAPABILITIES:
        v = verified_by_cap.get(name)
        if v is None:
            # Also accept snake_case keys from storage.
            attr = capability_attr(name)
            v = verified_by_cap.get(attr)
        eff = resolve_effective_capability(
            model,
            name,
            verified=v,
            max_age_seconds=max_age_seconds,
            now=now,
        )
        decisions[name] = eff
        updates[capability_attr(name)] = eff.state
    return replace(caps, **updates), decisions


def load_verified_map(
    model_id: str,
    list_fn: Callable[[str], list[VerifiedCapability]],
) -> dict[str, VerifiedCapability]:
    """Index verified rows by canonical capability name."""
    out: dict[str, VerifiedCapability] = {}
    for row in list_fn(model_id):
        canonical = normalize_capability_name(row.capability)
        if canonical is None:
            continue
        out[canonical] = row
    return out


def enrich_with_effective_capabilities(
    model: ModelDescriptor,
    *,
    verified_by_cap: dict[str, VerifiedCapability] | None = None,
    max_age_seconds: float = DEFAULT_PROBE_MAX_AGE_SECONDS,
) -> ModelDescriptor:
    """Return descriptor whose capabilities reflect effective (routing) truth."""
    caps, decisions = apply_effective_to_capabilities(
        model,
        verified_by_cap=verified_by_cap,
        max_age_seconds=max_age_seconds,
    )
    meta = dict(model.metadata or {})
    meta["effectiveCapabilities"] = {
        name: d.public_dict() for name, d in decisions.items()
    }
    payload = {k: v for k, v in model.__dict__.items()}
    payload["capabilities"] = caps
    payload["metadata"] = meta
    return ModelDescriptor(**payload)  # type: ignore[arg-type]
