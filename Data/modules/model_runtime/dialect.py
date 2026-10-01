"""Provider dialect adaptation for frontier inference transport (W2).

Maps requested InferenceTransportOptions onto provider payload fields.
Dialect adaptation proves WIRE SHAPE ONLY (transport_mappable).
It does NOT grant model/provider capability authority.

Semantics:
  - transport_mappable: dialect knows how to emit the JSON field
  - feature_states: never claim CapabilityState.SUPPORTED solely because a
    field was emitted — use UNMEASURED for wire-mappable-but-unverified
  - Capability engine / verified probes decide model support
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


# Wire-mappable ≠ model-supported. Dialect emits UNMEASURED for mappable fields.
FEATURE_SUPPORTED = CapabilityState.SUPPORTED.value  # reserved for verified dialects only
FEATURE_TRANSPORT_MAPPABLE = CapabilityState.UNMEASURED.value
FEATURE_UNSUPPORTED = CapabilityState.UNSUPPORTED.value
FEATURE_UNMEASURED = CapabilityState.UNMEASURED.value
FEATURE_UNKNOWN = CapabilityState.UNKNOWN.value


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
    # When True, UNMEASURED (wire-mappable but unverified) hard features also reject.
    reject_unmeasured: bool = False

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
    transport_mappable: dict[str, bool] = field(default_factory=dict)
    rejected: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "dialectId": self.dialect_id,
            "featureStates": dict(self.feature_states),
            "transportMappable": dict(self.transport_mappable),
            "rejected": list(self.rejected),
            "notes": list(self.notes),
            "payloadKeys": sorted(self.payload_fields.keys()),
            "truth": {
                "requested_capability_never_silently_dropped": True,
                "wire_mappable_is_not_model_supported": True,
                "mcp_means_model_context_protocol_not_control_plane": True,
            },
        }


class ProviderDialect:
    """Base dialect — subclasses declare which fields they can emit."""

    dialect_id: str = "base"

    def adapt(self, options: InferenceTransportOptions) -> DialectAdaptation:
        raise NotImplementedError

    def _mark_mappable(
        self,
        *,
        adaptation: DialectAdaptation,
        feature: TransportFeature,
        options: InferenceTransportOptions,
        detail: str | None = None,
    ) -> None:
        """Record that the dialect can emit the wire field — NOT that the model supports it."""
        adaptation.transport_mappable[feature.value] = True
        adaptation.feature_states[feature.value] = FEATURE_TRANSPORT_MAPPABLE
        note = detail or (
            f"dialect '{self.dialect_id}' can emit '{feature.value}' wire field; "
            "model capability must be verified separately"
        )
        adaptation.notes.append(note)
        if options.reject_unmeasured and options.reject_unsupported:
            adaptation.rejected.append(
                {
                    "feature": feature.value,
                    "state": FEATURE_UNMEASURED,
                    "detail": note,
                }
            )
            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message=(
                    f"Transport feature '{feature.value}' is UNMEASURED "
                    f"(wire-mappable only) for dialect '{self.dialect_id}'"
                ),
                details={
                    "feature": feature.value,
                    "dialect": self.dialect_id,
                    "state": FEATURE_UNMEASURED,
                    "transportMappable": True,
                },
            )

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
        adaptation.transport_mappable[feature.value] = False
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
        elif state in {FEATURE_UNMEASURED, FEATURE_UNKNOWN}:
            adaptation.notes.append(detail)
            adaptation.rejected.append(
                {"feature": feature.value, "state": state, "detail": detail}
            )
            if options.reject_unsupported:
                raise ModelControlError(
                    code=CAPABILITY_NOT_SUPPORTED,
                    message=(
                        f"Transport feature '{feature.value}' is {state} "
                        f"for dialect '{self.dialect_id}' and cannot be silently applied"
                    ),
                    details={
                        "feature": feature.value,
                        "dialect": self.dialect_id,
                        "state": state,
                    },
                )


class OpenAICompatibleDialect(ProviderDialect):
    """OpenAI chat.completions-shaped local/remote providers (LM Studio, vLLM, etc.).

    Wire mapping is shared; capability claims are NOT. Each provider still needs
    verified probes / authoritative reports for model support.
    """

    dialect_id = "openai_compatible"

    def adapt(self, options: InferenceTransportOptions) -> DialectAdaptation:
        adaptation = DialectAdaptation(dialect_id=self.dialect_id)
        adaptation.transport_mappable[TransportFeature.USAGE_ACCOUNTING.value] = True
        adaptation.feature_states[
            TransportFeature.USAGE_ACCOUNTING.value
        ] = FEATURE_TRANSPORT_MAPPABLE

        if options.tools is not None or options.tool_choice is not None:
            if options.tools is not None:
                adaptation.payload_fields["tools"] = list(options.tools)
            if options.tool_choice is not None:
                adaptation.payload_fields["tool_choice"] = options.tool_choice
            self._mark_mappable(
                adaptation=adaptation,
                feature=TransportFeature.TOOL_CALLING,
                options=options,
            )

        if options.parallel_tool_calls is not None:
            adaptation.payload_fields["parallel_tool_calls"] = bool(options.parallel_tool_calls)
            self._mark_mappable(
                adaptation=adaptation,
                feature=TransportFeature.PARALLEL_TOOL_CALLS,
                options=options,
            )

        if options.response_format is not None:
            rf = dict(options.response_format)
            adaptation.payload_fields["response_format"] = rf
            self._mark_mappable(
                adaptation=adaptation,
                feature=TransportFeature.JSON_SCHEMA_RESPONSE,
                options=options,
                detail=(
                    "response_format field is wire-mappable; json_schema validity "
                    "requires verified probe — not assumed from dialect"
                ),
            )
            if rf.get("type") == "json_schema" and "json_schema" not in rf:
                adaptation.notes.append(
                    "response_format.type=json_schema without json_schema body — provider may reject"
                )

        if options.reasoning_effort is not None:
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
            self._mark_mappable(
                adaptation=adaptation,
                feature=TransportFeature.LOGPROBS,
                options=options,
            )

        if options.n is not None and int(options.n) > 1:
            adaptation.payload_fields["n"] = int(options.n)
            self._mark_mappable(
                adaptation=adaptation,
                feature=TransportFeature.MULTI_CANDIDATE,
                options=options,
            )
        elif options.n is not None:
            adaptation.payload_fields["n"] = int(options.n)

        if options.prompt_cache_key is not None or options.cache_control is not None:
            detail = (
                "cache hints not mapped for generic openai_compatible — "
                "UNKNOWN until provider profile confirms"
            )
            self._reject_or_mark(
                adaptation=adaptation,
                feature=TransportFeature.CACHE_HINTS,
                state=FEATURE_UNKNOWN,
                detail=detail,
                options=options,
            )

        if options.stream:
            adaptation.payload_fields["stream"] = True
            self._mark_mappable(
                adaptation=adaptation,
                feature=TransportFeature.STREAMING,
                options=options,
            )
            if options.stream_include_usage is not None:
                adaptation.payload_fields["stream_options"] = {
                    "include_usage": bool(options.stream_include_usage)
                }
            if options.tools is not None:
                self._mark_mappable(
                    adaptation=adaptation,
                    feature=TransportFeature.STREAMING_TOOL_DELTAS,
                    options=options,
                    detail=(
                        "stream+tools wire shape is mappable; streamingToolDeltas "
                        "requires verified probe or authoritative provider capability"
                    ),
                )

        return adaptation


class OpenAIReasoningDialect(OpenAICompatibleDialect):
    """OpenAI-compatible endpoints that accept reasoning effort / budget / cache fields."""

    dialect_id = "openai_reasoning"

    def adapt(self, options: InferenceTransportOptions) -> DialectAdaptation:
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
            reject_unmeasured=options.reject_unmeasured,
        )
        adaptation = OpenAICompatibleDialect.adapt(self, base_opts)
        adaptation.dialect_id = self.dialect_id

        if options.reasoning_effort is not None:
            adaptation.payload_fields["reasoning_effort"] = str(options.reasoning_effort)
            self._mark_mappable(
                adaptation=adaptation,
                feature=TransportFeature.REASONING_EFFORT,
                options=options,
            )

        if options.reasoning_max_tokens is not None:
            adaptation.payload_fields["reasoning"] = {
                "max_tokens": int(options.reasoning_max_tokens)
            }
            self._mark_mappable(
                adaptation=adaptation,
                feature=TransportFeature.REASONING_TOKEN_BUDGET,
                options=options,
            )

        if options.prompt_cache_key is not None:
            adaptation.payload_fields["prompt_cache_key"] = str(options.prompt_cache_key)
            self._mark_mappable(
                adaptation=adaptation,
                feature=TransportFeature.CACHE_HINTS,
                options=options,
            )
        elif options.cache_control is not None:
            adaptation.payload_fields["cache_control"] = dict(options.cache_control)
            self._mark_mappable(
                adaptation=adaptation,
                feature=TransportFeature.CACHE_HINTS,
                options=options,
            )

        return adaptation


class UnknownDialect(ProviderDialect):
    """Fail-closed dialect for unrecognized provider ids."""

    dialect_id = "unknown"

    def adapt(self, options: InferenceTransportOptions) -> DialectAdaptation:
        adaptation = DialectAdaptation(dialect_id=self.dialect_id)
        for feature in options.requested_features():
            self._reject_or_mark(
                adaptation=adaptation,
                feature=feature,
                state=FEATURE_UNKNOWN,
                detail=(
                    f"unknown dialect '{self.dialect_id}' does not claim "
                    f"OpenAI-compatible support for '{feature.value}'"
                ),
                options=options,
            )
        adaptation.notes.append(
            "unknown dialect is fail-closed; not treated as generic openai_compatible"
        )
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
        if key not in {"openai_compatible", "openai_reasoning"}:
            wrapped = OpenAICompatibleDialect()
            wrapped.dialect_id = key
            return wrapped
        return _DIALECTS[key]
    unknown = UnknownDialect()
    unknown.dialect_id = key or "unknown"
    return unknown


def adapt_transport(
    options: InferenceTransportOptions,
    *,
    dialect_id: str | None = None,
) -> DialectAdaptation:
    """Adapt requested transport options for the named provider dialect."""
    return get_provider_dialect(dialect_id).adapt(options)
