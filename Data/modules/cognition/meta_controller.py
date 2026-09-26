"""MetaController — allocates real cognitive budgets (not cosmetic modes).

Supports continuous re-decision and adaptive escalation/de-escalation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from Data.modules.intelligence.policy import ReasoningPolicy

from .compute_axes import (
    NeuralComputeBudget,
    OrchestrationCompute,
    neural_for_mode,
)
from .task_model import TaskModel
from .types import CognitiveBudgets, ReasoningMode, ReasoningStrategy, RiskClass


@dataclass(frozen=True)
class MetaDecision:
    mode: ReasoningMode
    strategy: ReasoningStrategy
    budgets: CognitiveBudgets
    value_scores: dict[str, float]
    notes: tuple[str, ...]
    escalation: str | None = None  # escalated | deescalated | None
    requested_mode: ReasoningMode | None = None
    effective_mode: ReasoningMode | None = None
    neural: NeuralComputeBudget | None = None
    resource_pressure: float = 0.0

    def public_dict(self) -> dict[str, Any]:
        effective = self.effective_mode or self.mode
        neural = self.neural or neural_for_mode(effective)
        return {
            "mode": self.mode.value,
            "requested_mode": (self.requested_mode.value if self.requested_mode else None),
            "effective_mode": effective.value,
            "strategy": self.strategy.value,
            "budgets": self.budgets.public_dict(),
            "orchestration": OrchestrationCompute(self.budgets).public_dict(),
            "neural": neural.public_dict(),
            "resource_pressure": self.resource_pressure,
            "value_scores": dict(self.value_scores),
            "notes": list(self.notes),
            "escalation": self.escalation,
            "truth": {
                "modes_control_real_budgets": True,
                "more_agents_is_not_automatically_better": True,
                "adaptive_can_escalate_and_deescalate": True,
                "two_axis_compute": True,
                "requested_and_effective_mode_observable": True,
            },
        }


_BUDGET_FIELDS: tuple[str, ...] = (
    "max_wall_time_seconds",
    "max_model_calls",
    "max_model_tokens",
    "max_tool_calls",
    "max_agent_delegations",
    "max_replans",
    "max_retries",
    "max_retrieval_rounds",
    "max_parallel_workers",
    "max_context_tokens",
    "max_critic_passes",
    "max_iterations",
)

_MODE_ORDER = (
    ReasoningMode.FAST,
    ReasoningMode.STANDARD,
    ReasoningMode.DEEP,
    ReasoningMode.MAXIMUM,
)


def _cognitive_budgets_from_mapping(raw: dict[str, Any] | None) -> CognitiveBudgets | None:
    if not isinstance(raw, dict) or not raw:
        return None
    defaults = CognitiveBudgets()
    kwargs: dict[str, Any] = {}
    for name in _BUDGET_FIELDS:
        if name not in raw:
            continue
        try:
            current = getattr(defaults, name)
            kwargs[name] = type(current)(raw[name])
        except (TypeError, ValueError):
            continue
    return CognitiveBudgets(**{**defaults.public_dict(), **kwargs})


def _mode_index(mode: ReasoningMode) -> int:
    try:
        return _MODE_ORDER.index(mode if mode != ReasoningMode.ADAPTIVE else ReasoningMode.STANDARD)
    except ValueError:
        return 1


class MetaController:
    """Decide HOW MUCH cognition is justified — continuously when called each iteration."""

    def __init__(self, policy: ReasoningPolicy | None = None) -> None:
        self.policy = policy

    def set_policy(self, policy: ReasoningPolicy | None) -> None:
        """Hot-swap reasoning budget policy (settings control plane)."""
        self.policy = policy

    def decide(
        self,
        task: TaskModel,
        *,
        uncertainty: float | None = None,
        evidence_coverage: float = 0.0,
        contradiction_density: float = 0.0,
        resource_pressure: float = 0.0,
        working_memory_saturation: float = 0.0,
        model_available: bool = True,
        user_requested_depth: str | None = None,
        previous_mode: ReasoningMode | None = None,
        information_gain_recent: float | None = None,
        plan_progress: float = 0.0,
        tool_failures: int = 0,
        repeated_actions: int = 0,
    ) -> MetaDecision:
        unc = task.initial_uncertainty if uncertainty is None else max(0.0, min(1.0, uncertainty))
        notes: list[str] = []
        escalation: str | None = None

        requested_mode: ReasoningMode | None = None
        if user_requested_depth:
            mapping = {m.value.lower(): m for m in ReasoningMode}
            requested_mode = mapping.get(str(user_requested_depth).strip().lower())

        mode = self._mode(task, unc, user_requested_depth, resource_pressure)
        # Adaptive escalation / de-escalation during a run.
        if previous_mode is not None and (
            not user_requested_depth
            or str(user_requested_depth).strip().lower() in {"adaptive", "adadaptive", ""}
            or str(user_requested_depth).strip().upper() == ReasoningMode.ADAPTIVE.value
        ):
            mode, escalation, esc_notes = self._adapt_mode(
                previous_mode,
                mode,
                uncertainty=unc,
                contradiction_density=contradiction_density,
                evidence_coverage=evidence_coverage,
                information_gain_recent=information_gain_recent,
                resource_pressure=resource_pressure,
                tool_failures=tool_failures,
                repeated_actions=repeated_actions,
                task=task,
            )
            notes.extend(esc_notes)

        strategy = self._strategy(task, unc, evidence_coverage, contradiction_density)
        budgets = self._budgets(mode, task, resource_pressure)
        neural = neural_for_mode(mode)
        # Under high pressure, shrink neural candidate/output allowance measurably.
        if resource_pressure >= 0.7:
            neural = NeuralComputeBudget(
                reasoning_effort="low" if neural.reasoning_effort in {"high", "maximum"} else neural.reasoning_effort,
                reasoning_max_tokens=(
                    min(neural.reasoning_max_tokens or 0, 256) if neural.reasoning_max_tokens else 0
                ),
                candidate_count=max(1, min(2, neural.candidate_count)),
                temperature=neural.temperature,
                max_output_tokens=max(512, neural.max_output_tokens // 2),
                top_p=neural.top_p,
            )
            notes.append("resource pressure — reduced neural compute axis")
        values = self._value_scores(
            task,
            unc,
            evidence_coverage,
            contradiction_density,
            plan_progress=plan_progress,
            information_gain_recent=information_gain_recent,
        )

        execution_class = str(getattr(task, "execution_class", None) or "DIRECT")
        if execution_class == "DIRECT" and task.task_type == "simple_chat":
            notes.append("simple/DIRECT execution_class — keep FAST path")
        elif execution_class == "DIRECT":
            notes.append("DIRECT execution_class — keep FAST path")
        if execution_class == "CURRENT_INFO" or getattr(task, "requires_current_information", False):
            notes.append("freshness required — external research valuable when permitted")
        if execution_class in {"MULTI_DOMAIN", "COMPLEX_REASONING"}:
            notes.append(f"execution_class={execution_class} — deeper orchestration")
        if execution_class in {"TOOL_REQUIRED", "VERIFICATION_REQUIRED"}:
            notes.append(f"execution_class={execution_class} — tool/verify path required")
        if getattr(task, "research_mode", "none") == "deep":
            notes.append("deep research mode indicated by task semantics")
        if resource_pressure >= 0.7:
            notes.append("resource pressure — reduced parallelism and depth")
        if not model_available:
            notes.append("model unavailable — retrieval/delegation only where possible")
            budgets = CognitiveBudgets(
                max_wall_time_seconds=min(budgets.max_wall_time_seconds, 30.0),
                max_model_calls=0,
                max_model_tokens=0,
                max_tool_calls=budgets.max_tool_calls,
                max_agent_delegations=0,
                max_replans=1,
                max_retries=1,
                max_retrieval_rounds=min(2, budgets.max_retrieval_rounds),
                max_parallel_workers=1,
                max_context_tokens=min(2000, budgets.max_context_tokens),
                max_critic_passes=0,
                max_iterations=2,
            )
        if working_memory_saturation > 0.85:
            notes.append("working memory saturated — prefer compaction over expand")
        if values.get("delegate_agent", 0) < 0.35:
            notes.append("delegation value low — prefer direct path")
        if values.get("retrieve", 0) < 0.25 and evidence_coverage >= 0.6:
            notes.append("retrieval low VoI — evidence already adequate")

        # Enforce policy verification flags when present.
        if self.policy is not None:
            if (
                getattr(self.policy, "require_verification_for_high_risk", False)
                and task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL}
            ):
                notes.append("policy requires verification for high-risk task")
                values["verify"] = max(values.get("verify", 0.0), 0.75)
            if getattr(self.policy, "require_grounding_for_knowledge_tasks", False) and task.domain in {
                "knowledge",
                "research",
                "question",
            }:
                values["retrieve"] = max(values.get("retrieve", 0.0), 0.55)

        return MetaDecision(
            mode=mode,
            strategy=strategy,
            budgets=budgets,
            value_scores=values,
            notes=tuple(notes),
            escalation=escalation,
            requested_mode=requested_mode,
            effective_mode=mode,
            neural=neural,
            resource_pressure=float(resource_pressure),
        )

    def estimate_value_of_action(
        self,
        *,
        expected_gain: float,
        expected_risk_reduction: float = 0.0,
        expected_completion_progress: float = 0.0,
        cost: float,
        latency_penalty: float = 0.0,
        duplication_penalty: float = 0.0,
        failure_risk: float = 0.0,
        risk_penalty: float = 0.0,
    ) -> float:
        """Practical VoI heuristic — not academic Bayesian inference.

        utility ≈ expected_gain + risk_reduction + progress − costs − penalties
        """
        return round(
            expected_gain
            + expected_risk_reduction
            + expected_completion_progress
            - cost
            - latency_penalty
            - duplication_penalty
            - failure_risk
            - risk_penalty,
            4,
        )

    def _adapt_mode(
        self,
        previous: ReasoningMode,
        proposed: ReasoningMode,
        *,
        uncertainty: float,
        contradiction_density: float,
        evidence_coverage: float,
        information_gain_recent: float | None,
        resource_pressure: float,
        tool_failures: int,
        repeated_actions: int,
        task: TaskModel,
    ) -> tuple[ReasoningMode, str | None, list[str]]:
        notes: list[str] = []
        mode = previous if previous != ReasoningMode.ADAPTIVE else proposed
        if mode == ReasoningMode.ADAPTIVE:
            mode = ReasoningMode.STANDARD

        escalate = False
        deescalate = False

        if contradiction_density >= 0.4 or uncertainty >= 0.7:
            escalate = True
            notes.append("escalate — high uncertainty or contradiction density")
        if getattr(task, "requires_research", False) and evidence_coverage < 0.35:
            escalate = True
            notes.append("escalate — research needed with low evidence coverage")
        if tool_failures >= 2 or repeated_actions >= 2:
            escalate = True
            notes.append("escalate — repeated failures suggest deeper strategy")

        if (
            evidence_coverage >= 0.75
            and contradiction_density < 0.15
            and uncertainty < 0.35
            and (information_gain_recent is not None and information_gain_recent < 0.1)
        ):
            deescalate = True
            notes.append("de-escalate — criteria largely met, low remaining gain")
        if resource_pressure >= 0.8:
            deescalate = True
            notes.append("de-escalate — resource pressure")

        idx = _mode_index(mode)
        if escalate and not deescalate:
            idx = min(len(_MODE_ORDER) - 1, idx + 1)
            return _MODE_ORDER[idx], "escalated", notes
        if deescalate and not escalate:
            idx = max(0, idx - 1)
            # Never de-escalate below STANDARD for research/coding mid-run unless simple.
            if task.task_type != "simple_chat" and _MODE_ORDER[idx] == ReasoningMode.FAST:
                idx = 1
            return _MODE_ORDER[idx], "deescalated", notes
        # Prefer proposed when neither strongly indicated.
        if _mode_index(proposed) != idx:
            return proposed, None, notes
        return mode, None, notes

    def _uncertainty_deep_threshold(self) -> float:
        if self.policy is not None:
            return float(self.policy.uncertainty_deep_threshold)
        return 0.75

    def _allow_fast_path(self) -> bool:
        if self.policy is not None:
            return bool(self.policy.allow_fast_path)
        return True

    def _mode(
        self,
        task: TaskModel,
        uncertainty: float,
        user_depth: str | None,
        resource_pressure: float,
    ) -> ReasoningMode:
        if user_depth:
            mapping = {m.value.lower(): m for m in ReasoningMode}
            forced = mapping.get(user_depth.strip().lower())
            # ADAPTIVE falls through to heuristics (settings default_mode=adaptive).
            if forced and forced != ReasoningMode.ADAPTIVE:
                if resource_pressure >= 0.8 and forced in {ReasoningMode.DEEP, ReasoningMode.MAXIMUM}:
                    return ReasoningMode.STANDARD
                return forced
        deep_threshold = self._uncertainty_deep_threshold()
        allow_fast = self._allow_fast_path()
        execution_class = str(getattr(task, "execution_class", None) or "DIRECT")
        # Adaptive depth from TaskModel.execution_class (GI4) — beats short-message simple_chat.
        if execution_class == "DIRECT" and task.risk_class == RiskClass.LOW:
            return ReasoningMode.FAST if allow_fast else ReasoningMode.STANDARD
        if execution_class in {"MULTI_DOMAIN", "COMPLEX_REASONING", "WORK"}:
            if resource_pressure < 0.7:
                return ReasoningMode.DEEP if uncertainty >= 0.4 else ReasoningMode.STANDARD
            return ReasoningMode.STANDARD
        if execution_class == "CURRENT_INFO" or (
            getattr(task, "requires_current_information", False) and uncertainty >= 0.5
        ):
            return ReasoningMode.STANDARD if resource_pressure >= 0.6 else ReasoningMode.DEEP
        if execution_class in {"TOOL_REQUIRED", "VERIFICATION_REQUIRED", "CONTEXTUAL"}:
            return ReasoningMode.STANDARD
        if task.task_type == "simple_chat" and task.risk_class == RiskClass.LOW:
            return ReasoningMode.FAST if allow_fast else ReasoningMode.STANDARD
        if getattr(task, "research_mode", "none") == "deep" or getattr(task, "requires_research", False):
            if resource_pressure < 0.7:
                return ReasoningMode.DEEP if uncertainty >= 0.45 or task.research_mode == "deep" else ReasoningMode.STANDARD
        if task.risk_class == RiskClass.CRITICAL or (
            uncertainty >= deep_threshold and task.domain in {"coding", "research"}
        ):
            return ReasoningMode.DEEP if resource_pressure < 0.7 else ReasoningMode.STANDARD
        if task.legacy_plan and task.legacy_plan.complexity == "high":
            return ReasoningMode.STANDARD if resource_pressure >= 0.6 else ReasoningMode.DEEP
        if uncertainty >= 0.55 or task.domain in {"coding", "research"}:
            return ReasoningMode.STANDARD
        return ReasoningMode.FAST if allow_fast else ReasoningMode.STANDARD

    def _strategy(
        self,
        task: TaskModel,
        uncertainty: float,
        evidence_coverage: float,
        contradiction_density: float,
    ) -> ReasoningStrategy:
        contradiction_threshold = 0.3
        if self.policy is not None:
            contradiction_threshold = float(self.policy.contradiction_replan_threshold)
        min_evidence = 0.3
        if self.policy is not None:
            min_evidence = float(self.policy.minimum_evidence_coverage)

        execution_class = str(getattr(task, "execution_class", None) or "DIRECT")
        # Coding / research domain strategies stay specialized even when execution_class is TOOL_REQUIRED.
        if task.domain == "coding" and execution_class not in {"DIRECT", "CURRENT_INFO"}:
            if "repair" in task.task_type or any("test" in c.lower() for c in task.success_criteria):
                return ReasoningStrategy.CODING_REPAIR
            return ReasoningStrategy.DEBUG_LOOP if uncertainty >= 0.55 else ReasoningStrategy.PLAN_EXECUTE_VERIFY
        if (task.domain == "research" or getattr(task, "requires_research", False)) and execution_class not in {
            "DIRECT",
            "TOOL_REQUIRED",
        }:
            if contradiction_density >= contradiction_threshold:
                return ReasoningStrategy.COMPARE_ALTERNATIVES
            if task.task_type == "research_comparison":
                return ReasoningStrategy.COMPARE_ALTERNATIVES
            return ReasoningStrategy.RESEARCH_SYNTHESIS
        # execution_class beats short-message simple_chat when tools/current-info are required.
        if execution_class == "DIRECT":
            return ReasoningStrategy.DIRECT
        if execution_class == "MULTI_DOMAIN":
            return ReasoningStrategy.MULTI_AGENT
        if execution_class == "COMPLEX_REASONING":
            return (
                ReasoningStrategy.RESEARCH_SYNTHESIS
                if getattr(task, "requires_research", False)
                else ReasoningStrategy.PLAN_EXECUTE_VERIFY
            )
        if execution_class == "CURRENT_INFO" or getattr(task, "requires_current_information", False):
            return ReasoningStrategy.TOOL_DRIVEN
        if execution_class == "TOOL_REQUIRED" or getattr(task, "needs_calculation", False):
            return ReasoningStrategy.TOOL_DRIVEN
        if execution_class == "VERIFICATION_REQUIRED":
            return ReasoningStrategy.HIGH_RISK_VERIFY
        if execution_class == "CONTEXTUAL":
            return ReasoningStrategy.RETRIEVE_THEN_ANSWER
        if task.task_type == "simple_chat":
            return ReasoningStrategy.DIRECT
        if task.domain == "coding":
            if "repair" in task.task_type or any("test" in c.lower() for c in task.success_criteria):
                return ReasoningStrategy.CODING_REPAIR
            return ReasoningStrategy.DEBUG_LOOP if uncertainty >= 0.55 else ReasoningStrategy.PLAN_EXECUTE_VERIFY
        if task.domain == "research" or getattr(task, "requires_research", False):
            if contradiction_density >= contradiction_threshold:
                return ReasoningStrategy.COMPARE_ALTERNATIVES
            if task.task_type == "research_comparison":
                return ReasoningStrategy.COMPARE_ALTERNATIVES
            return ReasoningStrategy.RESEARCH_SYNTHESIS
        if task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL}:
            return ReasoningStrategy.HIGH_RISK_VERIFY
        if evidence_coverage < min_evidence and (
            (task.legacy_plan.use_knowledge if task.legacy_plan else True)
            or getattr(task, "requires_current_information", False)
        ):
            return ReasoningStrategy.RETRIEVE_THEN_ANSWER
        if task.side_effect_expectations or getattr(task, "requires_tools", False):
            return ReasoningStrategy.TOOL_DRIVEN
        if uncertainty >= 0.65:
            return ReasoningStrategy.HYPOTHESIS_TEST
        return ReasoningStrategy.DIRECT

    def _policy_budgets(self, mode: ReasoningMode) -> CognitiveBudgets | None:
        if self.policy is None:
            return None
        raw: dict[str, Any] | None = None
        if hasattr(self.policy, "budgets_for"):
            try:
                raw = self.policy.budgets_for(mode.value)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                raw = None
        if raw is None and hasattr(self.policy, "budget_for"):
            try:
                raw = self.policy.budget_for(mode.value)
            except Exception:  # noqa: BLE001
                raw = None
        if raw is None and isinstance(self.policy.mode_budgets, dict):
            key = mode.value.upper()
            candidate = self.policy.mode_budgets.get(key) or self.policy.mode_budgets.get(mode.value)
            if isinstance(candidate, dict):
                raw = dict(candidate)
        return _cognitive_budgets_from_mapping(raw)

    def _hardcoded_presets(self) -> dict[ReasoningMode, CognitiveBudgets]:
        return {
            ReasoningMode.FAST: CognitiveBudgets(
                max_wall_time_seconds=30.0,
                max_model_calls=1,
                max_model_tokens=2000,
                max_tool_calls=0,
                max_agent_delegations=0,
                max_replans=0,
                max_retries=1,
                max_retrieval_rounds=1,
                max_parallel_workers=1,
                max_context_tokens=3000,
                max_critic_passes=0,
                max_iterations=2,
            ),
            ReasoningMode.STANDARD: CognitiveBudgets(
                max_wall_time_seconds=90.0,
                max_model_calls=3,
                max_model_tokens=6000,
                max_tool_calls=4,
                max_agent_delegations=1,
                max_replans=2,
                max_retries=2,
                max_retrieval_rounds=2,
                max_parallel_workers=2,
                max_context_tokens=6000,
                max_critic_passes=1,
                max_iterations=5,
            ),
            ReasoningMode.DEEP: CognitiveBudgets(
                max_wall_time_seconds=180.0,
                max_model_calls=6,
                max_model_tokens=12000,
                max_tool_calls=8,
                max_agent_delegations=2,
                max_replans=3,
                max_retries=3,
                max_retrieval_rounds=3,
                max_parallel_workers=3,
                max_context_tokens=8000,
                max_critic_passes=2,
                max_iterations=8,
            ),
            ReasoningMode.MAXIMUM: CognitiveBudgets(
                max_wall_time_seconds=300.0,
                max_model_calls=10,
                max_model_tokens=20000,
                max_tool_calls=12,
                max_agent_delegations=3,
                max_replans=4,
                max_retries=4,
                max_retrieval_rounds=4,
                max_parallel_workers=4,
                max_context_tokens=12000,
                max_critic_passes=3,
                max_iterations=12,
            ),
            ReasoningMode.ADAPTIVE: CognitiveBudgets(),
        }

    def _budgets(
        self,
        mode: ReasoningMode,
        task: TaskModel,
        resource_pressure: float,
    ) -> CognitiveBudgets:
        base = self._policy_budgets(mode)
        if base is None:
            base = self._hardcoded_presets().get(mode, CognitiveBudgets())
        elif self.policy is not None:
            base = CognitiveBudgets(
                max_wall_time_seconds=base.max_wall_time_seconds,
                max_model_calls=base.max_model_calls,
                max_model_tokens=base.max_model_tokens,
                max_tool_calls=base.max_tool_calls,
                max_agent_delegations=base.max_agent_delegations,
                max_replans=min(base.max_replans, int(self.policy.max_replans_global)),
                max_retries=min(base.max_retries, int(self.policy.max_retries_global)),
                max_retrieval_rounds=base.max_retrieval_rounds,
                max_parallel_workers=base.max_parallel_workers,
                max_context_tokens=base.max_context_tokens,
                max_critic_passes=base.max_critic_passes,
                max_iterations=base.max_iterations,
            )
        if resource_pressure >= 0.7:
            base = CognitiveBudgets(
                max_wall_time_seconds=min(base.max_wall_time_seconds, 60.0),
                max_model_calls=max(1, base.max_model_calls // 2),
                max_model_tokens=max(1000, base.max_model_tokens // 2),
                max_tool_calls=max(0, base.max_tool_calls // 2),
                max_agent_delegations=min(1, base.max_agent_delegations),
                max_replans=min(1, base.max_replans),
                max_retries=min(1, base.max_retries),
                max_retrieval_rounds=min(2, base.max_retrieval_rounds),
                max_parallel_workers=1,
                max_context_tokens=max(2000, base.max_context_tokens // 2),
                max_critic_passes=min(1, base.max_critic_passes),
                max_iterations=max(2, base.max_iterations // 2),
            )
        if not task.allowed_delegation:
            base = CognitiveBudgets(
                max_wall_time_seconds=base.max_wall_time_seconds,
                max_model_calls=base.max_model_calls,
                max_model_tokens=base.max_model_tokens,
                max_tool_calls=base.max_tool_calls,
                max_agent_delegations=0,
                max_replans=base.max_replans,
                max_retries=base.max_retries,
                max_retrieval_rounds=base.max_retrieval_rounds,
                max_parallel_workers=base.max_parallel_workers,
                max_context_tokens=base.max_context_tokens,
                max_critic_passes=base.max_critic_passes,
                max_iterations=base.max_iterations,
            )
        # DIRECT short path — HADES lesson: hard ceilings, no tool burn.
        execution_class = str(getattr(task, "execution_class", None) or "DIRECT")
        if execution_class == "DIRECT":
            base = CognitiveBudgets(
                max_wall_time_seconds=min(base.max_wall_time_seconds, 30.0),
                max_model_calls=min(1, base.max_model_calls),
                max_model_tokens=min(2000, base.max_model_tokens),
                max_tool_calls=0,
                max_agent_delegations=0,
                max_replans=0,
                max_retries=min(1, base.max_retries),
                max_retrieval_rounds=min(1, base.max_retrieval_rounds),
                max_parallel_workers=1,
                max_context_tokens=min(3000, base.max_context_tokens),
                max_critic_passes=0,
                max_iterations=min(2, base.max_iterations),
            )
        elif execution_class == "TOOL_REQUIRED":
            # Ensure at least one tool call slot for inspect/calc/web.
            base = CognitiveBudgets(
                max_wall_time_seconds=base.max_wall_time_seconds,
                max_model_calls=max(1, base.max_model_calls),
                max_model_tokens=base.max_model_tokens,
                max_tool_calls=max(2, base.max_tool_calls),
                max_agent_delegations=base.max_agent_delegations,
                max_replans=min(base.max_replans, 2),
                max_retries=base.max_retries,
                max_retrieval_rounds=base.max_retrieval_rounds,
                max_parallel_workers=base.max_parallel_workers,
                max_context_tokens=base.max_context_tokens,
                max_critic_passes=base.max_critic_passes,
                max_iterations=max(3, base.max_iterations),
            )
        elif execution_class == "CURRENT_INFO":
            base = CognitiveBudgets(
                max_wall_time_seconds=base.max_wall_time_seconds,
                max_model_calls=max(2, base.max_model_calls),
                max_model_tokens=base.max_model_tokens,
                max_tool_calls=max(2, base.max_tool_calls),
                max_agent_delegations=base.max_agent_delegations,
                max_replans=min(base.max_replans, 2),
                max_retries=base.max_retries,
                max_retrieval_rounds=base.max_retrieval_rounds,
                max_parallel_workers=base.max_parallel_workers,
                max_context_tokens=base.max_context_tokens,
                max_critic_passes=base.max_critic_passes,
                max_iterations=max(4, base.max_iterations),
            )
        return base

    def _value_scores(
        self,
        task: TaskModel,
        uncertainty: float,
        evidence_coverage: float,
        contradiction_density: float,
        *,
        plan_progress: float = 0.0,
        information_gain_recent: float | None = None,
    ) -> dict[str, float]:
        min_evidence = 0.3
        contradiction_threshold = 0.3
        if self.policy is not None:
            min_evidence = float(self.policy.minimum_evidence_coverage)
            contradiction_threshold = float(self.policy.contradiction_replan_threshold)

        dup = 0.25 if information_gain_recent is not None and information_gain_recent < 0.05 else 0.0
        retrieve_gain = min(
            1.0,
            uncertainty
            + (0.45 if evidence_coverage < min_evidence else 0.1)
            + (0.2 if getattr(task, "requires_current_information", False) else 0.0),
        )
        retrieve = self.estimate_value_of_action(
            expected_gain=retrieve_gain,
            expected_risk_reduction=0.1 if evidence_coverage < min_evidence else 0.0,
            expected_completion_progress=0.15 if evidence_coverage < 0.5 else 0.0,
            cost=0.2,
            latency_penalty=0.05,
            duplication_penalty=dup,
        )
        critic = self.estimate_value_of_action(
            expected_gain=0.55 if task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL} else 0.25,
            expected_risk_reduction=0.2 if contradiction_density >= contradiction_threshold else 0.05,
            cost=0.2,
            latency_penalty=0.1,
        )
        verify_boost = 0.0
        if str(getattr(task, "verification_mode", "") or "") in {"REQUIRED", "CORROBORATED"}:
            verify_boost = 0.35
        verify = self.estimate_value_of_action(
            expected_gain=(0.4 if task.success_criteria else 0.15) + verify_boost,
            expected_risk_reduction=0.35 if task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL} else 0.1,
            expected_completion_progress=0.25 if plan_progress >= 0.5 else 0.05,
            cost=0.15,
            latency_penalty=0.05,
        )
        delegate = 0.0
        if str(getattr(task, "execution_class", "") or "") in {"MULTI_DOMAIN", "COMPLEX_REASONING", "WORK"}:
            delegate = max(
                delegate,
                self.estimate_value_of_action(
                    expected_gain=0.55,
                    expected_completion_progress=0.2,
                    cost=0.3,
                    latency_penalty=0.1,
                ),
            )
        if "coding" in task.allowed_delegation and task.domain == "coding":
            delegate = self.estimate_value_of_action(
                expected_gain=0.7 if task.legacy_plan and task.legacy_plan.complexity != "low" else 0.35,
                expected_completion_progress=0.2,
                cost=0.4,
                latency_penalty=0.15,
                risk_penalty=0.1 if task.risk_class == RiskClass.CRITICAL else 0.0,
            )
        if "research" in task.allowed_delegation and (
            task.domain == "research" or getattr(task, "requires_research", False)
        ):
            research_gain = 0.8 if getattr(task, "research_mode", "none") == "deep" else 0.65
            delegate = max(
                delegate,
                self.estimate_value_of_action(
                    expected_gain=research_gain,
                    expected_risk_reduction=0.2 if getattr(task, "requires_current_information", False) else 0.1,
                    expected_completion_progress=0.25,
                    cost=0.35,
                    latency_penalty=0.2,
                    duplication_penalty=dup,
                ),
            )
        replan = self.estimate_value_of_action(
            expected_gain=0.5 if contradiction_density >= contradiction_threshold else 0.15,
            expected_completion_progress=0.1 if plan_progress < 0.3 else 0.0,
            cost=0.25,
        )
        return {
            "retrieve": retrieve,
            "critic": critic,
            "verify": verify,
            "delegate_agent": delegate,
            "replan": replan,
        }
