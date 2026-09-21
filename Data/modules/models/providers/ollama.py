"""Ollama provider adapter — real HTTP integration where APIs exist."""

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
    PROVIDER_OFFLINE,
    REQUEST_TIMEOUT,
    ModelControlError,
)
from Data.modules.models.store import utc_now


def _ollama_root(endpoint: str) -> str:
    text = endpoint.strip().rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ModelControlError(
            code="VALIDATION_ERROR",
            message=f"Invalid Ollama endpoint: {endpoint!r}",
            http_status=422,
        )
    if text.endswith("/v1"):
        return text[:-3]
    return text


class OllamaAdapter:
    provider_type = "ollama"

    def __init__(
        self,
        *,
        provider_id: str,
        endpoint: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.provider_id = provider_id
        self.endpoint = _ollama_root(endpoint)
        self.api_key = api_key or ""
        self.timeout_seconds = timeout_seconds
        self._capabilities = RuntimeCapabilities(
            discover_models=True,
            import_model=False,
            download_model=True,
            load_model=False,
            unload_model=False,
            delete_model=True,
            list_loaded_models=True,
            inference=True,
            streaming=True,
            embeddings=True,
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
                response = await client.get(f"{self.endpoint}/api/tags", headers=self._headers())
            latency = (time.perf_counter() - started) * 1000.0
            if response.status_code >= 500:
                return ProviderHealth.DEGRADED, latency, f"HTTP {response.status_code}"
            response.raise_for_status()
            return ProviderHealth.HEALTHY, latency, None
        except httpx.TimeoutException as exc:
            return ProviderHealth.TIMEOUT, None, str(exc)
        except httpx.HTTPError as exc:
            return ProviderHealth.OFFLINE, None, str(exc)

    async def discover(self) -> list[ModelDescriptor]:
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout_seconds, 15.0)) as client:
                response = await client.get(f"{self.endpoint}/api/tags", headers=self._headers())
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise ModelControlError(
                code=REQUEST_TIMEOUT,
                message="Ollama discovery timed out",
                provider_id=self.provider_id,
                retryable=True,
                http_status=504,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message=f"Ollama offline: {exc}",
                provider_id=self.provider_id,
                retryable=True,
                http_status=503,
            ) from exc

        models_raw = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models_raw, list):
            return []

        loaded_names: set[str] = set()
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout_seconds, 10.0)) as client:
                ps = await client.get(f"{self.endpoint}/api/ps", headers=self._headers())
                if ps.status_code == 200:
                    ps_payload = ps.json()
                    for item in ps_payload.get("models") or []:
                        if isinstance(item, dict) and item.get("name"):
                            loaded_names.add(str(item["name"]))
        except (httpx.HTTPError, ValueError):
            pass

        results: list[ModelDescriptor] = []
        for item in models_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("model") or "").strip()
            if not name:
                continue
            details = item.get("details") if isinstance(item.get("details"), dict) else {}
            size = item.get("size")
            disk_size = int(size) if isinstance(size, int) else None
            family = details.get("family") if isinstance(details.get("family"), str) else None
            quantization = (
                details.get("quantization_level")
                if isinstance(details.get("quantization_level"), str)
                else None
            )
            fmt = details.get("format") if isinstance(details.get("format"), str) else None
            loaded = name in loaded_names if loaded_names else None
            results.append(
                ModelDescriptor(
                    id=f"{self.provider_id}:{name}",
                    display_name=name,
                    provider_id=self.provider_id,
                    runtime_id="ollama",
                    source=ModelSource.LOCAL,
                    object_type="model",
                    architecture=None,
                    family=family,
                    parameter_count=None,
                    quantization=quantization,
                    format=fmt,
                    disk_size_bytes=disk_size,
                    context_window=None,
                    max_output_tokens=None,
                    capabilities=ModelCapabilities(
                        chat=CapabilityState.UNVERIFIED,
                        streaming=CapabilityState.UNVERIFIED,
                        embeddings=CapabilityState.UNVERIFIED,
                    ),
                    lifecycle_state=(
                        ModelLifecycleState.LOADED if loaded else ModelLifecycleState.AVAILABLE
                    ),
                    health=ModelHealthState.HEALTHY,
                    loaded=loaded,
                    endpoint=self.endpoint,
                    last_discovered_at=utc_now(),
                    metadata={"provider_model_id": name},
                )
            )
        return results

    async def load(self, model_id: str, options: LoadOptions | None = None) -> dict[str, Any]:
        raise ModelControlError(
            code=CAPABILITY_NOT_SUPPORTED,
            message="Ollama loads models on demand; explicit load is not exposed",
            provider_id=self.provider_id,
            model_id=model_id,
            http_status=409,
        )

    async def unload(self, model_id: str) -> dict[str, Any]:
        raise ModelControlError(
            code=CAPABILITY_NOT_SUPPORTED,
            message="Ollama unload is not implemented in this adapter",
            provider_id=self.provider_id,
            model_id=model_id,
            http_status=409,
        )

    async def remove(self, model_id: str) -> None:
        name = model_id.split(":", 1)[-1]
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.request(
                    "DELETE",
                    f"{self.endpoint}/api/delete",
                    headers=self._headers(),
                    json={"model": name},
                )
                if response.status_code == 404:
                    raise ModelControlError(
                        code=MODEL_NOT_FOUND,
                        message=f"Ollama model not found: {name}",
                        provider_id=self.provider_id,
                        model_id=model_id,
                        http_status=404,
                    )
                response.raise_for_status()
        except ModelControlError:
            raise
        except httpx.HTTPError as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message=f"Ollama delete failed: {exc}",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=503,
            ) from exc

    async def test_inference(
        self, model_id: str, *, prompt: str = "ping", max_tokens: int = 8
    ) -> dict[str, Any]:
        name = model_id.split(":", 1)[-1]
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout_seconds, 20.0)) as client:
                response = await client.post(
                    f"{self.endpoint}/api/generate",
                    headers=self._headers(),
                    json={
                        "model": name,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"num_predict": max_tokens},
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise ModelControlError(
                code=REQUEST_TIMEOUT,
                message="Ollama test inference timed out",
                provider_id=self.provider_id,
                model_id=model_id,
                retryable=True,
                http_status=504,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message=f"Ollama test inference failed: {exc}",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=503,
            ) from exc
        return {
            "ok": True,
            "modelId": model_id,
            "latencyMs": (time.perf_counter() - started) * 1000.0,
            "preview": str(data.get("response") or "")[:200],
        }

    async def pull(self, repository: str, *, revision: str | None = None) -> dict[str, Any]:
        name = repository if not revision else f"{repository}:{revision}"
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                response = await client.post(
                    f"{self.endpoint}/api/pull",
                    headers=self._headers(),
                    json={"name": name, "stream": False},
                )
                response.raise_for_status()
                return response.json() if response.content else {"status": "success"}
        except httpx.HTTPError as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message=f"Ollama pull failed: {exc}",
                provider_id=self.provider_id,
                http_status=503,
            ) from exc
