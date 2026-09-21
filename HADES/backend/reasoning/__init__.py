"""HADES shared reasoning/orchestration kernel.

Deterministic policy, budgets, routing and verification live here.
Semantic synthesis stays with the local LM Studio model.
"""

from .autonomy_policies import (
    PIPELINE_STAGES,
    evaluate_knowledge_write_back,
    evaluate_memory_write,
    reflection_gate,
    stop_and_ask_gate,
    validate_pipeline_progress,
)
from .atomic_budget import BudgetExhausted, SharedBudgetPool, shared_budget_pool
from .budgets import ExecutionBudget, budget_from_profile, resolve_tool_round_budget
from .contracts import (
    BudgetReport,
    ContextItem,
    Plan,
    PlanStep,
    ReasoningProfileName,
    RequestKind,
    RequestSpec,
    RouteDecision,
    ToolCallRequest,
    ToolObservation,
    VerificationResult,
)
from .context import assemble_budgeted_messages, assemble_context_messages, budget_context_items, estimate_chars
from .conversation_state import build_conversation_working_state
from .evidence_coverage import (
    CoverageReport,
    ClaimRecord,
    assess_coverage,
    classify_support,
    extract_checkable_claims,
    stable_claim_id,
)
from .answer_presentation import map_verification_display, present_answer
from .targeted_repair import apply_targeted_qualifiers, build_repair_plan
from .events import RunEvent, RunEventBus, run_event_bus
from .model_gateway import (
    ModelCallCancelled,
    ModelCallFailed,
    ModelCapacityTimeout,
    ModelGateway,
    ModelGatewayError,
    ModelRetriesExhausted,
    model_gateway,
)
from .model_router import ModelRouter, ModelSelection, model_router
from .mode_policy import POLICY_VERSION, parse_mode_input
from .orchestration import ExecutedRoute, finalize_without_tool_json, should_run_verification, should_use_work_runtime
from .profiles import PROFILE_CONFIGS, resolve_reasoning_profile
from .steering import next_steering_action
from .understanding import (
    apply_classifier_overlay,
    build_request_spec,
    build_route_decision,
    extract_task_features,
    maybe_early_stop,
    maybe_escalate_profile,
    parse_classifier_output,
    score_complexity,
)
from .plan_scheduler import (
    PlanValidationError,
    ValidatedPlan,
    diagnose_deadlock,
    execution_waves,
    format_deadlock_error,
    ready_steps,
    validate_plan,
)
from .retrieval import RetrievalFilters, RetrievalHit, RetrievalResult, merge_rank, lexical_score
from .run_control import RunControlCommand, apply_redirect, can_pause_safely, crash_recovery_notes
from .specialists import SPECIALISTS, get_specialist, route_specialist
from .tool_workflows import HandoffResult, ToolStepSpec, evaluate_success, resolve_inputs, validate_against_schema
from .tools import (
    DISCOVER_PLUGIN_ID,
    DISCOVER_TOOL_NAME,
    TOOL_CALL_KEY,
    build_plugin_directory,
    discover_tools,
    observation_from_invoke_result,
    parse_tool_choice,
    render_plugin_directory,
    render_tool_catalog,
    tool_call_request_from_choice,
)
from .verification import (
    apply_critic_outcome,
    build_acceptance_checklist,
    build_verification_prompt,
    parse_verification_result,
    validate_evidence_refs,
    verification_allows_success,
)

__all__ = [
    "BudgetExhausted",
    "BudgetReport",
    "ClaimRecord",
    "ContextItem",
    "CoverageReport",
    "DISCOVER_PLUGIN_ID",
    "DISCOVER_TOOL_NAME",
    "ExecutedRoute",
    "ExecutionBudget",
    "HandoffResult",
    "ModelRouter",
    "ModelSelection",
    "PIPELINE_STAGES",
    "PROFILE_CONFIGS",
    "Plan",
    "PlanStep",
    "PlanValidationError",
    "ReasoningProfileName",
    "RequestKind",
    "RequestSpec",
    "RetrievalFilters",
    "RetrievalHit",
    "RetrievalResult",
    "RouteDecision",
    "RunControlCommand",
    "RunEvent",
    "RunEventBus",
    "SPECIALISTS",
    "SharedBudgetPool",
    "TOOL_CALL_KEY",
    "ToolCallRequest",
    "ToolObservation",
    "ToolStepSpec",
    "ValidatedPlan",
    "VerificationResult",
    "apply_critic_outcome",
    "apply_redirect",
    "apply_targeted_qualifiers",
    "assemble_budgeted_messages",
    "assemble_context_messages",
    "assess_coverage",
    "budget_context_items",
    "build_plugin_directory",
    "budget_from_profile",
    "build_conversation_working_state",
    "build_acceptance_checklist",
    "build_repair_plan",
    "build_request_spec",
    "build_route_decision",
    "build_verification_prompt",
    "can_pause_safely",
    "classify_support",
    "crash_recovery_notes",
    "discover_tools",
    "estimate_chars",
    "evaluate_knowledge_write_back",
    "evaluate_memory_write",
    "evaluate_success",
    "execution_waves",
    "extract_checkable_claims",
    "finalize_without_tool_json",
    "get_specialist",
    "lexical_score",
    "map_verification_display",
    "maybe_early_stop",
    "maybe_escalate_profile",
    "merge_rank",
    "model_gateway",
    "model_router",
    "observation_from_invoke_result",
    "parse_tool_choice",
    "parse_verification_result",
    "present_answer",
    "ready_steps",
    "reflection_gate",
    "render_plugin_directory",
    "render_tool_catalog",
    "resolve_inputs",
    "resolve_reasoning_profile",
    "resolve_tool_round_budget",
    "route_specialist",
    "run_event_bus",
    "score_complexity",
    "shared_budget_pool",
    "should_run_verification",
    "should_use_work_runtime",
    "stable_claim_id",
    "stop_and_ask_gate",
    "tool_call_request_from_choice",
    "validate_against_schema",
    "validate_evidence_refs",
    "validate_pipeline_progress",
    "validate_plan",
    "verification_allows_success",
]
