"""Signal Router — direct / role / capability / orchestrator / mission / system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .types import (
    SIGNAL_NO_RECIPIENT,
    RecipientType,
    RoutingMode,
    SignalType,
)


class SignalRouterError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _AgentLike(Protocol):
    agent_id: str
    name: str
    kind: Any
    role: str
    capabilities: list[str]
    enabled: bool
    archived: bool
    health: Any
    max_concurrency: int
    orchestrator: Any
    metadata: dict[str, Any]


class _FleetLike(Protocol):
    def list_agents(self, *, include_archived: bool = False, kind: str | None = None) -> list[Any]: ...
    def get_agent(self, agent_id: str) -> Any: ...
    def get_mission(self, mission_id: str) -> Any: ...


@dataclass(frozen=True)
class ResolvedRecipient:
    recipient_type: RecipientType
    recipient_id: str
    resolved_agent_id: str | None
    routing_mode: RoutingMode
    reason: str = ""


class SignalRouter:
    """Deterministic recipient resolution. No LLM for routing."""

    def __init__(self, fleet: _FleetLike | None = None) -> None:
        self.fleet = fleet

    def bind_fleet(self, fleet: _FleetLike) -> None:
        self.fleet = fleet

    def resolve(
        self,
        *,
        recipient_type: RecipientType,
        recipient_id: str,
        signal_type: SignalType | None = None,
        mission_id: str | None = None,
        sender_id: str | None = None,
    ) -> list[ResolvedRecipient]:
        if recipient_type == RecipientType.AGENT:
            return self._direct(recipient_id)
        if recipient_type == RecipientType.ORCHESTRATOR:
            return self._orchestrator(recipient_id, mission_id=mission_id, sender_id=sender_id)
        if recipient_type == RecipientType.ROLE:
            return self._role(recipient_id)
        if recipient_type == RecipientType.CAPABILITY:
            return self._capability(recipient_id)
        if recipient_type == RecipientType.MISSION:
            return self._mission(recipient_id or mission_id)
        if recipient_type == RecipientType.SYSTEM:
            return [
                ResolvedRecipient(
                    recipient_type=RecipientType.SYSTEM,
                    recipient_id=recipient_id or "system",
                    resolved_agent_id=None,
                    routing_mode=RoutingMode.SYSTEM,
                    reason="system consumer",
                )
            ]
        if recipient_type == RecipientType.WORKER:
            # Only controlled parent-worker: resolve to parent agent id in recipient_id.
            return [
                ResolvedRecipient(
                    recipient_type=RecipientType.WORKER,
                    recipient_id=recipient_id,
                    resolved_agent_id=None,
                    routing_mode=RoutingMode.DIRECT,
                    reason="controlled worker recipient (parent-bound)",
                )
            ]
        raise SignalRouterError(SIGNAL_NO_RECIPIENT, f"Unsupported recipient type {recipient_type}")

    def _agents(self) -> list[_AgentLike]:
        if self.fleet is None:
            return []
        return list(self.fleet.list_agents(include_archived=False))

    def _eligible(self, agent: _AgentLike) -> bool:
        if agent.archived or not agent.enabled:
            return False
        health = getattr(agent.health, "value", agent.health)
        if str(health) in {"error", "archived", "disabled"}:
            return False
        return True

    def _capacity_score(self, agent: _AgentLike) -> int:
        # Prefer agents with higher remaining concurrency (we don't always have load;
        # max_concurrency acts as a stable capacity proxy; lower id breaks ties).
        return int(getattr(agent, "max_concurrency", 1) or 1)

    def _pick_best(self, candidates: list[_AgentLike], *, capability: str | None = None) -> _AgentLike | None:
        eligible = [a for a in candidates if self._eligible(a)]
        if not eligible:
            return None
        if capability:
            exact = [a for a in eligible if capability in (a.capabilities or [])]
            if exact:
                eligible = exact
            else:
                # Prefix / substring match as secondary — only among agents that have capabilities.
                soft = [
                    a
                    for a in eligible
                    if (a.capabilities or [])
                    and any(capability in c or c in capability for c in (a.capabilities or []))
                ]
                if soft:
                    eligible = soft
                else:
                    return None

        def sort_key(a: _AgentLike) -> tuple:
            health = str(getattr(a.health, "value", a.health) or "unknown")
            healthy = 0 if health in {"idle", "busy", "unknown"} else 1
            return (
                healthy,
                0 if a.enabled else 1,
                -self._capacity_score(a),
                a.agent_id,  # stable deterministic tie-break
            )

        eligible.sort(key=sort_key)
        return eligible[0]

    def _direct(self, agent_id: str) -> list[ResolvedRecipient]:
        if self.fleet is not None:
            try:
                agent = self.fleet.get_agent(agent_id)
            except Exception:  # noqa: BLE001
                agent = None
            if agent is not None and not self._eligible(agent):
                raise SignalRouterError(
                    SIGNAL_NO_RECIPIENT,
                    f"Agent {agent_id} is not eligible (disabled/archived/unhealthy)",
                )
        return [
            ResolvedRecipient(
                recipient_type=RecipientType.AGENT,
                recipient_id=agent_id,
                resolved_agent_id=agent_id,
                routing_mode=RoutingMode.DIRECT,
                reason="direct",
            )
        ]

    def _role(self, role: str) -> list[ResolvedRecipient]:
        role_l = role.lower().strip()
        candidates = [
            a
            for a in self._agents()
            if (a.role or "").lower() == role_l
            or role_l in (a.role or "").lower()
            or role_l in [t.lower() for t in getattr(a, "tags", []) or []]
        ]
        pick = self._pick_best(candidates)
        if pick is None:
            raise SignalRouterError(SIGNAL_NO_RECIPIENT, f"No eligible agent for role={role}")
        return [
            ResolvedRecipient(
                recipient_type=RecipientType.ROLE,
                recipient_id=role,
                resolved_agent_id=pick.agent_id,
                routing_mode=RoutingMode.ROLE,
                reason=f"role={role} -> {pick.agent_id}",
            )
        ]

    def _capability(self, capability: str) -> list[ResolvedRecipient]:
        candidates = list(self._agents())
        pick = self._pick_best(candidates, capability=capability)
        if pick is None:
            raise SignalRouterError(
                SIGNAL_NO_RECIPIENT,
                f"No eligible agent for capability={capability}",
            )
        return [
            ResolvedRecipient(
                recipient_type=RecipientType.CAPABILITY,
                recipient_id=capability,
                resolved_agent_id=pick.agent_id,
                routing_mode=RoutingMode.CAPABILITY,
                reason=f"capability={capability} -> {pick.agent_id}",
            )
        ]

    def _orchestrator(
        self,
        recipient_id: str,
        *,
        mission_id: str | None,
        sender_id: str | None,
    ) -> list[ResolvedRecipient]:
        # Prefer explicit orchestrator id; else parent mission agent if orchestrator; else first orch.
        if recipient_id and recipient_id not in {"orchestrator", "parent", "*"}:
            return [
                ResolvedRecipient(
                    recipient_type=RecipientType.ORCHESTRATOR,
                    recipient_id=recipient_id,
                    resolved_agent_id=recipient_id,
                    routing_mode=RoutingMode.ORCHESTRATOR,
                    reason="explicit orchestrator",
                )
            ]
        if self.fleet is not None and mission_id:
            try:
                mission = self.fleet.get_mission(mission_id) if hasattr(self.fleet, "get_mission") else None
                if mission is None and hasattr(self.fleet, "store"):
                    mission = self.fleet.store.get_mission(mission_id)
                if mission is not None:
                    parent_id = getattr(mission, "parent_mission_id", None)
                    agent_id = getattr(mission, "agent_id", None)
                    # Climb to parent mission's agent when requesting parent orchestrator.
                    if parent_id:
                        parent = self.fleet.store.get_mission(parent_id)
                        if parent:
                            return [
                                ResolvedRecipient(
                                    recipient_type=RecipientType.ORCHESTRATOR,
                                    recipient_id=parent.agent_id,
                                    resolved_agent_id=parent.agent_id,
                                    routing_mode=RoutingMode.ORCHESTRATOR,
                                    reason="parent mission orchestrator",
                                )
                            ]
                    if agent_id:
                        agent = self.fleet.get_agent(agent_id)
                        kind = str(getattr(agent.kind, "value", agent.kind))
                        if kind == "orchestrator":
                            return [
                                ResolvedRecipient(
                                    recipient_type=RecipientType.ORCHESTRATOR,
                                    recipient_id=agent_id,
                                    resolved_agent_id=agent_id,
                                    routing_mode=RoutingMode.ORCHESTRATOR,
                                    reason="mission owning orchestrator",
                                )
                            ]
            except Exception:  # noqa: BLE001
                pass
        orch = [
            a
            for a in self._agents()
            if str(getattr(a.kind, "value", a.kind)).lower() == "orchestrator"
        ]
        pick = self._pick_best(orch)
        if pick is None:
            raise SignalRouterError(SIGNAL_NO_RECIPIENT, "No eligible orchestrator")
        return [
            ResolvedRecipient(
                recipient_type=RecipientType.ORCHESTRATOR,
                recipient_id=pick.agent_id,
                resolved_agent_id=pick.agent_id,
                routing_mode=RoutingMode.ORCHESTRATOR,
                reason="default orchestrator",
            )
        ]

    def _mission(self, mission_id: str | None) -> list[ResolvedRecipient]:
        if not mission_id or self.fleet is None:
            raise SignalRouterError(SIGNAL_NO_RECIPIENT, "mission_id required for MISSION routing")
        store = getattr(self.fleet, "store", None)
        if store is None:
            raise SignalRouterError(SIGNAL_NO_RECIPIENT, "fleet store unavailable")
        mission = store.get_mission(mission_id)
        if mission is None:
            raise SignalRouterError(SIGNAL_NO_RECIPIENT, f"Mission {mission_id} not found")
        # Mission-scoped: owning agent + sibling children owners (bounded).
        recipients: list[ResolvedRecipient] = [
            ResolvedRecipient(
                recipient_type=RecipientType.MISSION,
                recipient_id=mission_id,
                resolved_agent_id=mission.agent_id,
                routing_mode=RoutingMode.MISSION,
                reason="mission owner",
            )
        ]
        children = store.list_missions(limit=50)
        for child in children:
            if getattr(child, "parent_mission_id", None) == mission_id:
                recipients.append(
                    ResolvedRecipient(
                        recipient_type=RecipientType.MISSION,
                        recipient_id=mission_id,
                        resolved_agent_id=child.agent_id,
                        routing_mode=RoutingMode.MISSION,
                        reason=f"mission child {child.mission_id}",
                    )
                )
        # Deduplicate by resolved agent.
        seen: set[str] = set()
        unique: list[ResolvedRecipient] = []
        for r in recipients:
            key = r.resolved_agent_id or r.recipient_id
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)
        return unique
