from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentKind(str, Enum):
    GENERIC = "GENERIC"
    CODING = "CODING"
    RESEARCH = "RESEARCH"
    TRADING = "TRADING"


class AgentStepKind(str, Enum):
    PLAN = "PLAN"
    CAPABILITY = "CAPABILITY"
    VERIFY = "VERIFY"
    RESPOND = "RESPOND"


@dataclass(frozen=True)
class AgentStep:
    kind: AgentStepKind
    capability_id: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    approval_id: str | None = None
    note: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "capability_id": self.capability_id,
            "arguments": self.arguments,
            "approval_id": self.approval_id,
            "note": self.note,
        }


@dataclass
class AgentResult:
    agent_kind: AgentKind
    run_id: str | None
    status: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    job_ids: list[str] = field(default_factory=list)
    verification: dict[str, Any] | None = None
    output: str | None = None
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "agent_kind": self.agent_kind.value,
            "run_id": self.run_id,
            "status": self.status,
            "steps": self.steps,
            "job_ids": self.job_ids,
            "verification": self.verification,
            "output": self.output,
            "error": self.error,
            "truth": {
                "agents_use_shared_gateway": True,
                "agents_have_no_private_execution": True,
            },
        }
