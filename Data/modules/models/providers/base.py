"""Provider adapter protocol for the Model Control Plane."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from Data.modules.models.contracts import (
    LoadOptions,
    ModelDescriptor,
    ProviderHealth,
    RuntimeCapabilities,
)


@runtime_checkable
class ModelProviderAdapter(Protocol):
    provider_id: str

    def capabilities(self) -> RuntimeCapabilities: ...

    async def health(self) -> tuple[ProviderHealth, float | None, str | None]:
        """Return (health, latency_ms, error_message)."""
        ...

    async def discover(self) -> list[ModelDescriptor]: ...

    async def load(
        self, model_id: str, options: LoadOptions | None = None
    ) -> dict[str, Any]: ...

    async def unload(self, model_id: str) -> dict[str, Any]: ...

    async def remove(self, model_id: str) -> None: ...

    async def test_inference(
        self, model_id: str, *, prompt: str = "ping", max_tokens: int = 8
    ) -> dict[str, Any]: ...


class UnsupportedOperation(RuntimeError):
    def __init__(self, operation: str, provider_id: str) -> None:
        super().__init__(f"{operation} is not supported by provider {provider_id}")
        self.operation = operation
        self.provider_id = provider_id
