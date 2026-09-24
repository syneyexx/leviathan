"""Context-fit preflight helpers for production inference paths."""

from __future__ import annotations

from typing import Any

from .budget import (
    CONTEXT_WINDOW_EXCEEDED,
    ContextBudgetPlanner,
    ContextFitDecision,
    ContextFitState,
)
from .tokenization import TokenCountResult, TokenizationRequest, TokenizationService


def preflight_context_fit(
    *,
    messages: list[dict[str, Any]],
    model_id: str | None,
    context_window: int | None,
    max_output_tokens: int | None = None,
    profile_max_tokens: int | None = None,
    explicit_selection: bool = False,
    tokenization: TokenizationService | None = None,
    tokenizer_id: str | None = None,
    chat_template_id: str | None = None,
    pinned_tokens: int = 0,
    budget_planner: ContextBudgetPlanner | None = None,
    tools_schema: Any | None = None,
) -> ContextFitDecision:
    """Evaluate whether messages fit the selected model before transport."""
    planner = budget_planner or ContextBudgetPlanner()
    count_result: TokenCountResult | None = None
    if tokenization is not None:
        count_result = tokenization.count(
            TokenizationRequest(
                messages=tuple(messages),
                model_id=model_id,
                tokenizer_id=tokenizer_id,
                chat_template_id=chat_template_id,
                tools_schema=tools_schema,
                add_generation_prompt=True,
            )
        )
        required = count_result.budget_count
    else:
        from .types import estimate_tokens

        required = sum(estimate_tokens(str(m.get("content") or "")) + 4 for m in messages)

    plan = planner.plan(
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        profile_max_tokens=profile_max_tokens,
        count_result=count_result,
    )
    return planner.evaluate_fit(
        plan,
        required_input_tokens=required,
        pinned_tokens=pinned_tokens,
        packed_tokens=required,
        model_id=model_id,
        explicit_selection=explicit_selection,
    )


def raise_if_unfit(decision: ContextFitDecision) -> None:
    """Raise structured CONTEXT_WINDOW_EXCEEDED for unfit explicit/required cases."""
    if decision.ok or decision.state == ContextFitState.UNKNOWN_CONTEXT_CAPACITY:
        return
    from Data.modules.models.errors import ModelControlError

    raise ModelControlError(
        code=CONTEXT_WINDOW_EXCEEDED,
        message=(
            f"Context does not fit selected model "
            f"(state={decision.state.value}, required={decision.required_input_tokens}, "
            f"usable={decision.plan.usable_input_tokens})"
        ),
        model_id=decision.model_id,
        http_status=409,
        details=decision.public_dict(),
    )
