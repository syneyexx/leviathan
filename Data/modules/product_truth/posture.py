"""Product Truth — evidence-based status vocabulary (Round 9).

Never report ``operational`` merely because a module imported.
Status must derive from measured evidence, feature flags, and backend kind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable


class ProductStatus(str, Enum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    EXPERIMENTAL = "experimental"
    FIXTURE = "fixture"
    UNAVAILABLE = "unavailable"
    UNCONFIGURED = "unconfigured"
    UNMEASURED = "unmeasured"


# Legacy aliases that UIs historically emitted — map them honestly.
_LEGACY_STATUS_MAP: dict[str, ProductStatus] = {
    "healthy": ProductStatus.OPERATIONAL,
    "ok": ProductStatus.OPERATIONAL,
    "ready": ProductStatus.OPERATIONAL,
    "degraded": ProductStatus.DEGRADED,
    "belast": ProductStatus.DEGRADED,
    "warning": ProductStatus.DEGRADED,
    "failed": ProductStatus.UNAVAILABLE,
    "error": ProductStatus.UNAVAILABLE,
    "offline": ProductStatus.UNAVAILABLE,
    "stopped": ProductStatus.UNAVAILABLE,
    "unavailable": ProductStatus.UNAVAILABLE,
    "unknown": ProductStatus.UNMEASURED,
    "fixture": ProductStatus.FIXTURE,
    "experimental": ProductStatus.EXPERIMENTAL,
    "unconfigured": ProductStatus.UNCONFIGURED,
    "unmeasured": ProductStatus.UNMEASURED,
}


def normalize_status(raw: str | ProductStatus | None) -> ProductStatus:
    if isinstance(raw, ProductStatus):
        return raw
    if raw is None or not str(raw).strip():
        return ProductStatus.UNMEASURED
    key = str(raw).strip().lower()
    return _LEGACY_STATUS_MAP.get(key, ProductStatus.UNMEASURED)


@dataclass
class ComponentPosture:
    id: str
    name: str
    type: str
    status: ProductStatus
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    measured: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            # Keep legacy ``status`` field for the Performance page, but use
            # the Round 9 vocabulary (not ``healthy`` from import success).
            "status": self.status.value,
            "detail": self.detail,
            "evidence": dict(self.evidence),
            "measured": self.measured,
            "truth": {
                "import_success_is_not_operational": True,
                "status_derives_from_evidence": True,
                "unmeasured_is_not_operational": self.status != ProductStatus.OPERATIONAL
                or self.measured,
            },
        }


@dataclass
class ProductTruthReport:
    components: list[ComponentPosture]
    overall: ProductStatus
    notes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "components": [c.public_dict() for c in self.components],
            "overall": self.overall.value,
            "notes": list(self.notes),
            "vocabulary": [s.value for s in ProductStatus],
            "truth": {
                "import_success_is_not_operational": True,
                "status_derives_from_evidence": True,
                "no_meaningless_confidence": True,
                "fixture_is_not_production": True,
                "unmeasured_is_not_pass": True,
            },
        }


def _overall(components: Iterable[ComponentPosture]) -> ProductStatus:
    statuses = {c.status for c in components}
    if not statuses:
        return ProductStatus.UNMEASURED
    if ProductStatus.UNAVAILABLE in statuses and all(
        s in {ProductStatus.UNAVAILABLE, ProductStatus.UNCONFIGURED, ProductStatus.UNMEASURED}
        for s in statuses
    ):
        return ProductStatus.UNAVAILABLE
    if ProductStatus.DEGRADED in statuses or ProductStatus.UNAVAILABLE in statuses:
        return ProductStatus.DEGRADED
    if ProductStatus.FIXTURE in statuses or ProductStatus.EXPERIMENTAL in statuses:
        return ProductStatus.EXPERIMENTAL
    if ProductStatus.UNMEASURED in statuses or ProductStatus.UNCONFIGURED in statuses:
        return ProductStatus.UNMEASURED
    return ProductStatus.OPERATIONAL


def assess_product_truth(
    *,
    backend_alive: bool,
    observability_durable: bool,
    jobs_queued: int | None = None,
    module_manager_enabled: bool = False,
    module_count: int = 0,
    mcp_feature_enabled: bool = False,
    mcp_server_count: int | None = None,
    mcp_connected_count: int | None = None,
    telemetry_partial: bool | None = None,
    browser_backend_kind: str | None = None,
    browser_production_capable: bool | None = None,
    model_gateway_health: str | None = None,
    model_provider_count: int | None = None,
    embedding_available: bool | None = None,
    agents_enabled: bool = False,
    training_fixture_default: bool = False,
) -> ProductTruthReport:
    """Build evidence-based postures for operator/product surfaces."""
    components: list[ComponentPosture] = []

    components.append(
        ComponentPosture(
            id="backend",
            name="backend",
            type="Core",
            status=ProductStatus.OPERATIONAL if backend_alive else ProductStatus.UNAVAILABLE,
            detail="process up" if backend_alive else "process down",
            evidence={"alive": backend_alive},
            measured=True,
        )
    )

    components.append(
        ComponentPosture(
            id="observability",
            name="observability",
            type="Runtime",
            status=(
                ProductStatus.OPERATIONAL
                if observability_durable
                else ProductStatus.DEGRADED
            ),
            detail="durable" if observability_durable else "ring_buffer_only",
            evidence={"durable_store": observability_durable},
            measured=True,
        )
    )

    if jobs_queued is None:
        components.append(
            ComponentPosture(
                id="job_runtime",
                name="job-runtime",
                type="Runtime",
                status=ProductStatus.UNMEASURED,
                detail="queue depth not sampled",
                evidence={},
                measured=False,
            )
        )
    else:
        components.append(
            ComponentPosture(
                id="job_runtime",
                name="job-runtime",
                type="Runtime",
                status=ProductStatus.OPERATIONAL,
                detail=f"queued={jobs_queued}",
                evidence={"queued": jobs_queued},
                measured=True,
            )
        )

    components.append(
        ComponentPosture(
            id="module_manager",
            name="module-manager",
            type="Runtime",
            status=(
                ProductStatus.OPERATIONAL
                if module_manager_enabled
                else ProductStatus.UNAVAILABLE
            ),
            detail=f"modules={module_count}",
            evidence={"enabled": module_manager_enabled, "modules": module_count},
            measured=True,
        )
    )

    if not mcp_feature_enabled:
        components.append(
            ComponentPosture(
                id="mcp_bridge",
                name="mcp-bridge",
                type="Bridge",
                status=ProductStatus.UNCONFIGURED,
                detail="feature_disabled",
                evidence={"feature_enabled": False},
                measured=True,
            )
        )
    elif mcp_server_count is None:
        components.append(
            ComponentPosture(
                id="mcp_bridge",
                name="mcp-bridge",
                type="Bridge",
                status=ProductStatus.UNMEASURED,
                detail="server list unavailable",
                evidence={"feature_enabled": True},
                measured=False,
            )
        )
    elif mcp_server_count == 0:
        # No servers configured ≠ healthy bridge — unconfigured.
        components.append(
            ComponentPosture(
                id="mcp_bridge",
                name="mcp-bridge",
                type="Bridge",
                status=ProductStatus.UNCONFIGURED,
                detail="no_servers_configured",
                evidence={"servers": 0, "connected": 0},
                measured=True,
            )
        )
    else:
        connected = int(mcp_connected_count or 0)
        if connected >= mcp_server_count:
            status = ProductStatus.OPERATIONAL
            detail = f"servers={mcp_server_count} connected={connected}"
        elif connected > 0:
            status = ProductStatus.DEGRADED
            detail = f"servers={mcp_server_count} connected={connected}"
        else:
            status = ProductStatus.UNAVAILABLE
            detail = f"servers={mcp_server_count} connected=0"
        components.append(
            ComponentPosture(
                id="mcp_bridge",
                name="mcp-bridge",
                type="Bridge",
                status=status,
                detail=detail,
                evidence={"servers": mcp_server_count, "connected": connected},
                measured=True,
            )
        )

    if telemetry_partial is None:
        components.append(
            ComponentPosture(
                id="system_telemetry",
                name="system-telemetry",
                type="Sampler",
                status=ProductStatus.UNMEASURED,
                detail="sampler not queried",
                evidence={},
                measured=False,
            )
        )
    elif telemetry_partial:
        components.append(
            ComponentPosture(
                id="system_telemetry",
                name="system-telemetry",
                type="Sampler",
                status=ProductStatus.DEGRADED,
                detail="partial_unavailable",
                evidence={"cpu_or_ram_missing": True},
                measured=True,
            )
        )
    else:
        components.append(
            ComponentPosture(
                id="system_telemetry",
                name="system-telemetry",
                type="Sampler",
                status=ProductStatus.OPERATIONAL,
                detail="sampling",
                evidence={"cpu_or_ram_missing": False},
                measured=True,
            )
        )

    # Browser — fixture must never read as operational.
    kind = (browser_backend_kind or "").lower()
    if not kind:
        components.append(
            ComponentPosture(
                id="browser",
                name="browser",
                type="Multimodal",
                status=ProductStatus.UNCONFIGURED,
                detail="backend_kind unset",
                evidence={},
                measured=False,
            )
        )
    elif kind == "fixture":
        components.append(
            ComponentPosture(
                id="browser",
                name="browser",
                type="Multimodal",
                status=ProductStatus.FIXTURE,
                detail="fixture_is_not_chromium",
                evidence={
                    "backend_kind": kind,
                    "production_capable": False,
                },
                measured=True,
            )
        )
    elif browser_production_capable is False:
        components.append(
            ComponentPosture(
                id="browser",
                name="browser",
                type="Multimodal",
                status=ProductStatus.UNAVAILABLE,
                detail=f"backend={kind} not production capable",
                evidence={"backend_kind": kind, "production_capable": False},
                measured=True,
            )
        )
    elif kind in {"local_dom", "playwright"}:
        components.append(
            ComponentPosture(
                id="browser",
                name="browser",
                type="Multimodal",
                status=ProductStatus.OPERATIONAL
                if browser_production_capable is not False
                else ProductStatus.UNAVAILABLE,
                detail=f"backend={kind}",
                evidence={
                    "backend_kind": kind,
                    "production_capable": browser_production_capable,
                },
                measured=browser_production_capable is not None,
            )
        )
    else:
        components.append(
            ComponentPosture(
                id="browser",
                name="browser",
                type="Multimodal",
                status=ProductStatus.UNMEASURED,
                detail=f"unknown backend={kind}",
                evidence={"backend_kind": kind},
                measured=False,
            )
        )

    # Models gateway
    gw = normalize_status(model_gateway_health)
    if model_provider_count == 0:
        gw = ProductStatus.UNCONFIGURED
        detail = "no_providers"
        measured = True
    elif model_gateway_health is None:
        gw = ProductStatus.UNMEASURED
        detail = "gateway health not sampled"
        measured = False
    else:
        detail = f"gateway={model_gateway_health}"
        measured = True
        if gw == ProductStatus.OPERATIONAL and not model_provider_count:
            gw = ProductStatus.UNCONFIGURED
    components.append(
        ComponentPosture(
            id="models",
            name="models",
            type="Runtime",
            status=gw,
            detail=detail,
            evidence={
                "gateway_health_raw": model_gateway_health,
                "provider_count": model_provider_count,
            },
            measured=measured,
        )
    )

    if embedding_available is None:
        emb_status = ProductStatus.UNMEASURED
        emb_detail = "embedding availability not sampled"
        emb_measured = False
    elif embedding_available:
        emb_status = ProductStatus.OPERATIONAL
        emb_detail = "embedding provider available"
        emb_measured = True
    else:
        emb_status = ProductStatus.UNAVAILABLE
        emb_detail = "embedding provider unavailable"
        emb_measured = True
    components.append(
        ComponentPosture(
            id="embeddings",
            name="embeddings",
            type="Knowledge",
            status=emb_status,
            detail=emb_detail,
            evidence={"available": embedding_available},
            measured=emb_measured,
        )
    )

    components.append(
        ComponentPosture(
            id="agents",
            name="agents",
            type="Runtime",
            status=(
                ProductStatus.OPERATIONAL
                if agents_enabled
                else ProductStatus.UNCONFIGURED
            ),
            detail="feature_enabled" if agents_enabled else "feature_disabled",
            evidence={"enabled": agents_enabled},
            measured=True,
        )
    )

    if training_fixture_default:
        components.append(
            ComponentPosture(
                id="training",
                name="training",
                type="Training",
                status=ProductStatus.FIXTURE,
                detail="default method is fixture — not production training proof",
                evidence={"default_method": "fixture"},
                measured=True,
            )
        )

    notes = (
        "Status vocabulary: operational|degraded|experimental|fixture|unavailable|unconfigured|unmeasured",
        "Import/feature-flag alone never implies operational without evidence",
    )
    return ProductTruthReport(
        components=components,
        overall=_overall(components),
        notes=notes,
    )


def confidence_is_meaningless(value: float | int | None, *, evidence: Any = None) -> bool:
    """True when a confidence percentage has no supporting evidence."""
    if value is None:
        return True
    if evidence is None:
        return True
    if isinstance(evidence, (list, tuple, dict, set)) and len(evidence) == 0:
        return True
    return False
