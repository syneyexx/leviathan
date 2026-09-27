"""Remote chat helpers for agents — consume provider_io, never own SDKs."""

from __future__ import annotations

from typing import Any

from Data.modules.provider_io.facade import ProviderExecutionClient
from Data.modules.provider_io.types import ProviderExecutionResult


def complete_remote_chat(
    job_runtime: Any,
    *,
    endpoint: str,
    messages: list[dict[str, Any]],
    model: str | None = None,
    provider: str = "openai_compatible",
    credential_ref: str | None = "llm",
    max_tokens: int | None = None,
    temperature: float | None = None,
    deadline_seconds: float | None = None,
    correlation_id: str | None = None,
    principal_ref: str | None = None,
) -> ProviderExecutionResult:
    """Non-streaming remote completion via provider_io workers.

    Private-host / SSRF privilege is resolved solely from trusted configuration
    (endpoint allowlist / operator env) inside the provider executor — callers
    cannot request ``allow_private_hosts``.
    """
    client = ProviderExecutionClient(job_runtime)
    payload: dict[str, Any] = {
        "endpoint": endpoint,
        "messages": messages,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature
    return client.submit_and_wait(
        provider=provider,
        capability="chat.complete",
        payload=payload,
        model=model,
        credential_ref=credential_ref,
        deadline_seconds=deadline_seconds,
        correlation_id=correlation_id,
        principal_ref=principal_ref,
        latency_class="interactive",
        idempotency_class="NON_IDEMPOTENT_WRITE",
    )


def stream_remote_chat(
    job_runtime: Any,
    *,
    endpoint: str,
    messages: list[dict[str, Any]],
    model: str | None = None,
    provider: str = "openai_compatible",
    credential_ref: str | None = "llm",
    **kwargs: Any,
) -> tuple[Any, Any]:
    """Submit streaming chat; returns (job, event_iterator)."""
    # Drop forgeable private-host flags — authority is policy-owned only.
    kwargs.pop("allow_private_hosts", None)
    client = ProviderExecutionClient(job_runtime)
    payload: dict[str, Any] = {"endpoint": endpoint, "messages": messages}
    for key in ("max_tokens", "temperature", "tools", "tool_choice"):
        if key in kwargs and kwargs[key] is not None:
            payload[key] = kwargs[key]
    job = client.submit(
        provider=provider,
        capability="chat.stream",
        payload=payload,
        model=model,
        streaming=True,
        credential_ref=credential_ref,
        deadline_seconds=kwargs.get("deadline_seconds"),
        correlation_id=kwargs.get("correlation_id"),
        principal_ref=kwargs.get("principal_ref"),
        latency_class="interactive",
        idempotency_class="NON_IDEMPOTENT_WRITE",
    )
    return job, client.iter_stream(job.job_id)
