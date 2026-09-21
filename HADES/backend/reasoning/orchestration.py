"""Shared chat/Work execution helpers built on reasoning contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .contracts import RouteDecision
from .profiles import PROFILE_CONFIGS
from .understanding import extract_task_features, should_require_llm_critic


ExecutionStatus = Literal[
    "completed",
    "partial",
    "blocked",
    "failed",
    "cancelled",
    "running",
    "finished_unchecked",
]


@dataclass(slots=True)
class ExecutedRoute:
    intended_target: str
    actual_target: str
    planner_called: bool = False
    verification_called: bool = False
    work_runtime_called: bool = False
    research_called: bool = False
    tool_loop_called: bool = False
    model_calls: int = 0
    status: ExecutionStatus = "completed"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def should_use_work_runtime(route: RouteDecision) -> bool:
    return route.target == "work_runtime"


def should_run_verification(route: RouteDecision, *, profile_name: str | None = None, spec: Any | None = None) -> bool:
    """LLM critic only when the route/task warrants it — never as a High-mode tax."""
    if spec is not None:
        features = extract_task_features(spec)
        profile = profile_name or route.profile
        return should_require_llm_critic(spec, profile, features)
    if not route.require_verification:
        return False
    profile = profile_name or route.profile
    config = PROFILE_CONFIGS.get(profile)
    if config and not config.verify and profile in {"fast", "standard"}:
        return False
    return bool(route.require_verification)


def finalize_without_tool_json(content: str, *, reason: str, had_tool_request: bool = False) -> str:
    """Deterministic incomplete outcome when the model still requests tools after budget exhaustion."""
    stripped = (content or "").strip()
    if not had_tool_request and "hades_tool_call" not in stripped:
        return content
    return (
        "Uitvoering onvoltooid: het toolbudget is uitgeput voordat een eindantwoord beschikbaar was. "
        f"{reason} Er is geen nieuwe toolactie uitgevoerd. "
        "Geef een vervolgopdracht als de taak alsnog afgerond moet worden."
    )
