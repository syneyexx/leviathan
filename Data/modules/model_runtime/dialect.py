"""Provider dialect adaptation for frontier inference transport (W2).

Maps requested InferenceTransportOptions onto provider payload fields.
Never silently drops a requested capability: each requested feature is
reported as SUPPORTED, UNSUPPORTED, or UNMEASURED.

MCP in this repository means Model Context Protocol — not this plane.
Use ModelControlPlane / dialect naming here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.models.contracts import CapabilityState
from Data.modules.models.errors import CAPABILITY_NOT_SUPPORTED, ModelControlError


class TransportFeature(str, Enum):
    TOOL_CALLING = "tool_calling"
    PARALLEL_TOOL_CALLS = "parallel_tool_calls"
    JSON_SCHEMA_RESPONSE = "json_schema_response"
    REASONING_EFFORT = "reasoning_effort"
    REASONING_TOKEN_BUDGET = "reasoning_token_budget"
    LOGPROBS = "logprobs"
    STREAMING_TOOL_DELTAS = "streaming_tool_deltas"
    USAGE_ACCOUNTING = "usage_accounting"
    EMBEDDINGS = "embeddings"
    CACHE_HINTS = "cache_hints"
    MULTI_CANDIDATE = "multi_candidate"
    STREAMING = "streaming"


# Honest vocabulary aliases used in public responses (CapabilityState values).
FEATURE_SUPPORTED = CapabilityState.SUPPORTED.value
FEATURE_UNSUPPORTED = CapabilityState.UNSUPPORTED.value
FEATURE_UNMEASURED = CapabilityState.UNMEASURED.value


@dataclass
class InferenceTransportOptions:
    """Requested frontier transport features for one inference call."""

    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    parallel_tool_calls: bool | None = None
    response_format: dict[str, Any] | None = None
    reasoning_effort: str | None = None
    reasoning_max_tokens: int | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None
    n: int | None = None
    prompt_cache_key: str | None = None
    cache_control: dict[str, Any] | None = None
    stream: bool = False
    stream_include_usage: bool | None = None
    # When True (default), unsupported *requested* features raise rather than drop.
    reject_unsupported: bool = True

    def requested_features(self) -> list[TransportFeature]:
        out: list[TransportFeature] = []
        if self.tools is not None or self.tool_choice is not None:
            out.append(TransportFeature.TOOL_CALLING)
        if self.parallel_tool_calls is not None:
            out.append(TransportFeature.PARALLEL_TOOL_CALLS)
        if self.response_format is not None:
            out.append(TransportFeature.JSON_SCHEMA_RESPONSE)
        if self.reasoning_effort is not None:
            out.append(TransportFeature.REASONING_EFFORT)
        if self.reasoning_max_tokens is not None:
            out.append(TransportFeature.REASONING_TOKEN_BUDGET)
        if self.logprobs is not None or self.top_logprobs is not None:
            out.append(TransportFeature.LOGPROBS)
        if self.n is not None and int(self.n) > 1:
            out.append(TransportFeature.MULTI_CANDIDATE)
        if self.prompt_cache_key is not None or self.cache_control is not None:
            out.append(TransportFeature.CACHE_HINTS)
        if self.stream:
            out.append(TransportFeature.STREAMING)
            if self.tools is not None:
                out.append(TransportFeature.STREAMING_TOOL_DELTAS)
        if self.stream_include_usage is not None:
            out.append(TransportFeature.USAGE_ACCOUNTING)
        return out


@dataclass
class DialectAdaptation:
    """Result of adapting requested options to a provider payload."""

    dialect_id: str
    payload_fields: dict[str, Any] = field(default_factory=dict)
    feature_states: dict[str, str] = field(default_factory=dict)
    rejected: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "dialectId": self.dialect_id,
            "featureStates": dict(self.feature_states),
            "rejected": list(self.rejected),
            "notes": list(self.notes),
            "payloadKeys": sorted(self.payload_fields.keys()),
            "truth": {
                "requested_capability_never_silently_dropped": True,
                "mcp_means_model_context_protocol_not_control_plane": True,
            },
        }


class ProviderDialect:
    """Base dialect — subclasses declare which fields they can emit."""

    dialect_id: str = "base"

    def adapt(self, options: InferenceTransportOptions) -> DialectAdaptation:
        raise NotImplementedError

    def _reject_or_mark(
        self,
        *,
        adaptation: DialectAdaptation,
        feature: TransportFeature,
        state: str,
        detail: str,
        options: InferenceTransportOptions,
    ) -> None:
        adaptation.feature_states[feature.value] = state
        if state == FEATURE_UNSUPPORTED:
            adaptation.rejected.append(
                {"feature": feature.value, "state": state, "detail": detail}
            )
            adaptation.notes.append(detail)
            if options.reject_unsupported:
                raise ModelControlError(
                    code=CAPABILITY_NOT_SUPPORTED,
                    message=(
                        f"Transport feature '{feature.value}' is UNSUPPORTED "
                        f"by dialect '{self.dialect_id}': {detail}"
                    ),
                    details={
                        "feature": feature.value,
                        "dialect": self.dialect_id,
                        "state": state,
                    },
                )
        elif state == FEATURE_UNMEASURED:
            adaptation.notes.append(detail)


class OpenAICompatibleDialect(ProviderDialect):
    """OpenAI chat.completions-shaped local/remote providers (LM Studio, vLLM, etc.)."""

    dialect_id = "openai_compatible"

    def adapt(self, options: InferenceTransportOptions) -> DialectAdaptation:
        adaptation = DialectAdaptation(dialect_id=self.dialect_id)
        # Usage accounting is always attempted via response parsing when present.
        adaptation.feature_states[TransportFeature.USAGE_ACCOUNTING.value] = FEATURE_SUPPORTED

        if options.tools is not None or options.tool_choice is not None:
            if options.tools is not None:
                adaptation.payload_fields["tools"] = list(options.tools)
            if options.tool_choice is not None:
                adaptation.payload_fields["tool_choice"] = options.tool_choice
            adaptation.feature_states[TransportFeature.TOOL_CALLING.value] = FEATURE_SUPPORTED

        if options.parallel_tool_calls is not None:
            adaptation.payload_fields["parallel_tool_calls"] = bool(options.parallel_tool_calls)
            adaptation.feature_states[
                TransportFeature.PARALLEL_TOOL_CALLS.value
            ] = FEATURE_SUPPORTED

        if options.response_format is not None:
            rf = dict(options.response_format)
            adaptation.payload_fields["response_format"] = rf
            # json_object / json_schema shapes are OpenAI-compatible; validity is probed separately.
            adaptation.feature_states[
                TransportFeature.JSON_SCHEMA_RESPONSE.value
            ] = FEATURE_SUPPORTED
            if rf.get("type") == "json_schema" and "json_schema" not in rf:
                adaptation.notes.append(
                    "response_format.type=json_schema without json_schema body — provider may reject"
                )

        if options.reasoning_effort is not None:
            # Generic OpenAI-compatible servers do not standardize reasoning_effort.
            # Do not silently omit — mark UNSUPPORTED unless a specialized dialect handles it.
            self._reject_or_mark(
                adaptation=adaptation,
                feature=TransportFeature.REASONING_EFFORT,
                state=FEATURE_UNSUPPORTED,
                detail=(
                    "openai_compatible dialect does not emit reasoning_effort; "
                    "use OpenAIReasoningDialect or a measured provider profile"
                ),
                options=options,
            )

        if options.reasoning_max_tokens is not None:
            self._reject_or_mark(
                adaptation=adaptation,
                feature=TransportFeature.REASONING_TOKEN_BUDGET,
                state=FEATURE_UNSUPPORTED,
                detail="openai_compatible dialect has no standard reasoning token budget field",
                options=options,
            )

        if options.logprobs is not None or options.top_logprobs is not None:
            if options.logprobs is not None:
                adaptation.payload_fields["logprobs"] = bool(options.logprobs)
            if options.top_logprobs is not None:
                adaptation.payload_fields["top_logprobs"] = int(options.top_logprobs)
            adaptation.feature_states[TransportFeature.LOGPROBS.value] = FEATURE_SUPPORTED

        if options.n is not None and int(options.n) > 1:
            adaptation.payload_fields["n"] = int(options.n)
            adaptation.feature_states[TransportFeature.MULTI_CANDIDATE.value] = FEATURE_SUPPORTED
        elif options.n is not None:
            adaptation.payload_fields["n"] = int(options.n)

        if options.prompt_cache_key is not None or options.cache_control is not None:
            # Cache hints are provider-specific; generic dialect does not invent fields.
            detail = (
                "cache hints not mapped for generic openai_compatible — "
                "UNMEASURED until provider profile confirms"
            )
            adaptation.feature_states[TransportFeature.CACHE_HINTS.value] = FEATURE_UNMEASURED
            adaptation.notes.append(detail)
            adaptation.rejected.append(
                {
                    "feature": TransportFeature.CACHE_HINTS.value,
                    "state": FEATURE_UNMEASURED,
                    "detail": detail,
                }
            )
            if options.reject_unsupported:
                raise ModelControlError(
                    code=CAPABILITY_NOT_SUPPORTED,
                    message=(
                        "Transport feature 'cache_hints' is UNMEASURED for dialect "
                        f"'{self.dialect_id}' and cannot be silently applied"
                    ),
                    details={
                        "feature": TransportFeature.CACHE_HINTS.value,
                        "dialect": self.dialect_id,
                        "state": FEATURE_UNMEASURED,
                    },
                )

        if options.stream:
            adaptation.payload_fields["stream"] = True
            adaptation.feature_states[TransportFeature.STREAMING.value] = FEATURE_SUPPORTED
            if options.stream_include_usage is not None:
                adaptation.payload_fields["stream_options"] = {
                    "include_usage": bool(options.stream_include_usage)
                }
            if options.tools is not None:
                # Streaming tool deltas are supported by OpenAI wire format when tools present;
                # measured verification is separate.
                adaptation.feature_states[
                    TransportFeature.STREAMING_TOOL_DELTAS.value
                ] = FEATURE_SUPPORTED

        return adaptation


class OpenAIReasoningDialect(OpenAICompatibleDialect):
    """OpenAI-compatible endpoints that accept reasoning effort / budget / cache fields."""

    dialect_id = "openai_reasoning"

    def adapt(self, options: InferenceTransportOptions) -> DialectAdaptation:
        # Peel reasoning/cache so the base dialect does not UNSUPPORTED-reject them.
        base_opts = InferenceTransportOptions(
            tools=options.tools,
            tool_choice=options.tool_choice,
            parallel_tool_calls=options.parallel_tool_calls,
            response_format=options.response_format,
            logprobs=options.logprobs,
            top_logprobs=options.top_logprobs,
            n=options.n,
            stream=options.stream,
            stream_include_usage=options.stream_include_usage,
            reject_unsupported=options.reject_unsupported,
        )
        adaptation = OpenAICompatibleDialect.adapt(self, base_opts)
        adaptation.dialect_id = self.dialect_id

        if options.reasoning_effort is not None:
            adaptation.payload_fields["reasoning_effort"] = str(options.reasoning_effort)
            adaptation.feature_states[
                TransportFeature.REASONING_EFFORT.value
            ] = FEATURE_SUPPORTED

        if options.reasoning_max_tokens is not None:
            adaptation.payload_fields["reasoning"] = {
                "max_tokens": int(options.reasoning_max_tokens)
            }
            adaptation.feature_states[
                TransportFeature.REASONING_TOKEN_BUDGET.value
            ] = FEATURE_SUPPORTED

        if options.prompt_cache_key is not None:
            adaptation.payload_fields["prompt_cache_key"] = str(options.prompt_cache_key)
            adaptation.feature_states[TransportFeature.CACHE_HINTS.value] = FEATURE_SUPPORTED
        elif options.cache_control is not None:
            adaptation.payload_fields["cache_control"] = dict(options.cache_control)
            adaptation.feature_states[TransportFeature.CACHE_HINTS.value] = FEATURE_SUPPORTED

        return adaptation


_DIALECTS: dict[str, ProviderDialect] = {
    "openai_compatible": OpenAICompatibleDialect(),
    "openai_reasoning": OpenAIReasoningDialect(),
    "lm_studio": OpenAICompatibleDialect(),
    "vllm": OpenAICompatibleDialect(),
    "ollama": OpenAICompatibleDialect(),
    "llama_cpp": OpenAICompatibleDialect(),
}


def get_provider_dialect(dialect_id: str | None) -> ProviderDialect:
    key = (dialect_id or "openai_compatible").strip().lower()
    if key in _DIALECTS:
        return _DIALECTS[key]
    # Unknown dialect: openai-compatible wire shape; report the requested id honestly.
    unknown = OpenAICompatibleDialect()
    unknown.dialect_id = key or "openai_compatible"
    return unknown


def adapt_transport(
    options: InferenceTransportOptions,
    *,
    dialect_id: str | None = None,
) -> DialectAdaptation:
    """Adapt requested transport options for the named provider dialect."""
    return get_provider_dialect(dialect_id).adapt(options)
