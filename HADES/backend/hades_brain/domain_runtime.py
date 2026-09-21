"""Small common domain runtime boundary. Internals stay specialized."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class DomainRuntime(Protocol):
    domain_id: str

    def describe_capabilities(self) -> dict[str, Any]: ...
    def accept_mission(self, mission: dict[str, Any]) -> dict[str, Any]: ...
    def status(self, handle: str) -> dict[str, Any]: ...
    def pause(self, handle: str) -> dict[str, Any]: ...
    def cancel(self, handle: str) -> dict[str, Any]: ...
    def resume(self, handle: str) -> dict[str, Any]: ...
    def artifacts(self, handle: str) -> list[dict[str, Any]]: ...
    def evidence(self, handle: str) -> list[dict[str, Any]]: ...
    def verification(self, handle: str) -> dict[str, Any]: ...


@dataclass(slots=True)
class DomainDescriptor:
    domain_id: str
    specialized: list[str]
    shared_brain: list[str]
    duplicate_brain_behavior: list[str]
    adapter_required: bool
    migration_risk: str
    parity_proof: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "specialized": list(self.specialized),
            "shared_brain": list(self.shared_brain),
            "duplicate_brain_behavior": list(self.duplicate_brain_behavior),
            "adapter_required": self.adapter_required,
            "migration_risk": self.migration_risk,
            "parity_proof": self.parity_proof,
            "notes": list(self.notes),
        }


MIGRATION_MATRIX: dict[str, DomainDescriptor] = {
    "chat": DomainDescriptor(
        domain_id="chat",
        specialized=["conversation persistence", "streaming UI", "voice"],
        shared_brain=["capability_intel.observe", "model_router", "context compiler", "usage telemetry"],
        duplicate_brain_behavior=[],
        adapter_required=False,
        migration_risk="low",
        parity_proof="capability_intel + chat retrieval tests",
    ),
    "work": DomainDescriptor(
        domain_id="work",
        specialized=["TaskRunner DAG", "checkpoints", "completion gate"],
        shared_brain=["capability_intel.work_bridge", "MissionState"],
        duplicate_brain_behavior=["planner LLM skipped when composition exists"],
        adapter_required=False,
        migration_risk="low",
        parity_proof="work_bridge + work completion tests",
    ),
    "coding": DomainDescriptor(
        domain_id="coding",
        specialized=["worktrees", "patch apply", "tests", "language tooling", "leases"],
        shared_brain=["AgentContract", "verification_result", "model_router"],
        duplicate_brain_behavior=["coding_agent identity vs CanonicalAgent — adapter only"],
        adapter_required=True,
        migration_risk="medium",
        parity_proof="coding job tests remain source of truth",
        notes=["Do not genericize isolated worktrees."],
    ),
    "trading": DomainDescriptor(
        domain_id="trading",
        specialized=["clock", "exchange simulator", "ledger", "risk", "evaluation stats"],
        shared_brain=["CanonicalAgent projection of lab roles", "mission refs"],
        duplicate_brain_behavior=["lab AgentRole is a domain role, not a second protocol"],
        adapter_required=True,
        migration_risk="low",
        parity_proof="trading_lab contracts; deterministic engines untouched",
        notes=["Never let a model decide fills or risk vetoes."],
    ),
    "media": DomainDescriptor(
        domain_id="media",
        specialized=["FFmpeg", "asset processing", "platform publishing"],
        shared_brain=["capability registry", "trust/secrets"],
        duplicate_brain_behavior=["MediaCapabilityDoctor is host readiness, not routing"],
        adapter_required=True,
        migration_risk="low",
        parity_proof="media intelligence tests",
    ),
    "research": DomainDescriptor(
        domain_id="research",
        specialized=["crawl/fetch", "extraction", "citations"],
        shared_brain=["knowledge retrieval", "evidence refs"],
        duplicate_brain_behavior=[],
        adapter_required=True,
        migration_risk="low",
        parity_proof="research/knowledge tests",
    ),
    "plugins": DomainDescriptor(
        domain_id="plugins",
        specialized=["PluginManager invoke", "trust ladder", "healthchecks"],
        shared_brain=["capability_intel normalization"],
        duplicate_brain_behavior=[],
        adapter_required=False,
        migration_risk="low",
        parity_proof="plugin runtime contract tests",
    ),
    "mcp": DomainDescriptor(
        domain_id="mcp",
        specialized=["MCP protocol host", "OAuth", "secrets", "sessions"],
        shared_brain=["mcp_provider + tool normalization"],
        duplicate_brain_behavior=[],
        adapter_required=False,
        migration_risk="low",
        parity_proof="mcp_host tests; MCPMarket does not duplicate protocol",
    ),
}


class StaticDomainRuntime:
    """Descriptor-backed runtime used when a domain engine is not injected."""

    def __init__(self, domain_id: str, *, capabilities: dict[str, Any] | None = None) -> None:
        self.domain_id = domain_id
        self._capabilities = capabilities or {"domain": domain_id, "injected": False}
        self._missions: dict[str, dict[str, Any]] = {}

    def describe_capabilities(self) -> dict[str, Any]:
        descriptor = MIGRATION_MATRIX.get(self.domain_id)
        payload = dict(self._capabilities)
        if descriptor:
            payload["migration"] = descriptor.to_dict()
        return payload

    def accept_mission(self, mission: dict[str, Any]) -> dict[str, Any]:
        handle = str(mission.get("handle") or mission.get("mission_id") or f"{self.domain_id}:accepted")
        record = {"handle": handle, "status": "accepted", "mission": dict(mission), "domain": self.domain_id}
        self._missions[handle] = record
        return record

    def status(self, handle: str) -> dict[str, Any]:
        return dict(self._missions.get(handle) or {"handle": handle, "status": "unknown", "domain": self.domain_id})

    def pause(self, handle: str) -> dict[str, Any]:
        return self._set(handle, "paused")

    def cancel(self, handle: str) -> dict[str, Any]:
        return self._set(handle, "cancelled")

    def resume(self, handle: str) -> dict[str, Any]:
        return self._set(handle, "active")

    def artifacts(self, handle: str) -> list[dict[str, Any]]:
        mission = self._missions.get(handle) or {}
        return list((mission.get("mission") or {}).get("artifacts") or [])

    def evidence(self, handle: str) -> list[dict[str, Any]]:
        mission = self._missions.get(handle) or {}
        return list((mission.get("mission") or {}).get("evidence") or [])

    def verification(self, handle: str) -> dict[str, Any]:
        mission = self._missions.get(handle) or {}
        return dict((mission.get("mission") or {}).get("verification") or {"status": "unknown"})

    def _set(self, handle: str, status: str) -> dict[str, Any]:
        current = self.status(handle)
        current["status"] = status
        self._missions[handle] = current
        return current


def default_runtimes() -> dict[str, StaticDomainRuntime]:
    return {key: StaticDomainRuntime(key) for key in MIGRATION_MATRIX}


def migration_matrix() -> dict[str, dict[str, Any]]:
    return {key: item.to_dict() for key, item in MIGRATION_MATRIX.items()}
