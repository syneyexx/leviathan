"""Quick benchmark entry points — raw metrics only, no 'best model' scores."""

from __future__ import annotations

import time
from typing import Any, Callable

from Data.modules.models.errors import ModelControlError
from Data.modules.models.registry import ModelRegistry


class BenchmarkService:
    def __init__(
        self,
        registry: ModelRegistry,
        *,
        get_adapter: Callable[[str], Any],
    ) -> None:
        self.registry = registry
        self._get_adapter = get_adapter

    async def quick_benchmark(self, model_id: str) -> dict[str, Any]:
        model = self.registry.get(model_id)
        adapter = self._get_adapter(model.provider_id)
        started = time.perf_counter()
        try:
            outcome = await adapter.test_inference(
                model_id, prompt="Count from 1 to 3.", max_tokens=16
            )
        except ModelControlError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ModelControlError(
                code="MODEL_UNSUPPORTED",
                message=f"Quick benchmark failed: {exc}",
                model_id=model_id,
                provider_id=model.provider_id,
                http_status=502,
            ) from exc
        total_ms = (time.perf_counter() - started) * 1000.0
        # TTFT approximates total for non-streaming test; do not invent tokens/sec.
        return {
            "modelId": model_id,
            "requestLatencyMs": total_ms,
            "timeToFirstTokenMs": outcome.get("latencyMs"),
            "tokensPerSecond": None,
            "structuredOutputCompliance": None,
            "toolCallCapability": None,
            "preview": outcome.get("preview"),
            "note": "Quick probe only — not a ranking score",
        }
