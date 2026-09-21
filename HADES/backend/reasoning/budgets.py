"""Explicit execution budgets for chat and Work Runtime.

Global user settings are hard ceilings. Profiles and routes may only tighten them.
``None`` means unlimited (no HADES-owned ceiling).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _min_cap(*values: int | None) -> int | None:
    """Return the tightest finite ceiling; None if all unlimited."""
    finite = [int(v) for v in values if v is not None]
    if not finite:
        return None
    return min(finite)


@dataclass(slots=True)
class ExecutionBudget:
    max_model_calls: int | None
    max_tool_rounds: int | None
    max_replans: int | None = 0
    max_repair_attempts: int | None = 2
    reserved_verification_calls: int = 1
    reserved_finalize_calls: int = 1
    model_calls: int = 0
    tool_rounds: int = 0
    replans: int = 0
    repair_attempts: int = 0
    notes: list[str] = field(default_factory=list)
    # Token accounting: measured vs estimate must stay distinct.
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_input_tokens: int | None = None
    estimated_output_tokens: int | None = None
    usage_kind: str = "unavailable"  # exact | estimate | unavailable
    monetary_cost: float | None = None
    monetary_known: bool = False
    leased_model_calls: int = 0
    stop_reason: str | None = None

    def remaining_model_calls(self, *, reserve_verification: bool = False) -> int | None:
        if self.max_model_calls is None:
            return None
        reserved = 0
        if reserve_verification:
            reserved = self.reserved_verification_calls + self.reserved_finalize_calls
        return max(0, int(self.max_model_calls) - self.model_calls - self.leased_model_calls - reserved)

    def can_model_call(self, *, reserve_verification: bool = False) -> bool:
        remaining = self.remaining_model_calls(reserve_verification=reserve_verification)
        return True if remaining is None else remaining > 0

    def record_model_call(self) -> None:
        self.model_calls += 1

    def can_tool_round(self) -> bool:
        if self.max_tool_rounds is None:
            return True
        return self.tool_rounds < int(self.max_tool_rounds)

    def record_tool_round(self) -> None:
        self.tool_rounds += 1

    def can_replan(self) -> bool:
        if self.max_replans is None:
            return True
        return self.replans < int(self.max_replans)

    def record_replan(self) -> None:
        self.replans += 1
        self.notes.append(f"replan:{self.replans}")

    def can_repair(self) -> bool:
        if self.max_repair_attempts is None:
            return True
        return self.repair_attempts < int(self.max_repair_attempts)

    def record_repair(self) -> None:
        self.repair_attempts += 1

    def apply_provider_usage(self, usage: dict[str, Any] | None, *, estimated: dict[str, Any] | None = None) -> None:
        """Record measured provider usage. Missing usage stays unavailable, never €0/0 tokens."""
        if isinstance(usage, dict) and any(
            usage.get(key) is not None for key in ("total_tokens", "prompt_tokens", "completion_tokens", "input_tokens", "output_tokens")
        ):
            prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
            completion = usage.get("completion_tokens", usage.get("output_tokens"))
            try:
                if prompt is not None:
                    self.input_tokens = (self.input_tokens or 0) + int(prompt)
                if completion is not None:
                    self.output_tokens = (self.output_tokens or 0) + int(completion)
            except (TypeError, ValueError):
                pass
            self.usage_kind = "exact"
            cost = usage.get("cost")
            if cost is not None:
                try:
                    self.monetary_cost = float(cost)
                    self.monetary_known = True
                except (TypeError, ValueError):
                    self.monetary_known = False
            return
        if isinstance(estimated, dict):
            self.usage_kind = "estimate"
            try:
                if estimated.get("prompt_tokens") is not None:
                    self.estimated_input_tokens = (self.estimated_input_tokens or 0) + int(estimated["prompt_tokens"])
                if estimated.get("completion_tokens") is not None:
                    self.estimated_output_tokens = (self.estimated_output_tokens or 0) + int(estimated["completion_tokens"])
            except (TypeError, ValueError):
                pass
            return
        if self.usage_kind != "exact":
            self.usage_kind = "unavailable"

    def exhausted_without_success(self) -> bool:
        if self.max_model_calls is None:
            return False
        return self.model_calls >= int(self.max_model_calls) and not self.can_model_call()

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, baseline: "ExecutionBudget | None" = None) -> "ExecutionBudget":
        base = baseline or cls(max_model_calls=None, max_tool_rounds=None)
        if not isinstance(data, dict):
            return base

        def _int(key: str, fallback: int | None) -> int | None:
            raw = data.get(key, fallback)
            if raw is None:
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                return fallback

        restored = cls(
            max_model_calls=_int("max_model_calls", base.max_model_calls),
            max_tool_rounds=_int("max_tool_rounds", base.max_tool_rounds),
            max_replans=_int("max_replans", base.max_replans),
            max_repair_attempts=_int("max_repair_attempts", base.max_repair_attempts),
            reserved_verification_calls=int(data.get("reserved_verification_calls") or base.reserved_verification_calls),
            reserved_finalize_calls=int(data.get("reserved_finalize_calls") or base.reserved_finalize_calls),
            model_calls=int(data.get("model_calls") or 0),
            tool_rounds=int(data.get("tool_rounds") or 0),
            replans=int(data.get("replans") or 0),
            repair_attempts=int(data.get("repair_attempts") or 0),
            notes=list(data.get("notes") or []),
            input_tokens=_int("input_tokens", base.input_tokens),
            output_tokens=_int("output_tokens", base.output_tokens),
            estimated_input_tokens=_int("estimated_input_tokens", base.estimated_input_tokens),
            estimated_output_tokens=_int("estimated_output_tokens", base.estimated_output_tokens),
            usage_kind=str(data.get("usage_kind") or base.usage_kind),
            monetary_cost=float(data["monetary_cost"]) if data.get("monetary_cost") is not None else None,
            monetary_known=bool(data.get("monetary_known")),
            leased_model_calls=int(data.get("leased_model_calls") or 0),
            stop_reason=str(data["stop_reason"]) if data.get("stop_reason") else None,
        )
        return restored

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def begin_model_lease(budget: "ExecutionBudget | None") -> None:
    """Atomically hold one shared model-call unit before a gateway call."""
    from .atomic_budget import shared_budget_pool

    shared_budget_pool.lease("model", 1)
    if budget is not None:
        budget.leased_model_calls = int(getattr(budget, "leased_model_calls", 0) or 0) + 1


def finish_model_lease(
    budget: "ExecutionBudget | None",
    *,
    usage: dict[str, Any] | None = None,
    estimated: dict[str, Any] | None = None,
) -> None:
    from .atomic_budget import shared_budget_pool

    shared_budget_pool.commit_lease("model", 1)
    if budget is None:
        return
    budget.leased_model_calls = max(0, int(getattr(budget, "leased_model_calls", 0) or 0) - 1)
    budget.record_model_call()
    budget.apply_provider_usage(usage, estimated=estimated)


def abort_model_lease(budget: "ExecutionBudget | None") -> None:
    from .atomic_budget import shared_budget_pool

    try:
        shared_budget_pool.release_lease("model", 1)
    except Exception:
        pass
    if budget is not None:
        budget.leased_model_calls = max(0, int(getattr(budget, "leased_model_calls", 0) or 0) - 1)


def scale_execution_budget(budget: ExecutionBudget, next_profile: str) -> bool:
    """Raise Adaptive ceilings toward ``next_profile`` without resetting consumed usage.

    Never lowers a ceiling. Settings/global caps remain the hard max via ``_min_cap``.
    """
    from .profiles import PROFILE_CONFIGS, resolve_profile_config

    config = resolve_profile_config(next_profile) or PROFILE_CONFIGS.get(next_profile)
    if config is None:
        return False
    settings_model = None
    settings_tools = None
    try:
        from control.service import get_control_service

        values = get_control_service().runtime_values()
        settings_model = values.get("max_model_calls_per_task")
        settings_tools = values.get("max_tool_rounds")
    except Exception:
        settings_model = None
        settings_tools = None
    changed = False
    next_model = _min_cap(settings_model, config.max_model_calls)
    if next_model is None:
        if budget.max_model_calls is not None:
            budget.max_model_calls = None
            changed = True
    elif budget.max_model_calls is not None and int(next_model) > int(budget.max_model_calls):
        budget.max_model_calls = int(next_model)
        changed = True
    next_tools = _min_cap(settings_tools, config.max_tool_rounds)
    if next_tools is None:
        if budget.max_tool_rounds is not None:
            budget.max_tool_rounds = None
            changed = True
    elif budget.max_tool_rounds is not None and int(next_tools) > int(budget.max_tool_rounds):
        budget.max_tool_rounds = int(next_tools)
        changed = True
    next_replans = config.max_replans
    if next_replans is None:
        if budget.max_replans is not None:
            budget.max_replans = None
            changed = True
    elif budget.max_replans is not None and int(next_replans) > int(budget.max_replans):
        budget.max_replans = int(next_replans)
        changed = True
    if bool(config.verify) and budget.reserved_verification_calls < 1:
        budget.reserved_verification_calls = 1
        changed = True
    if changed:
        budget.notes.append(f"adaptive_scaled:{next_profile}")
    return changed


def should_restore_execution_budget(
    *,
    prior_resume_run_id: str | None,
    current_client_request_id: str | None,
) -> bool:
    """Restore consumed run counters only for a true same-run resume.

    Conversation working state may persist goals, failures, and open work across
    turns. ``ExecutionBudget`` counters belong to one run identity
    (``client_request_id`` / ``resume_run_id``). A prior ``partial`` /
    ``blocked`` / ``running`` status alone must NOT poison a new turn's budget.
    Both IDs must be non-empty and equal — empty==empty is not a resume.
    """
    prior = str(prior_resume_run_id or "").strip()
    current = str(current_client_request_id or "").strip()
    if not prior or not current:
        return False
    return prior == current


def resolve_tool_round_budget(
    *,
    settings_max_tool_rounds: int | None,
    profile_max_tool_rounds: int | None,
    route_max_tool_rounds: int | None = None,
    tools_allowed: bool = True,
) -> int | None:
    """Hard global ceiling; profile/route may only lower it. 0 disables tools. None = unlimited."""
    if not tools_allowed:
        return 0
    if settings_max_tool_rounds is not None and int(settings_max_tool_rounds) == 0:
        return 0
    return _min_cap(settings_max_tool_rounds, profile_max_tool_rounds, route_max_tool_rounds)


def budget_from_profile(
    *,
    profile_name: str,
    settings_max_tool_rounds: int | None,
    route_max_tool_rounds: int | None = None,
    tools_allowed: bool = True,
    profile_config: Any | None = None,
    settings_max_model_calls: int | None = None,
    max_repair_attempts: int | None = None,
) -> ExecutionBudget:
    from .profiles import PROFILE_CONFIGS, resolve_profile_config

    config = profile_config or resolve_profile_config(profile_name) or PROFILE_CONFIGS.get(profile_name) or PROFILE_CONFIGS["standard"]
    tool_rounds = resolve_tool_round_budget(
        settings_max_tool_rounds=settings_max_tool_rounds,
        profile_max_tool_rounds=config.max_tool_rounds,
        route_max_tool_rounds=route_max_tool_rounds,
        tools_allowed=tools_allowed,
    )
    repair = max_repair_attempts
    if repair is None:
        repair_resolved = False
        try:
            from control.service import get_control_service
            from control.types import SettingSource

            effective = get_control_service().resolve("agents.execution.max_repair_attempts")
            repair_resolved = True
            if effective.unlimited_requested:
                repair = None
            elif effective.configured is None and effective.source != SettingSource.SYSTEM_DEFAULT:
                # Explicit null override = Unlimited.
                repair = None
            else:
                repair = effective.effective
        except Exception:
            repair_resolved = False
        if not repair_resolved:
            repair = 2 if profile_name in {"high", "maximum"} else 1
    model_calls = _min_cap(settings_max_model_calls, config.max_model_calls)
    return ExecutionBudget(
        max_model_calls=model_calls,
        max_tool_rounds=tool_rounds,
        max_replans=config.max_replans,
        max_repair_attempts=repair,
        reserved_verification_calls=1 if bool(config.verify) else 0,
        reserved_finalize_calls=1,
    )
