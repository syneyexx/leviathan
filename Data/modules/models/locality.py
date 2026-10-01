"""Execution locality for model routing — distinct from acquisition ModelSource.

ModelSource describes how a model artifact was acquired (downloaded, API, …).
Endpoint locality describes where inference executes (loopback LM Studio vs
public SaaS). Routing ``local_only`` must use execution locality, not source.
"""

from __future__ import annotations

from typing import Any

from Data.modules.models.contracts import ModelDescriptor, ModelSource
from Data.modules.provider_io.endpoint_locality import (
    EndpointLocality,
    classify_endpoint_locality,
)


def model_execution_locality(
    model: ModelDescriptor,
    *,
    settings: Any | None = None,
) -> EndpointLocality:
    """Classify where this model would execute inference."""
    endpoint = (model.endpoint or "").strip()
    if endpoint:
        return classify_endpoint_locality(endpoint, settings=settings)

    # No endpoint: infer from acquisition source + metadata.
    source = model.source
    if source in {ModelSource.LOCAL, ModelSource.IMPORTED, ModelSource.DOWNLOADED, ModelSource.TRAINED}:
        return EndpointLocality.LOCAL_TRUSTED
    if source == ModelSource.API:
        return EndpointLocality.REMOTE
    # REMOTE source without endpoint (e.g. mis-tagged LM Studio) — check provider hints.
    meta = dict(model.metadata or {})
    hint = meta.get("endpoint") or meta.get("baseUrl") or meta.get("base_url")
    if hint:
        return classify_endpoint_locality(str(hint), settings=settings)
    if source == ModelSource.REMOTE:
        # Conservative: unknown remote without endpoint is REMOTE.
        return EndpointLocality.REMOTE
    return EndpointLocality.INVALID


def is_local_execution_eligible(
    model: ModelDescriptor,
    *,
    settings: Any | None = None,
) -> bool:
    """True when local_only routing may select this model."""
    loc = model_execution_locality(model, settings=settings)
    return loc == EndpointLocality.LOCAL_TRUSTED


def acquisition_source_is_local_artifact(source: ModelSource | str) -> bool:
    value = source.value if isinstance(source, ModelSource) else str(source)
    return value in {"local", "imported", "downloaded", "trained"}
