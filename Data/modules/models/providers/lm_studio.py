"""LM Studio provider adapter.

LM Studio exposes an OpenAI-compatible HTTP API for discovery and inference.
Programmatic load/unload via the OpenAI surface is not available; lifecycle is
managed externally in the LM Studio application unless a dedicated control API
is later wired.
"""

from __future__ import annotations

from Data.modules.models.contracts import ModelSource, RuntimeCapabilities
from Data.modules.models.providers.openai_compatible import OpenAICompatibleAdapter


class LMStudioAdapter(OpenAICompatibleAdapter):
    provider_type = "lm_studio"

    def __init__(
        self,
        *,
        provider_id: str,
        endpoint: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(
            provider_id=provider_id,
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            source=ModelSource.REMOTE,
            capabilities=RuntimeCapabilities(
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
                load_options=(),
            ),
        )
