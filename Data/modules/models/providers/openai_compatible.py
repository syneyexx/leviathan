"""OpenAI-compatible HTTP provider helpers."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx

from Data.modules.models.contracts import (
    CapabilityState,
    LoadOptions,
    ModelCapabilities,
    ModelDescriptor,
    ModelHealthState,
    ModelLifecycleState,
    ModelSource,
    ProviderHealth,
    RuntimeCapabilities,
)
from Data.modules.models.errors import (
    CAPABILITY_NOT_SUPPORTED,
    MODEL_NOT_FOUND,
    PROVIDER_AUTH_FAILED,
    PROVIDER_OFFLINE,
    REQUEST_TIMEOUT,
    ModelControlError,
)
from Data.modules.models.providers.base import UnsupportedOperation
from Data.modules.models.store import utc_now


def normalize_openai_base(endpoint: str) -> str:
    text = endpoint.strip().rstrip("/")
    if not text:
        raise ModelControlError(
            code="VALIDATION_ERROR",
            message="Provider endpoint cannot be empty",
            http_status=422,
        )
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ModelControlError(
            code="VALIDATION_ERROR",
            message=f"Provider endpoint must use http or https: {endpoint!r}",
            http_status=422,
        )
    if not parsed.netloc:
        raise ModelControlError(
            code="VALIDATION_ERROR",
            message=f"Provider endpoint missing host: {endpoint!r}",
            http_status=422,
        )
    # Accept both .../v1 and bare host; normalize to .../v1 for OpenAI-compatible.
    if text.endswith("/v1"):
        return text
    if "/v1/" in text:
        return text.split("/v1/")[0] + "/v1"
    return text + "/v1"


class OpenAICompatibleAdapter:
    """Generic OpenAI-compatible discovery + inference adapter."""

    provider_type = "openai_compatible"

    def __init__(
        self,
        *,
        provider_id: str,
        endpoint: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        source: ModelSource = ModelSource.API,
        capabilities: RuntimeCapabilities | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.endpoint = normalize_openai_base(endpoint)
        self.api_key = api_key or ""
        self.timeout_seconds = timeout_seconds
        self.source = source
        self._capabilities = capabilities or RuntimeCapabilities(
            discover_models=True,
            import_model=False,
            download_model=False,
            load_model=False,
            unload_model=False,
            delete_model=False,
            list_loaded_models=False,
            inference=True,
            streaming=True,
            embeddings=False,
            tool_calling=False,
            structured_output=False,
            vision=False,
            runtime_metrics=False,
        )

    def capabilities(self) -> RuntimeCapabilities:
        return self._capabilities

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "not-needed":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def health(self) -> tuple[ProviderHealth, float | None, str | None]:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout_seconds, 10.0)) as client:
                response = await client.get(f"{self.endpoint}/models", headers=self._headers())
            latency = (time.perf_counter() - started) * 1000.0
            if response.status_code in {401, 403}:
                return ProviderHealth.AUTH_ERROR, latency, f"HTTP {response.status_code}"
            if response.status_code >= 500:
                return ProviderHealth.DEGRADED, latency, f"HTTP {response.status_code}"
            response.raise_for_status()
            return ProviderHealth.HEALTHY, latency, None
        except httpx.TimeoutException as exc:
            return ProviderHealth.TIMEOUT, None, str(exc)
        except httpx.HTTPError as exc:
            return ProviderHealth.OFFLINE, None, str(exc)
        except ValueError as exc:
            return ProviderHealth.DEGRADED, None, str(exc)

    def _normalize_model(self, raw: dict[str, Any]) -> ModelDescriptor:
        model_id = str(raw.get("id") or "").strip()
        if not model_id:
            raise ModelControlError(
                code=MODEL_NOT_FOUND,
                message="Provider returned a model without an id",
                provider_id=self.provider_id,
            )
        # Never infer parameters/size/context from the name.
        caps = ModelCapabilities(
            chat=CapabilityState.UNVERIFIED,
            streaming=CapabilityState.UNVERIFIED
            if self._capabilities.streaming
            else CapabilityState.UNSUPPORTED,
            tool_calling=CapabilityState.UNKNOWN,
            structured_output=CapabilityState.UNKNOWN,
            vision=CapabilityState.UNKNOWN,
            embeddings=CapabilityState.UNKNOWN,
            reasoning=CapabilityState.UNKNOWN,
            coding=CapabilityState.UNKNOWN,
        )
        object_type = raw.get("object")
        owned_by = raw.get("owned_by")
        return ModelDescriptor(
            id=f"{self.provider_id}:{model_id}",
            display_name=model_id,
            provider_id=self.provider_id,
            runtime_id=self.provider_type,
            source=self.source,
            object_type=str(object_type) if object_type is not None else "model",
            architecture=None,
            family=str(owned_by) if owned_by else None,
            parameter_count=None,
            quantization=None,
            format=None,
            disk_size_bytes=None,
            context_window=None,
            max_output_tokens=None,
            capabilities=caps,
            lifecycle_state=ModelLifecycleState.AVAILABLE,
            health=ModelHealthState.HEALTHY,
            active=False,
            loaded=None,
            local_path=None,
            endpoint=self.endpoint,
            last_discovered_at=utc_now(),
            metadata={"provider_model_id": model_id, "raw_keys": sorted(raw.keys())},
        )

    async def discover(self) -> list[ModelDescriptor]:
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout_seconds, 15.0)) as client:
                response = await client.get(f"{self.endpoint}/models", headers=self._headers())
        except httpx.TimeoutException as exc:
            raise ModelControlError(
                code=REQUEST_TIMEOUT,
                message=f"Discovery timed out for {self.provider_id}",
                provider_id=self.provider_id,
                retryable=True,
                http_status=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message=f"Provider offline: {exc}",
                provider_id=self.provider_id,
                retryable=True,
                http_status=503,
            ) from exc

        if response.status_code in {401, 403}:
            raise ModelControlError(
                code=PROVIDER_AUTH_FAILED,
                message=f"Authentication failed for {self.provider_id}",
                provider_id=self.provider_id,
                http_status=401,
            )
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message=f"Invalid discovery response from {self.provider_id}",
                provider_id=self.provider_id,
                retryable=True,
                http_status=502,
                details={"error": str(exc)},
            ) from exc

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message=f"Provider {self.provider_id} returned no model list",
                provider_id=self.provider_id,
                http_status=502,
            )

        models: list[ModelDescriptor] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                models.append(self._normalize_model(item))
            except ModelControlError:
                continue
        return models

    async def load(self, model_id: str, options: LoadOptions | None = None) -> dict[str, Any]:
        raise UnsupportedOperation("load", self.provider_id)

    async def unload(self, model_id: str) -> dict[str, Any]:
        raise UnsupportedOperation("unload", self.provider_id)

    async def remove(self, model_id: str) -> None:
        raise UnsupportedOperation("remove", self.provider_id)

    async def test_inference(
        self, model_id: str, *, prompt: str = "ping", max_tokens: int = 8
    ) -> dict[str, Any]:
        provider_model = model_id.split(":", 1)[-1]
        payload = {
            "model": provider_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout_seconds, 20.0)) as client:
                response = await client.post(
                    f"{self.endpoint}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise ModelControlError(
                code=REQUEST_TIMEOUT,
                message="Test inference timed out",
                provider_id=self.provider_id,
                model_id=model_id,
                retryable=True,
                http_status=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message=f"Test inference failed: {exc}",
                provider_id=self.provider_id,
                model_id=model_id,
                retryable=True,
                http_status=503,
            ) from exc
        except ValueError as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message="Test inference returned invalid JSON",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=502,
            ) from exc

        latency = (time.perf_counter() - started) * 1000.0
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message="Unexpected chat completion payload",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=502,
            ) from exc
        return {
            "ok": True,
            "modelId": model_id,
            "latencyMs": latency,
            "preview": str(content)[:200] if content is not None else "",
        }

    def raise_capability(self, operation: str) -> None:
        raise ModelControlError(
            code=CAPABILITY_NOT_SUPPORTED,
            message=f"{operation} is not supported by provider {self.provider_id}",
            provider_id=self.provider_id,
            http_status=409,
            details={"operation": operation},
        )
