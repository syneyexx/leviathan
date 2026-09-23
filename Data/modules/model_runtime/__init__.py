"""Model runtime — canonical provider-facing model access + managed serving."""

from .openai_compatible import LLMUnavailable, OpenAICompatibleLLM
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
    "InferenceJobClass",
    "LLMUnavailable",
    "ManagedLocalServingAdapter",
    "OpenAICompatibleLLM",
    "ServingSupervisor",
    "ServingWorker",
    "StreamCancelToken",
    "WorkerState",
    "chat_truth",
    "get_serving_supervisor",
    "reset_serving_supervisor_for_tests",
    "sse_encode",
]
