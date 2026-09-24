"""Model-aware context budget planning and fit preflight."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .tokenization import TokenCountResult, TokenPrecision


class ContextFitState(str, Enum):
    FIT = "FIT"
    FIT_AFTER_COMPACTION = "FIT_AFTER_COMPACTION"
    FIT_AFTER_RETRIEVAL_TRIM = "FIT_AFTER_RETRIEVAL_TRIM"
    TOO_LARGE_PINNED_CONTEXT = "TOO_LARGE_PINNED_CONTEXT"
    TOO_LARGE_FOR_SELECTED_MODEL = "TOO_LARGE_FOR_SELECTED_MODEL"
    UNKNOWN_CONTEXT_CAPACITY = "UNKNOWN_CONTEXT_CAPACITY"


CONTEXT_WINDOW_EXCEEDED = "CONTEXT_WINDOW_EXCEEDED"


@dataclass(frozen=True)
class ContextBudgetPlan:
    context_window: int | None
    reserved_output_tokens: int
    template_overhead_tokens: int
    uncertainty_margin_tokens: int
    usable_input_tokens: int
    count_precision: TokenPrecision
    count_source: str
    response_request_tokens: int | None = None
    profile_max_tokens: int | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "contextWindow": self.context_window,
            "reservedOutputTokens": self.reserved_output_tokens,
            "templateOverheadTokens": self.template_overhead_tokens,
            "uncertaintyMarginTokens": self.uncertainty_margin_tokens,
            "usableInputTokens": self.usable_input_tokens,
            "countPrecision": self.count_precision.value,
            "countSource": self.count_source,
            "responseRequestTokens": self.response_request_tokens,
            "profileMaxTokens": self.profile_max_tokens,
            "diagnostics": dict(self.diagnostics),
            "truth": {
                "negative_budget_hidden": False,
                "percentage_cannot_exceed_window": True,
            },
        }


@dataclass(frozen=True)
class ContextFitDecision:
    state: ContextFitState
    plan: ContextBudgetPlan
    required_input_tokens: int
    packed_tokens: int | None = None
    model_id: str | None = None
    explicit_selection: bool = False
    error_code: str | None = None
    operator_actions: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.state in {
            ContextFitState.FIT,
            ContextFitState.FIT_AFTER_COMPACTION,
            ContextFitState.FIT_AFTER_RETRIEVAL_TRIM,
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "ok": self.ok,
            "plan": self.plan.public_dict(),
            "requiredInputTokens": self.required_input_tokens,
            "packedTokens": self.packed_tokens,
            "modelId": self.model_id,
            "explicitSelection": self.explicit_selection,
            "errorCode": self.error_code,
            "operatorActions": list(self.operator_actions),
            "details": dict(self.details),
        }


class ContextBudgetPlanner:
    """Derive usable input budget before ContextBuilder packing."""

    def __init__(
        self,
        *,
        max_context_fraction: float = 0.72,
        reserve_response_fraction: float = 0.18,
        minimum_response_tokens: int = 256,
        default_reserve_response_tokens: int = 512,
        uncertainty_margin_ratio: float = 0.03,
        uncertainty_margin_min: int = 8,
    ) -> None:
        self.max_context_fraction = float(max_context_fraction)
        self.reserve_response_fraction = float(reserve_response_fraction)
        self.minimum_response_tokens = max(0, int(minimum_response_tokens))
        self.default_reserve_response_tokens = int(default_reserve_response_tokens)
        self.uncertainty_margin_ratio = float(uncertainty_margin_ratio)
        self.uncertainty_margin_min = int(uncertainty_margin_min)

    def plan(
        self,
        *,
        context_window: int | None,
        max_output_tokens: int | None = None,
        profile_max_tokens: int | None = None,
        operator_response_tokens: int | None = None,
        template_overhead_tokens: int = 0,
        count_result: TokenCountResult | None = None,
        auto_budget: bool = True,
        fixed_token_budget: int | None = None,
    ) -> ContextBudgetPlan:
        precision = count_result.precision if count_result else TokenPrecision.HEURISTIC
        count_source = count_result.source.value if count_result else "heuristic_chars4"

        # Resolve reserved output: operator request > profile > fraction/floor.
        candidates = [v for v in (operator_response_tokens, max_output_tokens, profile_max_tokens) if v is not None]
        requested = max(candidates) if candidates else None

        diagnostics: dict[str, Any] = {}
        window_i: int | None
        try:
            window_i = int(context_window) if context_window is not None else None
        except (TypeError, ValueError):
            window_i = None

        if window_i is not None and window_i < 0:
            raise ValueError("context_window cannot be negative")

        template_overhead = max(0, int(template_overhead_tokens))

        if precision in {
            TokenPrecision.EXACT_LOCAL_TOKENIZER,
            TokenPrecision.EXACT_RUNTIME_TOKENIZER,
            TokenPrecision.PROVIDER_REPORTED,
        }:
            uncertainty = 0
        else:
            # Margin applied against window when known; else absolute floor.
            base_for_margin = window_i or (requested or self.default_reserve_response_tokens)
            uncertainty = max(self.uncertainty_margin_min, int(base_for_margin * self.uncertainty_margin_ratio))

        if window_i is None or window_i < 256 or not auto_budget:
            # Fixed / unknown-window path
            reserve = int(requested) if requested is not None else self.default_reserve_response_tokens
            reserve = max(self.minimum_response_tokens, reserve)
            if fixed_token_budget is not None:
                usable = max(0, int(fixed_token_budget) - template_overhead - uncertainty)
                # Historical ContextBuilder contract: caller token_budget may already be usable pack.
                if fixed_token_budget is not None and requested is None:
                    usable = max(0, int(fixed_token_budget) - template_overhead - uncertainty)
            else:
                base = fixed_token_budget if fixed_token_budget is not None else 6000
                usable = max(0, int(base) - reserve - template_overhead - uncertainty)
            diagnostics["mode"] = "fixed_or_unknown_window"
            return ContextBudgetPlan(
                context_window=window_i,
                reserved_output_tokens=reserve,
                template_overhead_tokens=template_overhead,
                uncertainty_margin_tokens=uncertainty,
                usable_input_tokens=usable,
                count_precision=precision,
                count_source=count_source,
                response_request_tokens=operator_response_tokens,
                profile_max_tokens=profile_max_tokens,
                diagnostics=diagnostics,
            )

        # Auto model-aware path
        frac = min(1.0, max(0.05, self.max_context_fraction))
        reserve_frac = min(1.0, max(0.0, self.reserve_response_fraction))
        pack_cap = max(256, int(window_i * frac))
        if requested is not None:
            reserve = max(self.minimum_response_tokens, int(requested))
        else:
            reserve = max(self.minimum_response_tokens, int(window_i * reserve_frac))

        # Never let reserve + overhead + margin exceed the window silently.
        overhead_total = template_overhead + uncertainty
        if reserve + overhead_total >= window_i:
            # Invalid: response reserve alone cannot fit — surface via usable=0 + diagnostics.
            diagnostics["mode"] = "auto_fraction"
            diagnostics["error"] = "reserve_plus_overhead_exceeds_window"
            return ContextBudgetPlan(
                context_window=window_i,
                reserved_output_tokens=reserve,
                template_overhead_tokens=template_overhead,
                uncertainty_margin_tokens=uncertainty,
                usable_input_tokens=0,
                count_precision=precision,
                count_source=count_source,
                response_request_tokens=operator_response_tokens,
                profile_max_tokens=profile_max_tokens,
                diagnostics=diagnostics,
            )

        usable = window_i - reserve - overhead_total
        # Also respect pack fraction ceiling.
        usable = min(usable, pack_cap)
        if fixed_token_budget is not None:
            usable = min(usable, max(0, int(fixed_token_budget)))

        if usable < 0:
            usable = 0
            diagnostics["error"] = "negative_budget_clamped_to_zero"

        diagnostics["mode"] = "auto_fraction"
        diagnostics["pack_cap"] = pack_cap
        return ContextBudgetPlan(
            context_window=window_i,
            reserved_output_tokens=reserve,
            template_overhead_tokens=template_overhead,
            uncertainty_margin_tokens=uncertainty,
            usable_input_tokens=int(usable),
            count_precision=precision,
            count_source=count_source,
            response_request_tokens=operator_response_tokens,
            profile_max_tokens=profile_max_tokens,
            diagnostics=diagnostics,
        )

    def evaluate_fit(
        self,
        plan: ContextBudgetPlan,
        *,
        required_input_tokens: int,
        pinned_tokens: int = 0,
        packed_tokens: int | None = None,
        model_id: str | None = None,
        explicit_selection: bool = False,
        after_compaction: bool = False,
        after_retrieval_trim: bool = False,
    ) -> ContextFitDecision:
        required = int(required_input_tokens)
        actions: list[str] = []

        if plan.context_window is None:
            return ContextFitDecision(
                state=ContextFitState.UNKNOWN_CONTEXT_CAPACITY,
                plan=plan,
                required_input_tokens=required,
                packed_tokens=packed_tokens,
                model_id=model_id,
                explicit_selection=explicit_selection,
                details={"note": "context_window_unknown_budget_best_effort"},
            )

        if pinned_tokens > plan.usable_input_tokens:
            actions = [
                "reduce_pinned_constraints",
                "select_larger_context_model",
                "lower_response_reserve",
            ]
            return ContextFitDecision(
                state=ContextFitState.TOO_LARGE_PINNED_CONTEXT,
                plan=plan,
                required_input_tokens=required,
                packed_tokens=packed_tokens,
                model_id=model_id,
                explicit_selection=explicit_selection,
                error_code=CONTEXT_WINDOW_EXCEEDED,
                operator_actions=tuple(actions),
                details={
                    "pinnedTokens": pinned_tokens,
                    "usableInputTokens": plan.usable_input_tokens,
                    "contextWindow": plan.context_window,
                    "reservedOutput": plan.reserved_output_tokens,
                },
            )

        if required <= plan.usable_input_tokens:
            if after_compaction:
                state = ContextFitState.FIT_AFTER_COMPACTION
            elif after_retrieval_trim:
                state = ContextFitState.FIT_AFTER_RETRIEVAL_TRIM
            else:
                state = ContextFitState.FIT
            return ContextFitDecision(
                state=state,
                plan=plan,
                required_input_tokens=required,
                packed_tokens=packed_tokens,
                model_id=model_id,
                explicit_selection=explicit_selection,
            )

        actions = [
            "compact_history",
            "trim_retrieval",
            "select_larger_context_model" if not explicit_selection else "keep_explicit_model_or_reduce_input",
            "lower_max_output_tokens",
        ]
        return ContextFitDecision(
            state=ContextFitState.TOO_LARGE_FOR_SELECTED_MODEL,
            plan=plan,
            required_input_tokens=required,
            packed_tokens=packed_tokens,
            model_id=model_id,
            explicit_selection=explicit_selection,
            error_code=CONTEXT_WINDOW_EXCEEDED,
            operator_actions=tuple(actions),
            details={
                "usableInputTokens": plan.usable_input_tokens,
                "contextWindow": plan.context_window,
                "reservedOutput": plan.reserved_output_tokens,
                "requiredInputTokens": required,
            },
        )
