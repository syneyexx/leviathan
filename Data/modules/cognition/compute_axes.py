"""Two-axis inference compute (W3).

ReasoningDepth = OrchestrationCompute + NeuralInferenceCompute

Orchestration: retrieval rounds, critics, verification, tools, agents, candidates.
Neural: reasoning effort, reasoning token allowance, candidate count, sampling,
output allowance.

One policy owner: MetaController / ReasoningPolicy. Avoid duplicate preset tables
outside that owner — neural presets live here and are consumed by MetaController.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import CognitiveBudgets, ReasoningMode


@dataclass(frozen=True)
class NeuralComputeBudget:
    """Neural inference compute axis — provider-facing generation controls."""

    reasoning_effort: str = "low"  # minimal | low | medium | high | maximum
    reasoning_max_tokens: int | None = None
    candidate_count: int = 1
    temperature: float | None = None
    max_output_tokens: int = 1024
    top_p: float | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "reasoning_effort": self.reasoning_effort,
            "reasoning_max_tokens": self.reasoning_max_tokens,
            "candidate_count": self.candidate_count,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "top_p": self.top_p,
            "truth": {
                "neural_axis_is_not_orchestration": True,
                "effort_is_not_guaranteed_without_provider_support": True,
            },
        }


@dataclass(frozen=True)
class OrchestrationCompute:
    """View of CognitiveBudgets as the orchestration compute axis."""

    budgets: CognitiveBudgets

    @property
    def max_retrieval_rounds(self) -> int:
        return self.budgets.max_retrieval_rounds

    @property
    def max_critic_passes(self) -> int:
        return self.budgets.max_critic_passes

    @property
    def max_tool_calls(self) -> int:
        return self.budgets.max_tool_calls

    @property
    def max_agent_delegations(self) -> int:
        return self.budgets.max_agent_delegations

    @property
    def max_model_calls(self) -> int:
        return self.budgets.max_model_calls

    def public_dict(self) -> dict[str, Any]:
        b = self.budgets.public_dict()
        return {
            "max_retrieval_rounds": b["max_retrieval_rounds"],
            "max_critic_passes": b["max_critic_passes"],
            "max_tool_calls": b["max_tool_calls"],
            "max_agent_delegations": b["max_agent_delegations"],
            "max_model_calls": b["max_model_calls"],
            "max_iterations": b["max_iterations"],
            "max_replans": b["max_replans"],
            "budgets": b,
            "truth": {"orchestration_axis_is_not_neural": True},
        }


def neural_presets() -> dict[ReasoningMode, NeuralComputeBudget]:
    """Single neural preset table — MetaController is the consumer/owner."""
    return {
        ReasoningMode.FAST: NeuralComputeBudget(
            reasoning_effort="minimal",
            reasoning_max_tokens=0,
            candidate_count=1,
            temperature=0.3,
            max_output_tokens=512,
            top_p=0.9,
        ),
        ReasoningMode.STANDARD: NeuralComputeBudget(
            reasoning_effort="low",
            reasoning_max_tokens=256,
            candidate_count=1,
            temperature=0.4,
            max_output_tokens=2048,
            top_p=0.95,
        ),
        ReasoningMode.DEEP: NeuralComputeBudget(
            reasoning_effort="high",
            reasoning_max_tokens=1024,
            candidate_count=3,
            temperature=0.5,
            max_output_tokens=4096,
            top_p=0.95,
        ),
        ReasoningMode.MAXIMUM: NeuralComputeBudget(
            reasoning_effort="maximum",
            reasoning_max_tokens=4096,
            candidate_count=5,
            temperature=0.6,
            max_output_tokens=8192,
            top_p=1.0,
        ),
        ReasoningMode.ADAPTIVE: NeuralComputeBudget(
            reasoning_effort="medium",
            reasoning_max_tokens=512,
            candidate_count=2,
            temperature=0.45,
            max_output_tokens=2048,
            top_p=0.95,
        ),
    }


def neural_for_mode(mode: ReasoningMode) -> NeuralComputeBudget:
    presets = neural_presets()
    if mode == ReasoningMode.ADAPTIVE:
        return presets[ReasoningMode.STANDARD]
    return presets.get(mode, presets[ReasoningMode.STANDARD])


def assert_modes_measurably_different(
    orchestration_presets: dict[ReasoningMode, CognitiveBudgets] | None = None,
) -> dict[str, Any]:
    """Diagnostic: FAST < STANDARD < DEEP < MAXIMUM on both axes."""
    neural = neural_presets()
    orch = orchestration_presets or {}
    order = (
        ReasoningMode.FAST,
        ReasoningMode.STANDARD,
        ReasoningMode.DEEP,
        ReasoningMode.MAXIMUM,
    )
    diffs: list[str] = []
    for a, b in zip(order, order[1:]):
        if neural[a].max_output_tokens >= neural[b].max_output_tokens:
            diffs.append(f"neural max_output {a.value}>={b.value}")
        if neural[a].candidate_count > neural[b].candidate_count:
            diffs.append(f"neural candidates {a.value}>{b.value}")
        if a in orch and b in orch:
            if orch[a].max_model_calls >= orch[b].max_model_calls:
                diffs.append(f"orch model_calls {a.value}>={b.value}")
            if orch[a].max_critic_passes > orch[b].max_critic_passes:
                diffs.append(f"orch critics {a.value}>{b.value}")
    return {
        "ok": not diffs,
        "violations": diffs,
        "truth": {"modes_must_differ_measurably": True},
    }
