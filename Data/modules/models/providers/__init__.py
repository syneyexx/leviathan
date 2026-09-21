"""Provider adapter factory."""

from __future__ import annotations

from typing import Any

from Data.modules.models.providers.llama_cpp import LlamaCppAdapter
from Data.modules.models.providers.lm_studio import LMStudioAdapter
from Data.modules.models.providers.ollama import OllamaAdapter
from Data.modules.models.providers.openai_compatible import OpenAICompatibleAdapter


def build_adapter(
    *,
    provider_id: str,
    provider_type: str,
    endpoint: str,
    api_key: str | None = None,
    timeout_seconds: float = 30.0,
    metadata: dict[str, Any] | None = None,
) -> Any:
    kind = (provider_type or "").strip().lower()
    if kind in {"lm_studio", "lmstudio"}:
        return LMStudioAdapter(
            provider_id=provider_id,
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    if kind == "ollama":
        return OllamaAdapter(
            provider_id=provider_id,
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    if kind in {"llama_cpp", "llamacpp", "llama.cpp"}:
        meta = metadata or {}
        return LlamaCppAdapter(
            provider_id=provider_id,
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            managed=bool(meta.get("managed", False)),
        )
    return OpenAICompatibleAdapter(
        provider_id=provider_id,
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
