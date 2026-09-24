"""Canonical SERVER-SIDE inventory of LEVIATHAN system intelligence/runtime components.

Architecture descriptors are read-only views of real composition — they are NOT
AgentDefinition database rows. Fleet-backed SYSTEM agents (Research, Coding, …)
remain in AgentFleetStore and are classified via metadata.systemKey.

Status probes must never invent healthy/idle values when status cannot be known.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


StatusProvider = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class SystemInventorySpec:
    """Static descriptor for a real LEVIATHAN runtime component."""

    system_key: str
    name: str
    entity_type: str  # orchestrator | architecture
    runtime_kind: str
    description: str
    source_module: str
    capabilities: tuple[str, ...] = ()
    # Declared relationships to other system_keys (not inferred from imports).
    relationship_keys: tuple[tuple[str, str], ...] = ()  # (relation, target_system_key)
    executable: bool = False


# Only components that are actually constructed in Data/backend/main.py and used
# as part of the intelligence/execution architecture. Filename ≠ membership.
_ARCHITECTURE_SPECS: tuple[SystemInventorySpec, ...] = (
    SystemInventorySpec(
        system_key="execution_gateway",
        name="Execution Gateway",
        entity_type="architecture",
        runtime_kind="execution",
        description="Sole side-effect authority for capability invocations.",
        source_module="Data.modules.execution",
        capabilities=("capability.invoke", "approval.gated_side_effects"),
    ),
    SystemInventorySpec(
        system_key="agent_runtime",
        name="Agent Runtime",
        entity_type="architecture",
        runtime_kind="agent_runtime",
        description="Strategy layer that plans and executes fleet missions via the gateway.",
        source_module="Data.modules.agents.runtime",
        capabilities=("mission.execute", "plan.structured"),
        relationship_keys=(("uses", "execution_gateway"), ("uses", "structured_agent_planner")),
    ),
    SystemInventorySpec(
        system_key="structured_agent_planner",
        name="Structured Agent Planner",
        entity_type="architecture",
        runtime_kind="planner",
        description="Kind-aware mission planner used by AgentRuntime (not Cognition).",
        source_module="Data.modules.agents.planner",
        capabilities=("plan.kind_aware",),
    ),
    SystemInventorySpec(
        system_key="agent_fleet_service",
        name="Agent Fleet Service",
        entity_type="architecture",
        runtime_kind="control_plane",
        description="Durable definitions, missions, and orchestrator membership control plane.",
        source_module="Data.modules.agents.fleet",
        capabilities=("definitions.crud", "missions.launch", "orchestrator.delegate"),
        relationship_keys=(("uses", "agent_runtime"),),
    ),
    SystemInventorySpec(
        system_key="multi_agent_coordinator",
        name="Multi-Agent Coordinator",
        entity_type="orchestrator",
        runtime_kind="multi_agent",
        description="DAG coordinator over a shared AgentRuntime (POST /api/agents/multi).",
        source_module="Data.modules.agents.multi",
        capabilities=("dag.execute", "blackboard.scoped"),
        relationship_keys=(("uses", "agent_runtime"),),
        executable=False,
    ),
    SystemInventorySpec(
        system_key="cognitive_runtime",
        name="Cognitive Runtime",
        entity_type="orchestrator",
        runtime_kind="cognition",
        description="Chat cognition path: meta-controller, planner, broker, and delegation.",
        source_module="Data.modules.cognition.runtime",
        capabilities=("cognition.run", "delegation", "belief"),
        relationship_keys=(
            ("uses", "meta_controller"),
            ("uses", "capability_broker"),
            ("uses", "delegation_service"),
            ("uses", "execution_gateway"),
            ("uses", "model_control_plane"),
        ),
    ),
    SystemInventorySpec(
        system_key="meta_controller",
        name="Meta Controller",
        entity_type="architecture",
        runtime_kind="cognition",
        description="Strategy/mode decisions inside CognitiveRuntime.",
        source_module="Data.modules.cognition.meta_controller",
        capabilities=("strategy.select",),
    ),
    SystemInventorySpec(
        system_key="capability_broker",
        name="Capability Broker",
        entity_type="architecture",
        runtime_kind="cognition",
        description="Shortlists capabilities from the shared capability catalog.",
        source_module="Data.modules.cognition.capability_broker",
        capabilities=("capability.shortlist",),
    ),
    SystemInventorySpec(
        system_key="delegation_service",
        name="Delegation Service",
        entity_type="architecture",
        runtime_kind="cognition",
        description="Routes cognition specialist work to coding and research handlers.",
        source_module="Data.modules.cognition.delegation",
        capabilities=("delegate.coding", "delegate.research"),
        relationship_keys=(("uses", "coding_control_plane"), ("uses", "research_service")),
    ),
    SystemInventorySpec(
        system_key="research_service",
        name="Research Service",
        entity_type="orchestrator",
        runtime_kind="research",
        description="Owns research projects/runs via ResearchRunner and ResearchCoordinator.",
        source_module="Data.modules.research.service",
        capabilities=("research.plan", "research.run"),
    ),
    SystemInventorySpec(
        system_key="coding_control_plane",
        name="Coding Control Plane",
        entity_type="architecture",
        runtime_kind="coding",
        description="Domain coding runtime bound onto AgentRuntime and cognition specialists.",
        source_module="Data.modules.coding",
        capabilities=("coding.execute", "coding.verify"),
        relationship_keys=(("uses", "execution_gateway"),),
    ),
    SystemInventorySpec(
        system_key="residual_orchestrator",
        name="Residual Orchestrator",
        entity_type="orchestrator",
        runtime_kind="neuro",
        description="Neuro residual-layer orchestration on the chat path when flags allow.",
        source_module="Data.modules.neuro",
        capabilities=("residual.orchestrate",),
    ),
    SystemInventorySpec(
        system_key="cortex_runtime",
        name="Cortex Runtime",
        entity_type="architecture",
        runtime_kind="neuro",
        description="Neuro cortex runtime used by NeuroAdvisor when cortex is enabled.",
        source_module="Data.modules.neuro",
        capabilities=("cortex.plan",),
    ),
    SystemInventorySpec(
        system_key="neuro_advisor",
        name="Neuro Advisor",
        entity_type="architecture",
        runtime_kind="neuro",
        description="Advisory neuro stack (memory tiers, critic, residual injection).",
        source_module="Data.modules.neuro",
        capabilities=("neuro.advise",),
        relationship_keys=(("uses", "cortex_runtime"), ("uses", "residual_orchestrator")),
    ),
    SystemInventorySpec(
        system_key="model_control_plane",
        name="Model Control Plane",
        entity_type="architecture",
        runtime_kind="models",
        description="Authoritative model registry, routing, gateway, and serving control.",
        source_module="Data.modules.models.control_plane",
        capabilities=("models.registry", "models.route", "models.serve", "models.gateway"),
    ),
    SystemInventorySpec(
        system_key="master_gate_runner",
        name="Master Gate Runner",
        entity_type="architecture",
        runtime_kind="master",
        description="Release/security/evaluation/neuro posture gates for operator readiness.",
        source_module="Data.modules.master",
        capabilities=("gates.evaluate",),
    ),
)


def architecture_id(system_key: str) -> str:
    spec = next((s for s in _ARCHITECTURE_SPECS if s.system_key == system_key), None)
    kind = spec.entity_type if spec else "architecture"
    return f"system:{kind}:{system_key}"


@dataclass
class SystemInventoryEntry:
    id: str
    name: str
    origin: str
    entity_type: str
    system_key: str
    runtime_kind: str
    description: str
    status: str
    enabled: bool | None
    mutable: bool
    source_module: str
    capabilities: list[str] = field(default_factory=list)
    relationships: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    executable: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "origin": self.origin,
            "entityType": self.entity_type,
            "systemKey": self.system_key,
            "runtimeKind": self.runtime_kind,
            "description": self.description,
            "status": self.status,
            "enabled": self.enabled,
            "mutable": self.mutable,
            "sourceModule": self.source_module,
            "capabilities": list(self.capabilities),
            "relationships": list(self.relationships),
            "metadata": dict(self.metadata),
            "executable": self.executable,
            "truth": {
                "not_an_agent_definition": True,
                "status_from_runtime_probe": True,
            },
        }


class SystemInventory:
    """Live catalog of architecture/orchestrator components wired at process start."""

    def __init__(self) -> None:
        self._providers: dict[str, StatusProvider] = {}

    def register_status_provider(self, system_key: str, provider: StatusProvider) -> None:
        key = str(system_key or "").strip()
        if not key:
            raise ValueError("system_key is required")
        self._providers[key] = provider

    def specs(self) -> tuple[SystemInventorySpec, ...]:
        return _ARCHITECTURE_SPECS

    def list_entries(self) -> list[SystemInventoryEntry]:
        by_key = {s.system_key: s for s in _ARCHITECTURE_SPECS}
        entries: list[SystemInventoryEntry] = []
        for spec in _ARCHITECTURE_SPECS:
            probe = self._probe(spec.system_key)
            status = str(probe.get("status") or "unknown")
            enabled = probe.get("enabled")
            if enabled is not None:
                enabled = bool(enabled)
            relationships: list[dict[str, str]] = []
            for relation, target_key in spec.relationship_keys:
                if target_key not in by_key:
                    continue
                relationships.append(
                    {
                        "relation": relation,
                        "targetId": architecture_id(target_key),
                        "targetSystemKey": target_key,
                    }
                )
            meta = dict(probe.get("metadata") or {})
            if probe.get("detail"):
                meta["detail"] = probe["detail"]
            entries.append(
                SystemInventoryEntry(
                    id=architecture_id(spec.system_key),
                    name=spec.name,
                    origin="system",
                    entity_type=spec.entity_type,
                    system_key=spec.system_key,
                    runtime_kind=spec.runtime_kind,
                    description=spec.description,
                    status=status,
                    enabled=enabled,
                    mutable=False,
                    source_module=spec.source_module,
                    capabilities=list(spec.capabilities),
                    relationships=relationships,
                    metadata=meta,
                    executable=bool(spec.executable),
                )
            )
        return entries

    def _probe(self, system_key: str) -> dict[str, Any]:
        provider = self._providers.get(system_key)
        if provider is None:
            return {"status": "unknown", "enabled": None, "detail": "no status provider registered"}
        try:
            result = provider() or {}
        except Exception as exc:  # noqa: BLE001 — probe failure must not invent health
            return {
                "status": "error",
                "enabled": None,
                "detail": f"status probe failed: {exc}",
            }
        status = str(result.get("status") or "unknown").strip().lower() or "unknown"
        # Never coerce missing status into idle/ready.
        allowed = {
            "unknown",
            "ready",
            "degraded",
            "offline",
            "disabled",
            "busy",
            "idle",
            "error",
        }
        if status not in allowed:
            status = "unknown"
        return {
            "status": status,
            "enabled": result.get("enabled"),
            "detail": result.get("detail"),
            "metadata": dict(result.get("metadata") or {}),
        }


def classify_fleet_agent(agent: Any) -> dict[str, Any]:
    """Derive first-class origin/entityType/systemKey/mutable from a fleet AgentDefinition."""
    metadata = dict(getattr(agent, "metadata", None) or {})
    system_key = str(metadata.get("systemKey") or "").strip() or None
    kind = getattr(agent, "kind", None)
    kind_value = getattr(kind, "value", kind)
    if str(kind_value) == "orchestrator":
        entity_type = "orchestrator"
    else:
        entity_type = "agent"
    origin = "system" if system_key else "user"
    # System fleet agents keep configurable operational fields, but identity is protected.
    mutable = origin == "user"
    return {
        "origin": origin,
        "entityType": entity_type,
        "systemKey": system_key,
        "mutable": mutable,
    }
