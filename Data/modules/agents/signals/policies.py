"""Signal Fabric authorization policy — capability/kind based, not hard-coded role names."""

from __future__ import annotations

from typing import Any, Protocol

from .types import (
    SIGNAL_UNAUTHORIZED,
    SIGNAL_WORKER_MESH_FORBIDDEN,
    RecipientType,
    SenderType,
    SignalType,
)


class SignalPolicyError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 403) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def public_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


class _AgentLike(Protocol):
    agent_id: str
    kind: Any
    role: str
    capabilities: list[str]
    enabled: bool
    archived: bool
    metadata: dict[str, Any]


# Default allow-lists keyed by agent kind value (lowercase).
# Orchestrators and operators get broader control; research/coding get domain emits.
_KIND_EMIT_ALLOW: dict[str, frozenset[SignalType]] = {
    "research": frozenset(
        {
            SignalType.FINDING,
            SignalType.EVIDENCE,
            SignalType.HYPOTHESIS,
            SignalType.QUESTION,
            SignalType.ANSWER,
            SignalType.KNOWLEDGE_CANDIDATE,
            SignalType.MEMORY_CANDIDATE,
            SignalType.PROGRESS,
            SignalType.WARNING,
            SignalType.ERROR,
            SignalType.ARTIFACT_READY,
            SignalType.COMPLETED,
            SignalType.HEARTBEAT,
            SignalType.CHALLENGE,
        }
    ),
    "coding": frozenset(
        {
            SignalType.TASK_HANDOFF,
            SignalType.ARTIFACT_READY,
            SignalType.VERIFY_REQUEST,
            SignalType.QUESTION,
            SignalType.ANSWER,
            SignalType.RESOURCE_REQUEST,
            SignalType.PROGRESS,
            SignalType.WARNING,
            SignalType.ERROR,
            SignalType.FINDING,
            SignalType.COMPLETED,
            SignalType.HEARTBEAT,
        }
    ),
    "trading": frozenset(
        {
            SignalType.FINDING,
            SignalType.HYPOTHESIS,
            SignalType.QUESTION,
            SignalType.ANSWER,
            SignalType.ARTIFACT_READY,
            SignalType.VERIFY_REQUEST,
            SignalType.WARNING,
            SignalType.ERROR,
            SignalType.PROGRESS,
            SignalType.COMPLETED,
            SignalType.HEARTBEAT,
            SignalType.DECISION,
        }
    ),
    "specialist": frozenset(
        {
            SignalType.FINDING,
            SignalType.EVIDENCE,
            SignalType.HYPOTHESIS,
            SignalType.QUESTION,
            SignalType.ANSWER,
            SignalType.ARTIFACT_READY,
            SignalType.VERIFY_REQUEST,
            SignalType.VERIFIED,
            SignalType.REJECTED,
            SignalType.CHALLENGE,
            SignalType.WARNING,
            SignalType.BLOCK,
            SignalType.PROGRESS,
            SignalType.ERROR,
            SignalType.COMPLETED,
            SignalType.HEARTBEAT,
        }
    ),
    "orchestrator": frozenset(
        {
            SignalType.TASK_REQUEST,
            SignalType.TASK_HANDOFF,
            SignalType.CANCEL,
            SignalType.RESOURCE_REQUEST,
            SignalType.WORKER_SPAWN_REQUEST,
            SignalType.DECISION,
            SignalType.VERIFY_REQUEST,
            SignalType.BLOCK,
            SignalType.UNBLOCK,
            SignalType.PROGRESS,
            SignalType.WARNING,
            SignalType.ERROR,
            SignalType.COMPLETED,
            SignalType.HEARTBEAT,
            SignalType.QUESTION,
            SignalType.ANSWER,
            SignalType.FINDING,
        }
    ),
    "generic": frozenset(
        {
            SignalType.FINDING,
            SignalType.QUESTION,
            SignalType.ANSWER,
            SignalType.PROGRESS,
            SignalType.WARNING,
            SignalType.ERROR,
            SignalType.HEARTBEAT,
            SignalType.COMPLETED,
            SignalType.ARTIFACT_READY,
        }
    ),
}

