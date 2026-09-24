from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from Data.backend.config import Settings
from Data.modules.context import ContextBuilder
from Data.modules.reasoning import ReasoningPlan

from .streaming import extract_delta_text, extract_finish_reason, parse_openai_sse_line
from .serving import StreamCancelToken


class LLMUnavailable(RuntimeError):
    pass


class OpenAICompatibleLLM:
    """Minimal OpenAI-compatible model client.

    Works with LM Studio and other servers exposing /v1/models and
    /v1/chat/completions. Provider-facing only — no task lifecycle or
    execution authority. Model Control Plane resolves which endpoint/model
    to use; this client executes the request.
    """

    def __init__(self, settings: Settings, context_builder: ContextBuilder | None = None) -> None:
        self.settings = settings
        ctx = settings.context
        self.context_builder = context_builder or ContextBuilder(
            token_budget=ctx.token_budget,
            max_knowledge_chars=ctx.max_knowledge_chars,
            max_history_messages=settings.resources.max_history_messages,
            reserve_response_tokens=ctx.reserve_response_tokens,
            auto_budget=bool(getattr(ctx, "auto_budget", True)),
            max_context_fraction=float(getattr(ctx, "max_context_fraction", 0.72)),
            reserve_response_fraction=float(getattr(ctx, "reserve_response_fraction", 0.18)),
            minimum_response_tokens=int(getattr(ctx, "minimum_response_tokens", 256)),
        )
        self._resolved_model: str | None = settings.llm_model

    def _headers(self, api_key: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = api_key if api_key is not None else self.settings.llm_api_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _base_url(self, endpoint: str | None = None) -> str:
        raw = (endpoint or self.settings.llm_base_url).rstrip("/")
        if raw.endswith("/v1"):
            return raw
        if "/v1/" in raw:
            return raw.split("/v1/")[0] + "/v1"
        # Ollama native root may be passed; prefer /v1 when present on settings default.
        if endpoint and not endpoint.rstrip("/").endswith("/v1"):
            # Caller may pass OpenAI-compatible endpoint already normalized by control plane.
            return raw if raw.endswith("/v1") else f"{raw}/v1"
        return raw if raw.endswith("/v1") else f"{raw}/v1"

    async def resolve_model(self, *, endpoint: str | None = None, api_key: str | None = None) -> str:
        if self._resolved_model:
            return self._resolved_model

        base = self._base_url(endpoint)
        try:
            async with httpx.AsyncClient(timeout=min(self.settings.llm_timeout_seconds, 10.0)) as client:
                response = await client.get(f"{base}/models", headers=self._headers(api_key))
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMUnavailable(
                f"No model configured and model discovery failed at {base}."
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

    def _build_messages(
        self,
        history: list[dict[str, str]],
        knowledge: list[dict],
        plan: ReasoningPlan,
        *,
        memory: list[dict] | None = None,
        observations: list[dict] | None = None,
        evidence: list[dict] | None = None,
        neuro: list[dict] | None = None,
        atlas: list[dict] | None = None,
        why: list[dict] | None = None,
        contradictions: list[dict] | str | None = None,
        system_prompt: str | None = None,
        behavior_profile_prompt: str | None = None,
        mode: str | None = None,
        constraints: str | None = None,
    ) -> list[dict[str, str]]:
        # Canonical identity comes from BehaviorProfile via ContextBuilder.
        # ``system_prompt`` here is treated as an optional additive constraint /
        # model-profile overlay — never a second LEVIATHAN identity layer after
        # the compiler has already produced the pack.
        identity = (behavior_profile_prompt or "").strip() or None
        if identity is None:
            try:
                from Data.modules.settings.behavior import DEFAULT_BEHAVIOR_PROFILE

                identity = DEFAULT_BEHAVIOR_PROFILE.system_prompt
            except Exception:  # noqa: BLE001
                identity = None

        additive = (system_prompt or "").strip()
        pack_constraints = constraints
        if additive:
            # Model-profile / caller overlay is pinned constraint text, not identity.
            if pack_constraints and pack_constraints.strip():
                pack_constraints = f"{pack_constraints.strip()}\n\n{additive}"
            else:
                pack_constraints = additive

        pack = self.context_builder.build(
            history=history,
            knowledge=knowledge,
            plan=plan,
            memory=memory,
            observations=observations,
            evidence=evidence,
            neuro=neuro,
            atlas=atlas,
            why=why,
            contradictions=contradictions,  # type: ignore[arg-type]
            behavior_profile_prompt=identity,
            mode=mode,
            constraints=pack_constraints,
        )
        # ContextPack is authoritative — do not prepend a competing system identity.
        return list(pack.messages)

    def _completion_payload(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None,
        max_tokens: int | None,
        top_p: float | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.35 if temperature is None else temperature,
            "stream": bool(stream),
        }
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    @staticmethod
    def _extract_usage(data: dict[str, Any]) -> tuple[dict[str, int], str]:
        """Parse provider usage when present. Never invent token counts.

        Cached-token fields are normalized when the provider emits them; omitted
        fields remain absent (not zero).
        """
        from Data.modules.models.efficiency_capabilities import normalize_provider_usage

        raw = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            return {}, "unavailable"
        normalized = normalize_provider_usage(raw)
        if normalized.usage_source == "unavailable":
            return {}, "unavailable"
        out: dict[str, int] = {}
        if normalized.input_tokens is not None:
            out["prompt_tokens"] = normalized.input_tokens
            out["input_tokens"] = normalized.input_tokens
        if normalized.output_tokens is not None:
            out["completion_tokens"] = normalized.output_tokens
            out["output_tokens"] = normalized.output_tokens
        if normalized.total_tokens is not None:
            out["total_tokens"] = normalized.total_tokens
        # Only include cached fields when explicitly reported (null ≠ 0).
        if normalized.cached_input_tokens is not None:
            out["cached_tokens"] = normalized.cached_input_tokens
            out["cached_input_tokens"] = normalized.cached_input_tokens
        if normalized.cache_creation_tokens is not None:
            out["cache_creation_tokens"] = normalized.cache_creation_tokens
        if normalized.cache_read_tokens is not None:
            out["cache_read_tokens"] = normalized.cache_read_tokens
        if not out:
            return {}, "unavailable"
        return out, "provider"

    async def complete_messages(
        self,
        messages: list[dict[str, str]],
        *,
        model_id: str | None = None,
        endpoint: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
    ) -> dict[str, Any]:
        """Low-level completion for cognition / tool loops — no ContextBuilder rewrite."""
        model = model_id or await self.resolve_model(endpoint=endpoint, api_key=api_key)
        payload = self._completion_payload(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stream=False,
        )
        base = self._base_url(endpoint)
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                response = await client.post(
                    f"{base}/chat/completions",
                    headers=self._headers(api_key),
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
        usage, usage_source = self._extract_usage(data if isinstance(data, dict) else {})
        return {
            "text": content.strip(),
            "model": model,
            "usage": usage,
            "usage_source": usage_source,
        }

    async def chat(
        self,
        history: list[dict[str, str]],
        knowledge: list[dict],
        plan: ReasoningPlan,
        *,
        memory: list[dict] | None = None,
        observations: list[dict] | None = None,
        evidence: list[dict] | None = None,
        neuro: list[dict] | None = None,
        atlas: list[dict] | None = None,
        why: list[dict] | None = None,
        contradictions: list[dict] | str | None = None,
        model_id: str | None = None,
        endpoint: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        system_prompt: str | None = None,
        behavior_profile_prompt: str | None = None,
        stream: bool = False,
    ) -> tuple[str, str]:
        """Non-streaming chat completion. ``stream=True`` is ignored here — use chat_stream."""
        _ = stream  # callers must use chat_stream for token streaming
        messages = self._build_messages(
            history,
            knowledge,
            plan,
            memory=memory,
            observations=observations,
            evidence=evidence,
            neuro=neuro,
            atlas=atlas,
            why=why,
            contradictions=contradictions,
            system_prompt=system_prompt,
            behavior_profile_prompt=behavior_profile_prompt,
        )
        result = await self.complete_messages(
            messages,
            model_id=model_id,
            endpoint=endpoint,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
        )
        return result["text"], result["model"]

    async def chat_stream(
        self,
        history: list[dict[str, str]],
        knowledge: list[dict],
        plan: ReasoningPlan,
        *,
        memory: list[dict] | None = None,
        observations: list[dict] | None = None,
        evidence: list[dict] | None = None,
        neuro: list[dict] | None = None,
        atlas: list[dict] | None = None,
        why: list[dict] | None = None,
        contradictions: list[dict] | str | None = None,
        model_id: str | None = None,
        endpoint: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        system_prompt: str | None = None,
        behavior_profile_prompt: str | None = None,
        cancel: StreamCancelToken | None = None,
    ) -> AsyncIterator[tuple[str, str]]:
        """Yield ``(delta_text, model_id)`` token chunks from OpenAI-compatible SSE.

        Honors cooperative ``cancel`` between chunks (U025). Never fabricates a
        stream from a completed non-stream response except when the server itself
        returns JSON (honest single-chunk degrade).
        """
        model = model_id or await self.resolve_model(endpoint=endpoint, api_key=api_key)
        messages = self._build_messages(
            history,
            knowledge,
            plan,
            memory=memory,
            observations=observations,
            evidence=evidence,
            neuro=neuro,
            atlas=atlas,
            why=why,
            contradictions=contradictions,
            system_prompt=system_prompt,
            behavior_profile_prompt=behavior_profile_prompt,
        )
        payload = self._completion_payload(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stream=True,
        )
        base = self._base_url(endpoint)
        headers = self._headers(api_key)
        headers["Accept"] = "text/event-stream"
        yielded = False
        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                async with client.stream(
                    "POST",
                    f"{base}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    if cancel and cancel.cancelled:
                        await response.aclose()
                        raise LLMUnavailable(f"LLM stream cancelled: {cancel.reason}")
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")[:400]
                        raise LLMUnavailable(
                            f"LLM stream failed HTTP {response.status_code}: {body}"
                        )
                    content_type = (response.headers.get("content-type") or "").lower()
                    # Some servers return application/json even for stream=false fallbacks.
                    if "text/event-stream" not in content_type and "json" in content_type:
                        raw = await response.aread()
                        try:
                            data = json.loads(raw.decode("utf-8"))
                            content = data["choices"][0]["message"]["content"]
                        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
                            raise LLMUnavailable(
                                "LLM stream endpoint returned non-SSE JSON without usable content"
                            ) from exc
                        if not isinstance(content, str) or not content.strip():
                            raise LLMUnavailable("LLM returned an empty streamed response.")
                        yield content.strip(), model
                        return
                    async for line in response.aiter_lines():
                        if cancel and cancel.cancelled:
                            await response.aclose()
                            break
                        chunk = parse_openai_sse_line(line)
                        if chunk is None:
                            continue
                        if chunk.get("_done"):
                            break
                        finish = extract_finish_reason(chunk)
                        delta = extract_delta_text(chunk)
                        if not delta:
                            if finish:
                                break
                            continue
                        yielded = True
                        yield delta, model
                        if finish:
                            break
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"LLM stream request failed: {exc}") from exc
        if cancel and cancel.cancelled:
            return
        if not yielded:
            raise LLMUnavailable("LLM stream completed without tokens.")
