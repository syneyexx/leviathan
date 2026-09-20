from __future__ import annotations

from typing import Any

import httpx

from Data.backend.config import Settings
from Data.modules.context import ContextBuilder
from Data.modules.reasoning import ReasoningPlan


class LLMUnavailable(RuntimeError):
    pass


class OpenAICompatibleLLM:
    """Minimal OpenAI-compatible model client.

    Works with LM Studio and other servers exposing /v1/models and
    /v1/chat/completions. Provider-facing only — no task lifecycle or
    execution authority.
    """

    def __init__(self, settings: Settings, context_builder: ContextBuilder | None = None) -> None:
        self.settings = settings
        self.context_builder = context_builder or ContextBuilder()
        self._resolved_model: str | None = settings.llm_model

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        return headers

    async def resolve_model(self) -> str:
        if self._resolved_model:
            return self._resolved_model

        try:
            async with httpx.AsyncClient(timeout=min(self.settings.llm_timeout_seconds, 10.0)) as client:
                response = await client.get(f"{self.settings.llm_base_url}/models", headers=self._headers())
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMUnavailable(
                f"No model configured and model discovery failed at {self.settings.llm_base_url}."
            ) from exc

        models = payload.get("data") if isinstance(payload, dict) else None
        if not models or not isinstance(models, list) or not models[0].get("id"):
            raise LLMUnavailable("The configured model server returned no usable models.")

        self._resolved_model = str(models[0]["id"])
        return self._resolved_model

    async def health(self) -> dict[str, Any]:
        try:
            model = await self.resolve_model()
            return {"available": True, "model": model, "base_url": self.settings.llm_base_url}
        except LLMUnavailable as exc:
            return {
                "available": False,
                "model": self.settings.llm_model,
                "base_url": self.settings.llm_base_url,
                "error": str(exc),
            }

    async def chat(
        self,
        history: list[dict[str, str]],
        knowledge: list[dict],
        plan: ReasoningPlan,
    ) -> tuple[str, str]:
        model = await self.resolve_model()
        pack = self.context_builder.build(history=history, knowledge=knowledge, plan=plan)

        payload = {
            "model": model,
            "messages": list(pack.messages),
            "temperature": 0.35,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                response = await client.post(
                    f"{self.settings.llm_base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"LLM request failed: {exc}") from exc
        except ValueError as exc:
            raise LLMUnavailable("LLM server returned invalid JSON.") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable("LLM server returned an unexpected chat-completion payload.") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMUnavailable("LLM returned an empty response.")
        return content.strip(), model