# Capability tags that expand emit rights.
_CAPABILITY_EMIT_EXTRA: dict[str, frozenset[SignalType]] = {
    "evaluation": frozenset(
        {
            SignalType.VERIFIED,
            SignalType.REJECTED,
            SignalType.CHALLENGE,
            SignalType.WARNING,
            SignalType.BLOCK,
            SignalType.UNBLOCK,
        }
    ),
    "risk": frozenset(
        {
            SignalType.WARNING,
            SignalType.BLOCK,
            SignalType.UNBLOCK,
            SignalType.REJECTED,
            SignalType.CHALLENGE,
        }
    ),
    "critic": frozenset(
        {
            SignalType.VERIFIED,
            SignalType.REJECTED,
            SignalType.CHALLENGE,
            SignalType.WARNING,
            SignalType.BLOCK,
        }
    ),
    "verify": frozenset({SignalType.VERIFIED, SignalType.REJECTED, SignalType.CHALLENGE}),
    "security": frozenset({SignalType.WARNING, SignalType.BLOCK, SignalType.REJECTED}),
}


CONTROL_TYPES: frozenset[SignalType] = frozenset(
    {
        SignalType.BLOCK,
        SignalType.UNBLOCK,
        SignalType.CANCEL,
    }
)


class SignalAuthorizationPolicy:
    """Authorize publication and routing. HTTP sender_id never grants authority alone."""

    def authorize_publish(
        self,
        *,
        signal_type: SignalType,
        sender_type: SenderType,
        sender_id: str,
        recipient_type: RecipientType,
        recipient_id: str,
        agent: _AgentLike | None = None,
        operator: bool = False,
        system: bool = False,
    ) -> None:
        # Unrestricted worker mesh is forbidden.
        if sender_type == SenderType.WORKER and recipient_type == RecipientType.WORKER:
            raise SignalPolicyError(
                SIGNAL_WORKER_MESH_FORBIDDEN,
                "Workers must not message other workers directly; route via parent agent",
            )
        if sender_type == SenderType.WORKER and recipient_type not in {
            RecipientType.AGENT,
            RecipientType.ORCHESTRATOR,
            RecipientType.MISSION,
            RecipientType.SYSTEM,
        }:
            raise SignalPolicyError(
                SIGNAL_WORKER_MESH_FORBIDDEN,
                "Worker signals may only target parent agent / orchestrator / mission / system",
            )

        if system or sender_type == SenderType.SYSTEM:
            return
        if operator or sender_type == SenderType.OPERATOR:
            # Operator may publish for inspection/governance; still no worker mesh.
            return

        if agent is None:
            raise SignalPolicyError(
                SIGNAL_UNAUTHORIZED,
                "Sender agent identity could not be resolved for authorization",
            )
        if agent.archived or not agent.enabled:
            raise SignalPolicyError(
                SIGNAL_UNAUTHORIZED,
                "Sender agent is disabled or archived",
                http_status=403,
            )

        allowed = set(_KIND_EMIT_ALLOW.get(str(getattr(agent.kind, "value", agent.kind)).lower(), frozenset()))
        role_l = (agent.role or "").lower()
        caps = [c.lower() for c in (agent.capabilities or [])]
        tags = [str(t).lower() for t in (agent.metadata or {}).get("tags", [])] if isinstance(agent.metadata, dict) else []
        for token in [role_l, *caps, *tags]:
            for key, extra in _CAPABILITY_EMIT_EXTRA.items():
                if key in token:
                    allowed |= set(extra)

        # Explicit capability grant on the definition.
        if f"signal.emit.{signal_type.value.lower()}" in caps:
            allowed.add(signal_type)

        if signal_type not in allowed:
            raise SignalPolicyError(
                SIGNAL_UNAUTHORIZED,
                f"Sender {sender_id} is not authorized to emit {signal_type.value}",
            )

        if signal_type in CONTROL_TYPES:
            # Control requires evaluation/risk/orchestrator/system capability.
            kind_v = str(getattr(agent.kind, "value", agent.kind)).lower()
            has_control = (
                kind_v == "orchestrator"
                or any(k in role_l or any(k in c for c in caps) for k in ("risk", "evaluat", "critic", "security"))
                or "signal.control" in caps
            )
            if not has_control:
                raise SignalPolicyError(
                    SIGNAL_UNAUTHORIZED,
                    f"Control signal {signal_type.value} requires risk/evaluation/orchestrator authority",
                )

    def authorize_http_publish(
        self,
        *,
        claimed_sender_id: str | None,
        signal_type: SignalType,
        operator_mode: bool,
    ) -> SenderType:
        """HTTP callers never inherit agent authority from a client-supplied senderId."""
        if operator_mode:
            return SenderType.OPERATOR
        # Non-operator HTTP publish is system-mediated with restricted types.
        if signal_type in CONTROL_TYPES:
            raise SignalPolicyError(
                SIGNAL_UNAUTHORIZED,
                "HTTP clients cannot emit BLOCK/CANCEL/UNBLOCK without operator mode",
            )
        _ = claimed_sender_id  # intentionally ignored for authority
        return SenderType.OPERATOR if operator_mode else SenderType.SYSTEM
