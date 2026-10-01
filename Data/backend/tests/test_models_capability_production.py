"""Production regressions: capability vocabulary, eligibility, effective truth, probe errors."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from Data.modules.models.capability_eligibility import (
    apply_family_capability_inference,
    capability_satisfies_request,
)
from Data.modules.models.capability_probe import CapabilityProbeService
from Data.modules.models.capability_vocabulary import (
    CANONICAL_CAPABILITIES,
    UnknownCapabilityAlias,
    capability_attr,
    normalize_capability_name,
)
from Data.modules.models.contracts import (
    CapabilityState,
    ModelCapabilities,
    ModelDescriptor,
    ModelSource,
    VerifiedCapability,
)
from Data.modules.models.effective_capability import (
    EffectiveProvenance,
    resolve_effective_capability,
)
from Data.modules.models.errors import (
    PROVIDER_AUTH_FAILED,
    PROVIDER_OFFLINE,
    REQUEST_TIMEOUT,
    ModelControlError,
)


# Frontier fields that must survive family inference via dataclasses.replace.
_FRONTIER_ATTRS = (
    "parallel_tool_calls",
    "json_schema_response",
    "reasoning_effort",
    "logprobs",
    "streaming_tool_deltas",
    "multi_candidate",
)


def _all_supported_caps(**overrides: CapabilityState) -> ModelCapabilities:
    kwargs = {attr: CapabilityState.SUPPORTED for attr in ModelCapabilities.__dataclass_fields__}
    kwargs.update(overrides)
    return ModelCapabilities(**kwargs)


def _descriptor(
    model_id: str,
    *,
    display_name: str | None = None,
    capabilities: ModelCapabilities | None = None,
    source: ModelSource = ModelSource.LOCAL,
    metadata: dict | None = None,
    family: str | None = None,
) -> ModelDescriptor:
    return ModelDescriptor(
        id=model_id,
        display_name=display_name or model_id,
        provider_id="lm_studio",
        source=source,
        capabilities=capabilities or ModelCapabilities(),
        family=family,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# capability_vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alias,canonical",
    [
        ("chat", "chat"),
        ("toolCalling", "toolCalling"),
        ("tool_calling", "toolCalling"),
        ("tool-calling", "toolCalling"),
        ("tools", "toolCalling"),
        ("parallelToolCalls", "parallelToolCalls"),
        ("parallel_tool_calls", "parallelToolCalls"),
        ("parallel-tool-calls", "parallelToolCalls"),
        ("structuredOutput", "structuredOutput"),
        ("structured_output", "structuredOutput"),
        ("jsonSchemaResponse", "jsonSchemaResponse"),
        ("json_schema_response", "jsonSchemaResponse"),
        ("json_schema", "jsonSchemaResponse"),
        ("jsonSchema", "jsonSchemaResponse"),
        ("reasoningEffort", "reasoningEffort"),
        ("reasoning_effort", "reasoningEffort"),
        ("logprobs", "logprobs"),
        ("streamingToolDeltas", "streamingToolDeltas"),
        ("streaming_tool_deltas", "streamingToolDeltas"),
        ("multiCandidate", "multiCandidate"),
        ("multi_candidate", "multiCandidate"),
        ("n", "multiCandidate"),
        ("embeddings", "embeddings"),
        ("embedding", "embeddings"),
        ("embed", "embeddings"),
        ("streaming", "streaming"),
        ("stream", "streaming"),
    ],
)
def test_capability_vocabulary_aliases(alias: str, canonical: str) -> None:
    assert normalize_capability_name(alias) == canonical
    assert normalize_capability_name(alias) in CANONICAL_CAPABILITIES


@pytest.mark.parametrize("bad", ["rerank", "reranking", "reranker", "cross_encoder", "cross-encoder"])
def test_rerank_not_mapped_to_embeddings(bad: str) -> None:
    assert normalize_capability_name(bad) is None
    with pytest.raises(UnknownCapabilityAlias):
        normalize_capability_name(bad, strict=True)
    with pytest.raises(UnknownCapabilityAlias):
        capability_attr(bad)


# ---------------------------------------------------------------------------
# apply_family_capability_inference preserves frontier fields
# ---------------------------------------------------------------------------


def test_family_inference_preserves_frontier_non_chat() -> None:
    caps = _all_supported_caps(chat=CapabilityState.UNKNOWN, embeddings=CapabilityState.UNKNOWN)
    model = _descriptor(
        "lm_studio:bge-large",
        display_name="BGE-large-en embedding",
        capabilities=caps,
        family="bge",
    )
    out, provenance = apply_family_capability_inference(caps, model)
    assert out.chat == CapabilityState.UNSUPPORTED
    assert provenance.get("chat") == "inferred_model_family"
    for attr in _FRONTIER_ATTRS:
        assert getattr(out, attr) == CapabilityState.SUPPORTED, attr


def test_family_inference_preserves_frontier_generative() -> None:
    caps = _all_supported_caps(chat=CapabilityState.UNKNOWN)
    model = _descriptor(
        "lm_studio:qwen2.5-14b-instruct",
        display_name="Qwen2.5 Instruct",
        capabilities=caps,
        family="qwen",
    )
    out, provenance = apply_family_capability_inference(caps, model)
    assert out.chat == CapabilityState.UNVERIFIED
    assert provenance.get("chat") == "unverified"
    for attr in _FRONTIER_ATTRS:
        assert getattr(out, attr) == CapabilityState.SUPPORTED, attr


# ---------------------------------------------------------------------------
# hard requirements
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state,ok",
    [
        (CapabilityState.SUPPORTED, True),
        (CapabilityState.UNKNOWN, False),
        (CapabilityState.UNMEASURED, False),
        (CapabilityState.UNSUPPORTED, False),
        (CapabilityState.UNVERIFIED, False),
    ],
)
def test_hard_requirement_states(state: CapabilityState, ok: bool) -> None:
    model = _descriptor(
        "m1",
        capabilities=ModelCapabilities(tool_calling=state, chat=CapabilityState.SUPPORTED),
    )
    decision = capability_satisfies_request(model, "toolCalling", requirement_mode="hard")
    assert decision.satisfies is ok


# ---------------------------------------------------------------------------
# effective_capability
# ---------------------------------------------------------------------------


def test_verified_unsupported_beats_declared_supported() -> None:
    model = _descriptor(
        "m1",
        capabilities=ModelCapabilities(tool_calling=CapabilityState.SUPPORTED),
    )
    verified = VerifiedCapability(
        capability="toolCalling",
        declared=CapabilityState.SUPPORTED,
        verified=CapabilityState.UNSUPPORTED,
        last_tested_at=datetime.now(timezone.utc).isoformat(),
        detail="probe_failed",
    )
    eff = resolve_effective_capability(model, "toolCalling", verified=verified)
    assert eff.state == CapabilityState.UNSUPPORTED
    assert eff.provenance == EffectiveProvenance.VERIFIED_PROBE


def test_verified_supported_routes() -> None:
    model = _descriptor(
        "m1",
        capabilities=ModelCapabilities(tool_calling=CapabilityState.UNKNOWN),
    )
    verified = VerifiedCapability(
        capability="toolCalling",
        declared=CapabilityState.UNKNOWN,
        verified=CapabilityState.SUPPORTED,
        last_tested_at=datetime.now(timezone.utc).isoformat(),
    )
    eff = resolve_effective_capability(model, "toolCalling", verified=verified)
    assert eff.state == CapabilityState.SUPPORTED
    assert eff.provenance == EffectiveProvenance.VERIFIED_PROBE
    decision = capability_satisfies_request(
        model, "toolCalling", verified=verified, requirement_mode="hard"
    )
    assert decision.satisfies is True


def test_stale_verified_unsupported_still_blocks() -> None:
    model = _descriptor(
        "m1",
        capabilities=ModelCapabilities(tool_calling=CapabilityState.SUPPORTED),
    )
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    verified = VerifiedCapability(
        capability="toolCalling",
        declared=CapabilityState.SUPPORTED,
        verified=CapabilityState.UNSUPPORTED,
        last_tested_at=old,
    )
    eff = resolve_effective_capability(
        model, "toolCalling", verified=verified, max_age_seconds=7 * 24 * 3600
    )
    assert eff.stale is True
    assert eff.state == CapabilityState.UNSUPPORTED
    assert eff.provenance == EffectiveProvenance.VERIFIED_PROBE_STALE


def test_stale_verified_supported_falls_through_to_declared() -> None:
    model = _descriptor(
        "m1",
        capabilities=ModelCapabilities(tool_calling=CapabilityState.UNMEASURED),
    )
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    verified = VerifiedCapability(
        capability="toolCalling",
        declared=CapabilityState.UNMEASURED,
        verified=CapabilityState.SUPPORTED,
        last_tested_at=old,
    )
    eff = resolve_effective_capability(
        model, "toolCalling", verified=verified, max_age_seconds=7 * 24 * 3600
    )
    assert eff.stale is False or eff.provenance != EffectiveProvenance.VERIFIED_PROBE
    assert eff.state == CapabilityState.UNMEASURED
    assert eff.provenance == EffectiveProvenance.DECLARED_METADATA


# ---------------------------------------------------------------------------
# CapabilityProbeService._classify_probe_error
# ---------------------------------------------------------------------------


def test_provider_offline_classifies_as_unknown_not_unsupported() -> None:
    verified, detail = CapabilityProbeService._classify_probe_error(
        ModelControlError(code=PROVIDER_OFFLINE, message="connection refused")
    )
    assert verified == CapabilityState.UNKNOWN
    assert "provider_unavailable" in detail
    assert verified != CapabilityState.UNSUPPORTED


def test_auth_and_timeout_also_unknown() -> None:
    auth, _ = CapabilityProbeService._classify_probe_error(
        ModelControlError(code=PROVIDER_AUTH_FAILED, message="401")
    )
    timeout, _ = CapabilityProbeService._classify_probe_error(
        ModelControlError(code=REQUEST_TIMEOUT, message="timed out")
    )
    assert auth == CapabilityState.UNKNOWN
    assert timeout == CapabilityState.UNKNOWN


def test_capability_not_supported_is_unsupported() -> None:
    verified, _ = CapabilityProbeService._classify_probe_error(
        ModelControlError(code="CAPABILITY_NOT_SUPPORTED", message="no tools")
    )
    assert verified == CapabilityState.UNSUPPORTED
