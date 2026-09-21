from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .runtime import AgentRuntime
from .types import AgentKind, AgentResult


@dataclass
class MultiAgentResult:
    status: str
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "results": self.results,
            "error": self.error,
            "truth": {
                "multi_agent_still_uses_shared_gateway": True,
                "no_private_agent_execution": True,
            },
        }


class MultiAgentCoordinator:
    """Run ordered agent kinds sequentially on shared AgentRuntime."""

    def __init__(self, agents: AgentRuntime) -> None:
        self.agents = agents

    def run(
        self,
        request: str,
        *,
        kinds: list[AgentKind] | tuple[AgentKind, ...] | None = None,
        capability_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> MultiAgentResult:
        if not self.agents.agents_enabled:
            return MultiAgentResult(
                status="DISABLED",
                error="Agents feature flag is OFF",
            )
        sequence = list(kinds or (AgentKind.RESEARCH, AgentKind.GENERIC))
        results: list[dict[str, Any]] = []
        for kind in sequence:
            outcome: AgentResult = self.agents.execute(
                request,
                kind=kind,
                capability_overrides=capability_overrides,
            )
            results.append(outcome.public_dict())
            if outcome.status in {"FAILED", "DISABLED", "UNVERIFIED"}:
                return MultiAgentResult(status=outcome.status, results=results, error=outcome.error)
        return MultiAgentResult(status="COMPLETED", results=results)
