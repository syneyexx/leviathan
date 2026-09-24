"""Generic bounded HTTP adapter with SSRF protection."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

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
from Data.modules.provider_io.types import ProviderExecutionResult, ProviderRequest
from Data.modules.research.ssrf import assert_safe_url


CancelCheck = Callable[[], bool]


class GenericHttpAdapter:
    name = "generic_http"

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
        url = str(payload.get("url") or "").strip()
        method = str(payload.get("method") or "GET").upper()
        headers = dict(payload.get("headers") or {})
        body = payload.get("body")
        max_bytes = int(payload.get("max_bytes") or policy.settings.max_response_bytes)
        allow_private = bool(request.allow_private_hosts or payload.get("allow_private_hosts"))

        if not url:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                "HTTP provider request requires payload.url",
                provider=request.provider,
            )
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                f"Unsupported HTTP method: {method}",
                provider=request.provider,
            )

        # SSRF: block private/metadata unless explicitly trusted local endpoint.
        if not allow_private:
            try:
                assert_safe_url(url)
            except ValueError as exc:
                raise ProviderError(
                    ProviderErrorCode.SSRF_BLOCKED,
                    str(exc),
                    provider=request.provider,
                    retryable=False,
                ) from exc
        else:
            parsed = urlparse(url)
            if (parsed.scheme or "").lower() not in {"http", "https"}:
                raise ProviderError(
                    ProviderErrorCode.SSRF_BLOCKED,
                    f"scheme not allowed: {parsed.scheme}",
                    provider=request.provider,
                )

        if credential.api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {credential.api_key}"
        if credential.headers:
            headers.update(credential.headers)

        connect_t, read_t = budget.timeout_for_attempt(
            connect=policy.settings.connect_timeout_seconds,
            read=policy.settings.read_timeout_seconds,
        )
        client = clients.client(name="http")
        try:
            if cancel_check and cancel_check():
                raise ProviderError(
                    ProviderErrorCode.EXECUTION_CANCELLED,
                    "Cancelled before HTTP request",
                    provider=request.provider,
                    retryable=False,
                )
            timeout = httpx.Timeout(connect=connect_t, read=read_t, write=read_t, pool=connect_t)
            resp = client.request(
                method,
                url,
                headers=headers,
                content=body if isinstance(body, (bytes, bytearray)) else None,
                json=body if isinstance(body, (dict, list)) else None,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_TIMEOUT,
                f"HTTP timeout talking to {urlparse(url).hostname}",
                provider=request.provider,
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_UNAVAILABLE,
                f"HTTP transport error: {redact_secrets(str(exc))}",
                provider=request.provider,
                retryable=True,
            ) from exc

        if cancel_check and cancel_check():
            raise ProviderError(
                ProviderErrorCode.EXECUTION_CANCELLED,
                "Cancelled after HTTP response",
                provider=request.provider,
                retryable=False,
            )

        content = resp.content or b""
        if len(content) > max_bytes:
            raise ProviderError(
                ProviderErrorCode.PAYLOAD_TOO_LARGE,
                f"Response exceeded max_bytes={max_bytes}",
                provider=request.provider,
                http_status=resp.status_code,
            )

        if resp.status_code >= 400:
            retry_after = None
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    retry_after = float(ra)
                except ValueError:
                    retry_after = None
            err = classify_http_status(
                resp.status_code,
                body_snippet=content[:500].decode("utf-8", errors="replace"),
                retry_after=retry_after,
            )
            err.provider = request.provider
            raise err

        text: str | None
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = None

        structured: dict[str, Any] | None = None
        if text and (resp.headers.get("content-type") or "").startswith("application/json"):
            try:
                import json

                parsed_json = json.loads(text)
                if isinstance(parsed_json, dict):
                    structured = parsed_json
                else:
                    structured = {"data": parsed_json}
            except Exception:  # noqa: BLE001
                structured = None

        return ProviderExecutionResult(
            status="succeeded",
            content=text,
            structured=structured,
            provider=request.provider,
            finish_reason="stop",
            metadata={
                "http_status": resp.status_code,
                "url_host": urlparse(url).hostname,
                "bytes": len(content),
                "content_type": resp.headers.get("content-type"),
            },
        )
