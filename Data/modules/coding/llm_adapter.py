"""Sync adapter so CodingLoop can use the shared OpenAICompatibleLLM transport.

Coding does not own a private model client — this only adapts async transport
to the CodingLoop ChatClient protocol.
"""

from __future__ import annotations

import asyncio
from typing import Any


class CodingLLMAdapter:
    """Bridge CodingLoop.complete(...) → OpenAICompatibleLLM.complete_messages(...)."""

    def __init__(self, llm: Any) -> None:
        self.llm = llm

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        model_id: str | None = None,
    ) -> tuple[str, str | None]:
        async def _run() -> tuple[str, str | None]:
            result = await self.llm.complete_messages(
                messages,
                model_id=model_id,
                temperature=temperature,
            )
            text = str(result.get("text") or "")
            mid = result.get("model") or model_id
            return text, str(mid) if mid else model_id

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_run())
        # Already inside an event loop (unusual for CodingWorker thread) — use a bridge.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(_run())).result(timeout=600)
