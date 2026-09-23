"""Production model caller adapter — bridges CognitiveRuntime to Model Control Plane.

Does not create a second model client. Uses existing OpenAICompatibleLLM +
ModelControlPlane routing/gateway for real inference.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from Data.modules.model_runtime import LLMUnavailable, OpenAICompatibleLLM
from Data.modules.models import ModelControlError, ModelControlPlane


def _run_coro(coro: Any) -> Any:
    """Run an async coroutine from sync cognition code without nesting loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already inside an event loop (e.g. FastAPI handler) — use a dedicated thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def build_control_plane_model_caller(
    model_plane: ModelControlPlane,
    llm: OpenAICompatibleLLM,
) -> Callable[..., dict[str, Any]]:
    """Return a sync ModelCaller compatible with CognitiveRuntime._call_model.

    Propagates: selected model, messages, max_tokens, usage (when provider
    returns it), model identity, and errors. Does not fabricate answers.
    """

    def model_caller(
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        role: str = "responder",
        run_id: str | None = None,
        trace_id: str | None = None,
        max_tokens: int = 2000,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        _ = role  # orchestration role — public metadata only
        call_id: str | None = None
        provider_id = "unknown"
        model_id = "unknown"
        try:
            routed = model_plane.resolve_for_chat()
            decision = routed["decision"]
            profile = routed["profile"]
            provider_id = routed["provider_id"]
            model_id = routed["model"].id
            call_id = model_plane.gateway.acquire(
                model_id=model_id,
                provider_id=provider_id,
                timeout_seconds=min(llm.settings.llm_timeout_seconds, 30.0),
            )
            model_plane.gateway.record_selection(model_id, trace_id=call_id or trace_id)

            payload_messages: list[dict[str, str]] = []
            if system_prompt and system_prompt.strip():
                payload_messages.append({"role": "system", "content": system_prompt.strip()})
            for item in messages:
                role_s = str(item.get("role") or "user")
                content = str(item.get("content") or "")
                if role_s == "system" and payload_messages and payload_messages[0]["role"] == "system":
                    payload_messages[0]["content"] = (
                        f"{payload_messages[0]['content']}\n\n{content}".strip()
                    )
                else:
                    payload_messages.append({"role": role_s, "content": content})

            effective_max = max_tokens
            if profile.max_tokens is not None:
                effective_max = min(int(profile.max_tokens), int(max_tokens))

            result = _run_coro(
                llm.complete_messages(
                    payload_messages,
                    model_id=routed["provider_model_id"],
                    endpoint=routed["endpoint"],
                    api_key=routed["api_key"],
                    temperature=profile.temperature,
                    max_tokens=effective_max,
                    top_p=profile.top_p,
                )
            )
            model_plane.registry.touch_used(model_id)
            model_plane.gateway.release(model_id=model_id, provider_id=provider_id)
            call_id = None
            return {
                "text": result["text"],
                "content": result["text"],
                "model_id": model_id,
                "provider_model_id": routed["provider_model_id"],
                "usage": result.get("usage") or {},
                "route": decision.public_dict(),
                "run_id": run_id,
                "trace_id": call_id or trace_id,
                "usage_source": result.get("usage_source") or "unavailable",
            }
        except (ModelControlError, LLMUnavailable) as exc:
            if call_id:
                model_plane.gateway.release(
                    model_id=model_id,
                    provider_id=provider_id,
                    error=getattr(exc, "code", type(exc).__name__),
                )
            raise
        except Exception:
            if call_id:
                model_plane.gateway.release(
                    model_id=model_id,
                    provider_id=provider_id,
                    error="model_caller_error",
                )
            raise

    # Mark for composition health probes.
    model_caller.__leviathan_production_caller__ = True  # type: ignore[attr-defined]
    model_caller.__wrapped_plane__ = model_plane  # type: ignore[attr-defined]
    assert inspect.isfunction(model_caller) or callable(model_caller)
    return model_caller
