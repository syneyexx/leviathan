from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from Data.backend.config import Settings
from Data.modules.context import ContextBuilder
from Data.modules.reasoning import ReasoningPlan

from .streaming import (
    StreamNormalizer,
    extract_finish_reason,
    parse_openai_sse_line,
)
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
            from Data.modules.settings.seed import SEED_SYSTEM_PROMPT

            identity = SEED_SYSTEM_PROMPT

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
        stop: list[str] | tuple[str, ...] | None = None,
        seed: int | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        provider_hints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build provider completion payload with optional termination controls.

        Stop sequences are only attached when explicitly configured for this
        provider/model — never universal User:/Assistant: stops.
        """
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
        if stop:
            cleaned = [s for s in stop if isinstance(s, str) and s]
            if cleaned:
                payload["stop"] = cleaned
        if seed is not None:
            payload["seed"] = seed
        if frequency_penalty is not None:
            payload["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            payload["presence_penalty"] = presence_penalty
        if provider_hints:
            # Non-conflicting provider-specific knobs (e.g. llama.cpp extras).
            for key, value in provider_hints.items():
                if key not in payload and value is not None:
                    payload[key] = value
        return payload

    @staticmethod
    def _normalize_completion_result(
        *,
        text: str,
        model: str,
        finish_reason: str | None,
        termination_source: str,
        usage: dict[str, int],
        usage_source: str,
        request_id: str | None = None,
        turn_id: str | None = None,
        provider: str = "openai_compatible",
        stream_stats: dict[str, Any] | None = None,
        raw_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "text": text,
            "model": model,
            "provider": provider,
            "finish_reason": finish_reason or "stop",
            "termination_source": termination_source,
            "usage": usage,
            "usage_source": usage_source,
            "request_id": request_id,
            "turn_id": turn_id,
            "stream_stats": stream_stats or {},
            "provider_meta": raw_meta or {},
        }

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
        transport: Any | None = None,
        dialect_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        parallel_tool_calls: bool | None = None,
        response_format: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        reasoning_max_tokens: int | None = None,
        logprobs: bool | None = None,
        top_logprobs: int | None = None,
        n: int | None = None,
        prompt_cache_key: str | None = None,
        cache_control: dict[str, Any] | None = None,
        reject_unsupported: bool = True,
        context_window: int | None = None,
        on_context_overflow: str = "refuse",
        enforce_structured: bool = True,
        structured_fail_closed: bool = True,
    ) -> dict[str, Any]:
        """Low-level completion for cognition / tool loops — no ContextBuilder rewrite.

        Frontier transport options are dialect-adapted. Unsupported *requested*
        capabilities are never silently dropped (CAPABILITY_NOT_SUPPORTED).

        W04 inference contract:
        - tool-calling is probed/recorded; tools never silently omitted from payload
        - json_schema / structured responses repair or fail closed (UNAVAILABLE)
        - context overflow refuses or truncates with an explicit signal
        """
        from .dialect import InferenceTransportOptions, adapt_transport
        from .inference_contract import (
            enforce_context_bounds,
            enforce_structured_response,
            probe_tool_calling_transport,
            record_tool_calling_response,
        )

        model = model_id or await self.resolve_model(endpoint=endpoint, api_key=api_key)
        options = transport or InferenceTransportOptions(
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            response_format=response_format,
            reasoning_effort=reasoning_effort,
            reasoning_max_tokens=reasoning_max_tokens,
            logprobs=logprobs,
            top_logprobs=top_logprobs,
            n=n,
            prompt_cache_key=prompt_cache_key,
            cache_control=cache_control,
            reject_unsupported=reject_unsupported,
        )
        adaptation = adapt_transport(options, dialect_id=dialect_id)

        tool_record = probe_tool_calling_transport(
            tools=getattr(options, "tools", tools),
            tool_choice=getattr(options, "tool_choice", tool_choice),
            payload_fields=adaptation.payload_fields,
            feature_states=adaptation.feature_states,
        )

        bounded_messages, context_signal = enforce_context_bounds(
            list(messages),
            context_window=context_window,
            max_output_tokens=max_tokens,
            policy=on_context_overflow,
        )

        payload = self._completion_payload(
            model=model,
            messages=bounded_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stream=False,
            provider_hints=adaptation.payload_fields,
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
            choice0 = data["choices"][0]
            message = choice0["message"]
            content = message.get("content")
            finish_reason = choice0.get("finish_reason")
            tool_calls = message.get("tool_calls")
            reasoning_text = None
            for key in ("reasoning_content", "reasoning", "thinking"):
                raw_r = message.get(key)
                if isinstance(raw_r, str) and raw_r:
                    reasoning_text = raw_r
                    break
                if isinstance(raw_r, dict):
                    for sub in ("content", "text", "summary"):
                        inner = raw_r.get(sub)
                        if isinstance(inner, str) and inner:
                            reasoning_text = inner
                            break
                if reasoning_text:
                    break
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable("LLM server returned an unexpected chat-completion payload.") from exc

        text = content.strip() if isinstance(content, str) else ""
        if not text and not tool_calls:
            raise LLMUnavailable("LLM returned an empty response.")
        usage, usage_source = self._extract_usage(data if isinstance(data, dict) else {})
        result = self._normalize_completion_result(
            text=text,
            model=model,
            finish_reason=str(finish_reason) if finish_reason else ("tool_calls" if tool_calls else "stop"),
            termination_source="provider_finish_reason" if finish_reason else "completion_message",
            usage=usage,
            usage_source=usage_source,
            raw_meta={"id": data.get("id")} if isinstance(data, dict) else {},
        )
        if tool_calls:
            result["tool_calls"] = tool_calls
        if reasoning_text:
            result["reasoning"] = reasoning_text
            result["reasoning_channel"] = {
                "separation": "separated",
                "truth": {"reasoning_not_merged_into_content": True},
            }
        if isinstance(data, dict) and isinstance(data.get("choices"), list) and len(data["choices"]) > 1:
            result["candidates"] = data["choices"]
        # Attach dialect feature report (honest support states).
        result["transport"] = adaptation.public_dict()
        # Surface logprobs when provider returned them.
        if isinstance(choice0, dict) and choice0.get("logprobs") is not None:
            result["logprobs"] = choice0.get("logprobs")

        tool_record = record_tool_calling_response(tool_record, tool_calls=tool_calls)
        result["tool_calling"] = tool_record.public_dict()
        result["context_bound"] = context_signal.public_dict()

        # Structured / json_schema: repair or fail closed — never pretend success.
        rf = getattr(options, "response_format", response_format)
        if enforce_structured and rf is not None and not tool_calls:
            structured = enforce_structured_response(
                text,
                rf if isinstance(rf, dict) else None,
                fail_closed=structured_fail_closed,
            )
            result["structured"] = structured.public_dict()
            if structured.schema_satisfied:
                result["structured_output"] = structured.parsed
            else:
                # Explicit non-success — callers must not treat as structured OK.
                result["structured_output"] = None
        elif rf is not None and tool_calls:
            result["structured"] = {
                "requested": True,
                "status": "deferred_tool_calls",
                "schemaSatisfied": False,
                "truth": {
                    "structured_success_requires_schema_satisfaction": True,
                    "tool_calls_skip_schema_enforcement_this_turn": True,
                },
            }

        return result

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
        stop: list[str] | tuple[str, ...] | None = None,
        seed: int | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
    ) -> AsyncIterator[tuple[str, str]]:
        """Yield ``(delta_text, model_id)`` from normalized stream frames.

        Cumulative ``message.content`` snapshots are converted to deltas so
        callers never append full snapshots as if they were increments.
        """
        async for frame in self.chat_stream_frames(
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
            model_id=model_id,
            endpoint=endpoint,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            system_prompt=system_prompt,
            behavior_profile_prompt=behavior_profile_prompt,
            cancel=cancel,
            stop=stop,
            seed=seed,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
        ):
            # Append-safe: only deltas (including snapshot-derived suffixes).
            # First snapshot (empty prior) is also append-safe as initial text.
            if frame.kind == "delta" and frame.text:
                yield frame.text, frame.model or model_id or ""
            elif frame.kind == "snapshot" and frame.text:
                yield frame.text, frame.model or model_id or ""
            # replace requires chat_stream_frames — skipped here to avoid corruption.
    async def chat_stream_frames(
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
        stop: list[str] | tuple[str, ...] | None = None,
        seed: int | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        request_id: str | None = None,
        turn_id: str | None = None,
    ) -> AsyncIterator[Any]:
        """Yield typed StreamFrame objects with snapshot→delta normalization."""
        from .streaming import StreamFrame

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
            stop=stop,
            seed=seed,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
        )
        base = self._base_url(endpoint)
        headers = self._headers(api_key)
        headers["Accept"] = "text/event-stream"
        normalizer = StreamNormalizer()
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
                    if "text/event-stream" not in content_type and "json" in content_type:
                        raw = await response.aread()
                        try:
                            data = json.loads(raw.decode("utf-8"))
                            content = data["choices"][0]["message"]["content"]
                            finish = data["choices"][0].get("finish_reason")
                        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
                            raise LLMUnavailable(
                                "LLM stream endpoint returned non-SSE JSON without usable content"
                            ) from exc
                        if not isinstance(content, str) or not content.strip():
                            raise LLMUnavailable("LLM returned an empty streamed response.")
                        for frame in normalizer.ingest_snapshot(
                            content.strip(),
                            finish_reason=str(finish) if finish else "stop",
                        ):
                            frame.model = model
                            frame.request_id = request_id
                            frame.turn_id = turn_id
                            yielded = True
                            yield frame
                        yield StreamFrame(
                            kind="done",
                            sequence=normalizer.next_seq(),
                            finish_reason=str(finish) if finish else "stop",
                            termination_source="json_fallback",
                            model=model,
                            request_id=request_id,
                            turn_id=turn_id,
                            meta=normalizer.stats(),
                        )
                        return
                    async for line in response.aiter_lines():
                        if cancel and cancel.cancelled:
                            await response.aclose()
                            break
                        chunk = parse_openai_sse_line(line)
                        if chunk is None:
                            continue
                        frames = normalizer.ingest_openai_chunk(chunk)
                        for frame in frames:
                            frame.model = model
                            frame.request_id = request_id
                            frame.turn_id = turn_id
                            if frame.kind in {"delta", "snapshot", "replace"} and frame.text:
                                yielded = True
                            yield frame
                            if frame.kind == "done":
                                return
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"LLM stream request failed: {exc}") from exc
        if cancel and cancel.cancelled:
            yield StreamFrame(
                kind="done",
                sequence=normalizer.next_seq(),
                finish_reason="cancelled",
                termination_source="cooperative_cancel",
                model=model,
                request_id=request_id,
                turn_id=turn_id,
                meta=normalizer.stats(),
            )
            return
        if not yielded:
            raise LLMUnavailable("LLM stream completed without tokens.")
        yield StreamFrame(
            kind="done",
            sequence=normalizer.next_seq(),
            finish_reason="stop",
            termination_source="stream_end",
            model=model,
            request_id=request_id,
            turn_id=turn_id,
            meta=normalizer.stats(),
        )