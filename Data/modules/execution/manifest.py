"""Frontier Capability Manifest — machine-readable availability from real probes (U016).

UI and APIs must derive availability from this manifest rather than duplicate truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from .catalog import CapabilityCatalog
from .types import CapabilityDefinition


class ManifestAvailability(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"
    UNMEASURED = "UNMEASURED"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ManifestEntry:
    capability_id: str
    name: str
    provider_kind: str
    availability: ManifestAvailability
    reason: str | None = None
    enabled: bool = True
    side_effects: tuple[str, ...] = ()
    schema_hash: str | None = None
    measured: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "provider_kind": self.provider_kind,
            "availability": self.availability.value,
            "reason": self.reason,
            "enabled": self.enabled,
            "side_effects": list(self.side_effects),
            "schema_hash": self.schema_hash,
            "measured": self.measured,
            "truth": {
                "discoverable_is_not_authorized": True,
                "unmeasured_is_not_passed": True,
            },
        }


@dataclass
class FrontierCapabilityManifest:
    """Snapshot of executable capability availability at a point in time."""

    generated_at: str
    schema_version: int = 1
    entries: list[ManifestEntry] = field(default_factory=list)
    source: str = "CapabilityCatalog"
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.availability.value] = counts.get(entry.availability.value, 0) + 1
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "source": self.source,
            "counts": counts,
            "entries": [item.public_dict() for item in self.entries],
            "metadata": self.metadata,
            "truth": {
                "manifest_is_not_authorization": True,
                "ui_must_not_duplicate_capability_truth": True,
            },
        }


def _availability_for(defn: CapabilityDefinition) -> tuple[ManifestAvailability, str | None]:
    if not defn.enabled:
        return ManifestAvailability.DISABLED, defn.availability_reason or "capability disabled"
    if not defn.available:
        return ManifestAvailability.UNAVAILABLE, defn.availability_reason or "unavailable"
    if defn.availability_reason:
        return ManifestAvailability.DEGRADED, defn.availability_reason
    return ManifestAvailability.READY, None


def build_frontier_manifest(
    catalog: CapabilityCatalog,
    *,
    measured_ids: Iterable[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> FrontierCapabilityManifest:
    measured = {str(item) for item in (measured_ids or ())}
    entries: list[ManifestEntry] = []
    for defn in catalog.list():
        availability, reason = _availability_for(defn)
        if defn.id not in measured and availability == ManifestAvailability.READY:
            # Without an empirical probe, READY decays to UNMEASURED for truthfulness.
            # Built-in/function capabilities are treated as measured by registration.
            if defn.provider_kind.value in {"external", "mcp", "module", "native"}:
                availability = ManifestAvailability.UNMEASURED
                reason = reason or "no recent capability probe"
        entries.append(
            ManifestEntry(
                capability_id=defn.id,
                name=defn.name,
                provider_kind=defn.provider_kind.value,
                availability=availability,
                reason=reason,
                enabled=defn.enabled,
                side_effects=tuple(e.value for e in defn.side_effects),
                schema_hash=defn.schema_hash,
                measured=defn.id in measured
                or defn.provider_kind.value in {"function", "knowledge", "artifact", "internal", "builtin"},
            )
        )
    return FrontierCapabilityManifest(
        generated_at=_utc_now(),
        entries=entries,
        metadata=dict(metadata or {}),
    )
