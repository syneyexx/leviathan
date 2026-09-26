"""Model runtime — canonical provider-facing model access + managed serving."""

from .durable_requests import (
    DurableRequestLedger,
    DurableRequestStatus,
    DurableServingRequest,
    get_durable_request_ledger,
    reset_durable_request_ledger_for_tests,
)
from .latency import LatencyBreakdown, LatencyTimer
from .openai_compatible import LLMUnavailable, OpenAICompatibleLLM
from .dialect import (
    DialectAdaptation,
    InferenceTransportOptions,
    OpenAICompatibleDialect,
    OpenAIReasoningDialect,
    TransportFeature,
    adapt_transport,
    get_provider_dialect,
)
from .inference_contract import (
    CONTEXT_TRUNCATED,
    STRUCTURED_RESPONSE_UNAVAILABLE,
    TOOL_CALLING_DROPPED,
    ContextBoundSignal,
    ContextOverflowPolicy,
    StructuredResponseResult,
    ToolCallingRecord,
    deterministic_json_repair,
    enforce_context_bounds,
    enforce_structured_response,
    probe_tool_calling_transport,
    record_tool_calling_response,
)
from .serving import (
    InferenceJobClass,
    ServingSupervisor,
    ServingWorker,
    StreamCancelToken,
    WorkerState,
    get_serving_supervisor,
    reset_serving_supervisor_for_tests,
)
from .streaming import chat_truth, sse_encode

# ManagedLocalServingAdapter imported lazily by providers to avoid circular imports
# with Data.modules.models. Re-export via attribute for convenience.


def __getattr__(name: str):
    if name == "ManagedLocalServingAdapter":
        from .managed_adapter import ManagedLocalServingAdapter

        return ManagedLocalServingAdapter
    raise AttributeError(name)


__all__ = [
    "CONTEXT_TRUNCATED",
    "ContextBoundSignal",
    "ContextOverflowPolicy",
    "DialectAdaptation",
    "DurableRequestLedger",
    "DurableRequestStatus",
    "DurableServingRequest",
    "InferenceJobClass",
    "InferenceTransportOptions",
    "LatencyBreakdown",
    "LatencyTimer",
    "LLMUnavailable",
    "ManagedLocalServingAdapter",
    "OpenAICompatibleDialect",
    "OpenAICompatibleLLM",
    "OpenAIReasoningDialect",
    "STRUCTURED_RESPONSE_UNAVAILABLE",
    "ServingSupervisor",
    "ServingWorker",
    "StreamCancelToken",
    "StructuredResponseResult",
    "TOOL_CALLING_DROPPED",
    "ToolCallingRecord",
    "TransportFeature",
    "WorkerState",
    "adapt_transport",
    "chat_truth",
    "deterministic_json_repair",
    "enforce_context_bounds",
    "enforce_structured_response",
    "get_durable_request_ledger",
    "get_provider_dialect",
    "get_serving_supervisor",
    "probe_tool_calling_transport",
    "record_tool_calling_response",
    "reset_durable_request_ledger_for_tests",
    "reset_serving_supervisor_for_tests",
    "sse_encode",
]
