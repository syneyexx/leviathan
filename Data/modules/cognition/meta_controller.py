"""MetaController — allocates real cognitive budgets (not cosmetic modes)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from Data.modules.intelligence.policy import ReasoningPolicy

from .task_model import TaskModel
from .types import CognitiveBudgets, ReasoningMode, ReasoningStrategy, RiskClass


@dataclass(frozen=True)
class MetaDecision:
    mode: ReasoningMode
    strategy: ReasoningStrategy
    budgets: CognitiveBudgets
    value_scores: dict[str, float]
    notes: tuple[str, ...]

    def public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "strategy": self.strategy.value,
            "budgets": self.budgets.public_dict(),
            "value_scores": dict(self.value_scores),
            "notes": list(self.notes),
            "truth": {
                "modes_control_real_budgets": True,
                "more_agents_is_not_automatically_better": True,
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


class MetaController:
    """Decide HOW MUCH cognition is justified."""

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
    ) -> MetaDecision:
        unc = task.initial_uncertainty if uncertainty is None else max(0.0, min(1.0, uncertainty))
        notes: list[str] = []
        mode = self._mode(task, unc, user_requested_depth, resource_pressure)
        strategy = self._strategy(task, unc, evidence_coverage, contradiction_density)
        budgets = self._budgets(mode, task, resource_pressure)
        values = self._value_scores(task, unc, evidence_coverage, contradiction_density)

        if task.task_type == "simple_chat":
            notes.append("simple request — keep FAST path")
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

        return MetaDecision(
            mode=mode,
            strategy=strategy,
            budgets=budgets,
            value_scores=values,
            notes=tuple(notes),
        )

    def estimate_value_of_action(
        self,
        *,
        expected_gain: float,
        cost: float,
        latency_penalty: float = 0.0,
        risk_penalty: float = 0.0,
    ) -> float:
        """Practical VoI heuristic — not academic Bayesian inference."""
        return round(expected_gain - cost - latency_penalty - risk_penalty, 4)

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
        if task.task_type == "simple_chat" and task.risk_class == RiskClass.LOW:
            return ReasoningMode.FAST if allow_fast else ReasoningMode.STANDARD
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

        if task.task_type == "simple_chat":
            return ReasoningStrategy.DIRECT
        if task.domain == "coding":
            if "repair" in task.task_type or any("test" in c.lower() for c in task.success_criteria):
                return ReasoningStrategy.CODING_REPAIR
            return ReasoningStrategy.DEBUG_LOOP if uncertainty >= 0.55 else ReasoningStrategy.PLAN_EXECUTE_VERIFY
        if task.domain == "research":
            if contradiction_density >= contradiction_threshold:
                return ReasoningStrategy.COMPARE_ALTERNATIVES
            return ReasoningStrategy.RESEARCH_SYNTHESIS
        if task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL}:
            return ReasoningStrategy.HIGH_RISK_VERIFY
        if evidence_coverage < min_evidence and (task.legacy_plan.use_knowledge if task.legacy_plan else True):
            return ReasoningStrategy.RETRIEVE_THEN_ANSWER
        if task.side_effect_expectations:
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
            # Global caps from settings-backed policy.
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
        # Never grant delegation budget for domains not allowed.
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
        return base

    def _value_scores(
        self,
        task: TaskModel,
        uncertainty: float,
        evidence_coverage: float,
        contradiction_density: float,
    ) -> dict[str, float]:
        min_evidence = 0.3
        contradiction_threshold = 0.3
        if self.policy is not None:
            min_evidence = float(self.policy.minimum_evidence_coverage)
            contradiction_threshold = float(self.policy.contradiction_replan_threshold)
        retrieve = self.estimate_value_of_action(
            expected_gain=min(1.0, uncertainty + (0.4 if evidence_coverage < min_evidence else 0.1)),
            cost=0.2,
            latency_penalty=0.05,
        )
        critic = self.estimate_value_of_action(
            expected_gain=0.55 if task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL} else 0.25,
            cost=0.2,
            latency_penalty=0.1,
        )
        delegate = 0.0
        if "coding" in task.allowed_delegation and task.domain == "coding":
            delegate = self.estimate_value_of_action(
                expected_gain=0.7 if task.legacy_plan and task.legacy_plan.complexity != "low" else 0.35,
                cost=0.4,
                latency_penalty=0.15,
                risk_penalty=0.1 if task.risk_class == RiskClass.CRITICAL else 0.0,
            )
        if "research" in task.allowed_delegation and task.domain == "research":
            delegate = max(
                delegate,
                self.estimate_value_of_action(
                    expected_gain=0.65,
                    cost=0.35,
                    latency_penalty=0.2,
                ),
            )
        replan = self.estimate_value_of_action(
            expected_gain=0.5 if contradiction_density >= contradiction_threshold else 0.15,
            cost=0.25,
        )
        return {
            "retrieve": retrieve,
            "critic": critic,
            "delegate_agent": delegate,
            "replan": replan,
        }
