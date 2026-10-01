"""Production regressions: dialect wire-mappable ≠ model capability SUPPORTED."""

from __future__ import annotations

import pytest

from Data.modules.model_runtime.dialect import (
    FEATURE_TRANSPORT_MAPPABLE,
    FEATURE_UNKNOWN,
    FEATURE_UNMEASURED,
    InferenceTransportOptions,
    TransportFeature,
    adapt_transport,
    get_provider_dialect,
)
from Data.modules.models.errors import CAPABILITY_NOT_SUPPORTED, ModelControlError


def test_mappable_tools_and_logprobs_are_unmeasured_not_supported() -> None:
    opts = InferenceTransportOptions(
        tools=[{"type": "function", "function": {"name": "ping", "parameters": {}}}],
        tool_choice="auto",
        parallel_tool_calls=True,
        logprobs=True,
        top_logprobs=2,
        n=3,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "ok", "schema": {"type": "object"}},
        },
    )
    result = adapt_transport(opts, dialect_id="openai_compatible")
    for feature in (
        TransportFeature.TOOL_CALLING,
        TransportFeature.PARALLEL_TOOL_CALLS,
        TransportFeature.LOGPROBS,
        TransportFeature.MULTI_CANDIDATE,
        TransportFeature.JSON_SCHEMA_RESPONSE,
    ):
        state = result.feature_states[feature.value]
        assert state == FEATURE_UNMEASURED
        assert state == FEATURE_TRANSPORT_MAPPABLE
        assert state != "supported"
        assert result.transport_mappable[feature.value] is True


def test_transport_mappable_true_for_wire_fields() -> None:
    opts = InferenceTransportOptions(
        tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
        logprobs=True,
        stream=True,
    )
    result = adapt_transport(opts, dialect_id="lm_studio")
    assert result.transport_mappable[TransportFeature.TOOL_CALLING.value] is True
    assert result.transport_mappable[TransportFeature.LOGPROBS.value] is True
    assert result.transport_mappable[TransportFeature.STREAMING.value] is True
    assert result.transport_mappable[TransportFeature.STREAMING_TOOL_DELTAS.value] is True
    assert "tools" in result.payload_fields
    assert "logprobs" in result.payload_fields


def test_unknown_dialect_fail_closed() -> None:
    opts = InferenceTransportOptions(
        tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
        reject_unsupported=True,
    )
    with pytest.raises(ModelControlError) as exc:
        adapt_transport(opts, dialect_id="totally_unknown_provider_xyz")
    assert exc.value.code == CAPABILITY_NOT_SUPPORTED

    dialect = get_provider_dialect("totally_unknown_provider_xyz")
    assert dialect.dialect_id == "totally_unknown_provider_xyz"
    soft = InferenceTransportOptions(
        tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
        reject_unsupported=False,
    )
    adaptation = dialect.adapt(soft)
    assert adaptation.feature_states[TransportFeature.TOOL_CALLING.value] in {
        FEATURE_UNKNOWN,
        FEATURE_UNMEASURED,
    }
    assert adaptation.transport_mappable.get(TransportFeature.TOOL_CALLING.value) is False
    assert "tools" not in adaptation.payload_fields


def test_resource_estimate_disagreement_keys() -> None:
    """Canonical Leviathan key is vramNeededBytes; provider uses estimatedGpuMemoryBytes."""
    from Data.modules.models.contracts import ResourceEstimate, ResourceProvenance

    est = ResourceEstimate(
        vram_needed_bytes=8 * 1024**3,
        vram_needed_provenance=ResourceProvenance.ESTIMATED,
    )
    pub = est.public_dict()
    assert "vramNeededBytes" in pub
    assert pub["vramNeededBytes"] == 8 * 1024**3
    assert "estimatedGpuMemoryBytes" not in pub

    # Disagreement math used by control_plane.estimate_model_load
    provider_gpu = 12 * 1024**3
    leviathan_vram = pub["vramNeededBytes"]
    disagree_pct = abs(provider_gpu - leviathan_vram) / max(provider_gpu, leviathan_vram)
    assert disagree_pct > 0.25
