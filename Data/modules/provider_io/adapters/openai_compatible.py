"""OpenAI-compatible chat complete / stream adapter for provider_io workers."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import httpx

from Data.modules.common.secrets import redact_secrets
from Data.modules.provider_io.clients import ProviderClientPool
from Data.modules.provider_io.credentials import ResolvedCredential
from Data.modules.provider_io.errors import (
    ProviderError,
    ProviderErrorCode,
    classify_http_status,
)
from Data.modules.provider_io.policy import DeadlineBudget, ProviderPolicyRegistry
from Data.modules.provider_io.stream_store import ProviderStreamStore
from Data.modules.provider_io.types import (
    ProviderExecutionResult,
    ProviderRequest,
    StreamEventType,
)
from Data.modules.research.ssrf import assert_safe_url


CancelCheck = Callable[[], bool]


def _normalize_base(url: str) -> str:
    raw = url.rstrip("/")
    if raw.endswith("/v1"):
        return raw
    if "/v1/" in raw:
        return raw.split("/v1/")[0] + "/v1"
    return raw if raw.endswith("/v1") else f"{raw}/v1"


class OpenAICompatibleAdapter:
    name = "openai_compatible"

    def execute(
        self,
        request: ProviderRequest,
        *,
        clients: ProviderClientPool,
        credential: ResolvedCredential,
        policy: ProviderPolicyRegistry,
        budget: DeadlineBudget,
        stream_store: ProviderStreamStore | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ProviderExecutionResult:
        payload = dict(request.payload or {})
        endpoint = str(payload.get("endpoint") or payload.get("base_url") or "").strip()
        if not endpoint:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                "openai_compatible requires payload.endpoint",
                provider=request.provider,
            )
        if not request.allow_private_hosts:
            try:
                assert_safe_url(endpoint)
            except ValueError as exc:
                raise ProviderError(
                    ProviderErrorCode.SSRF_BLOCKED,
                    str(exc),
                    provider=request.provider,
                    retryable=False,
                ) from exc
        base = _normalize_base(endpoint)
        model = request.model or str(payload.get("model") or "").strip() or None
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                "openai_compatible requires payload.messages",
                provider=request.provider,
            )

        headers = {"Content-Type": "application/json"}
        if credential.api_key:
            headers["Authorization"] = f"Bearer {credential.api_key}"

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": bool(request.streaming or request.capability.endswith("stream")),
        }
        for key in ("temperature", "max_tokens", "top_p", "tools", "tool_choice", "response_format"):
            if key in payload and payload[key] is not None:
                body[key] = payload[key]

        if body["stream"]:
            if stream_store is None or not request.job_id:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                    "Streaming requires stream_store and job_id",
                    provider=request.provider,
                )
            return self._stream(
                request=request,
                base=base,
                headers=headers,
                body=body,
                clients=clients,
                policy=policy,
                budget=budget,
                stream_store=stream_store,
                cancel_check=cancel_check,
            )
        return self._complete(
            request=request,
            base=base,
            headers=headers,
            body=body,
            clients=clients,
            policy=policy,
            budget=budget,
            cancel_check=cancel_check,
        )

    def _complete(
        self,
        *,
        request: ProviderRequest,
        base: str,
        headers: dict[str, str],
        body: dict[str, Any],
        clients: ProviderClientPool,
        policy: ProviderPolicyRegistry,
        budget: DeadlineBudget,
        cancel_check: CancelCheck | None,
    ) -> ProviderExecutionResult:
        connect_t, read_t = budget.timeout_for_attempt(
            connect=policy.settings.connect_timeout_seconds,
            read=policy.settings.read_timeout_seconds,
        )
        client = clients.client(name="openai")
        t0 = time.monotonic()
        try:
            if cancel_check and cancel_check():
                raise ProviderError(
                    ProviderErrorCode.EXECUTION_CANCELLED,
                    "Cancelled before chat completion",
                    provider=request.provider,
                )
            resp = client.post(
                f"{base}/chat/completions",
                headers=headers,
                json={**body, "stream": False},
                timeout=httpx.Timeout(connect=connect_t, read=read_t, write=read_t, pool=connect_t),
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_TIMEOUT,
                "Chat completion timed out",
                provider=request.provider,
                model=request.model,
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_UNAVAILABLE,
                f"Chat transport error: {redact_secrets(str(exc))}",
                provider=request.provider,
                model=request.model,
                retryable=True,
            ) from exc

        elapsed = time.monotonic() - t0
        if resp.status_code >= 400:
            ra = resp.headers.get("Retry-After")
            retry_after = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
            err = classify_http_status(
                resp.status_code,
                body_snippet=resp.text[:500],
                retry_after=retry_after,
            )
            err.provider = request.provider
            err.model = request.model
            raise err

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_INVALID,
                "Provider returned non-JSON chat completion",
                provider=request.provider,
                retryable=False,
            ) from exc

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        tool_calls = message.get("tool_calls") or []
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return ProviderExecutionResult(
            status="succeeded",
            content=str(content) if content is not None else None,
            tool_calls=list(tool_calls) if isinstance(tool_calls, list) else [],
            finish_reason=str(choice.get("finish_reason") or "stop"),
            usage=dict(usage),
            provider=request.provider,
            model=str(data.get("model") or request.model or ""),
            provider_request_id=str(data.get("id") or "") or None,
            timing={"total_seconds": elapsed, "ttfb_seconds": elapsed},
            structured={"raw_finish": choice.get("finish_reason")},
        )

    def _stream(
        self,
        *,
        request: ProviderRequest,
        base: str,
        headers: dict[str, str],
        body: dict[str, Any],
        clients: ProviderClientPool,
        policy: ProviderPolicyRegistry,
        budget: DeadlineBudget,
        stream_store: ProviderStreamStore,
        cancel_check: CancelCheck | None,
    ) -> ProviderExecutionResult:
        job_id = str(request.job_id)
        connect_t, read_t = budget.timeout_for_attempt(
            connect=policy.settings.connect_timeout_seconds,
            read=policy.settings.read_timeout_seconds,
        )
        client = clients.client(name="openai")
        t0 = time.monotonic()
        ttfb: float | None = None
        parts: list[str] = []
        finish_reason: str | None = None
        usage: dict[str, Any] = {}
        model_used = request.model
        provider_request_id: str | None = None
        emitted = False

        stream_store.append(
            job_id,
            StreamEventType.STARTED,
            {"provider": request.provider, "model": request.model},
            correlation_id=request.correlation_id,
        )

        try:
            with client.stream(
                "POST",
                f"{base}/chat/completions",
                headers=headers,
                json={**body, "stream": True},
                timeout=httpx.Timeout(connect=connect_t, read=read_t, write=read_t, pool=connect_t),
            ) as resp:
                if resp.status_code >= 400:
                    body_bytes = resp.read()
                    ra = resp.headers.get("Retry-After")
                    retry_after = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
                    err = classify_http_status(
                        resp.status_code,
                        body_snippet=body_bytes[:500].decode("utf-8", errors="replace"),
                        retry_after=retry_after,
                    )
                    err.provider = request.provider
                    raise err

                for line in resp.iter_lines():
                    budget.raise_if_exhausted()
                    if cancel_check and cancel_check():
                        raise ProviderError(
                            ProviderErrorCode.EXECUTION_CANCELLED,
                            "Cancelled during chat stream",
                            provider=request.provider,
                        )
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                    else:
                        continue
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if ttfb is None:
                        ttfb = time.monotonic() - t0
                    if chunk.get("id"):
                        provider_request_id = str(chunk["id"])
                    if chunk.get("model"):
                        model_used = str(chunk["model"])
                    if isinstance(chunk.get("usage"), dict):
                        usage = dict(chunk["usage"])
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        text = delta.get("content")
                        if text:
                            parts.append(str(text))
                            emitted = True
                            stream_store.append(
                                job_id,
                                StreamEventType.DELTA,
                                {"text": str(text)},
                                correlation_id=request.correlation_id,
                            )
                        if delta.get("tool_calls"):
                            stream_store.append(
                                job_id,
                                StreamEventType.TOOL_CALL,
                                {"tool_calls": delta.get("tool_calls")},
                                correlation_id=request.correlation_id,
                            )
                        if choice.get("finish_reason"):
                            finish_reason = str(choice["finish_reason"])
        except ProviderError:
            if emitted:
                stream_store.append(
                    job_id,
                    StreamEventType.FAILED,
                    {"code": "PROVIDER_STREAM_INTERRUPTED", "emitted_output": True},
                    correlation_id=request.correlation_id,
                )
            raise
        except httpx.TimeoutException as exc:
            code = (
                ProviderErrorCode.PROVIDER_STREAM_INTERRUPTED
                if emitted
                else ProviderErrorCode.PROVIDER_TIMEOUT
            )
            stream_store.append(
                job_id,
                StreamEventType.FAILED,
                {"code": code.value, "emitted_output": emitted},
                correlation_id=request.correlation_id,
            )
            raise ProviderError(
                code,
                "Chat stream timed out",
                provider=request.provider,
                model=request.model,
                retryable=not emitted,
            ) from exc
        except httpx.TransportError as exc:
            stream_store.append(
                job_id,
                StreamEventType.FAILED,
                {"code": "PROVIDER_STREAM_INTERRUPTED", "emitted_output": emitted},
                correlation_id=request.correlation_id,
            )
            raise ProviderError(
                ProviderErrorCode.PROVIDER_STREAM_INTERRUPTED
                if emitted
                else ProviderErrorCode.PROVIDER_UNAVAILABLE,
                f"Chat stream transport error: {redact_secrets(str(exc))}",
                provider=request.provider,
                retryable=not emitted,
            ) from exc

        content = "".join(parts)
        if usage:
            stream_store.append(
                job_id,
                StreamEventType.USAGE,
                usage,
                correlation_id=request.correlation_id,
            )
        result = ProviderExecutionResult(
            status="succeeded",
            content=content,
            finish_reason=finish_reason or "stop",
            usage=usage,
            provider=request.provider,
            model=model_used,
            provider_request_id=provider_request_id,
            timing={
                "total_seconds": time.monotonic() - t0,
                "ttfb_seconds": ttfb,
            },
        )
        stream_store.append(
            job_id,
            StreamEventType.COMPLETED,
            {
                "finish_reason": result.finish_reason,
                "usage": usage,
                "content_chars": len(content),
            },
            correlation_id=request.correlation_id,
        )
        return result
