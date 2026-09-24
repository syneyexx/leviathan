"""Production model caller adapter — bridges CognitiveRuntime to Model Control Plane.

Uses the canonical inference_session path (residency + gateway + transport).
Orchestration role ≠ model routing role.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from Data.modules.model_runtime import LLMUnavailable, OpenAICompatibleLLM
from Data.modules.models import ModelControlError, ModelControlPlane
from Data.modules.models.async_bridge import run_coro_sync


# Map orchestration roles → model routing roles when domain not provided.
_ORCH_TO_MODEL_ROLE = {
    "responder": None,  # fall through to domain / chat
    "critic": None,
    "planner": None,
    "researcher": "research",
    "coder": "coding",
}


def build_control_plane_model_caller(
    model_plane: ModelControlPlane,
    llm: OpenAICompatibleLLM,
) -> Callable[..., dict[str, Any]]:
    """Return a sync ModelCaller compatible with CognitiveRuntime._call_model."""

    model_plane.bind_llm(llm)

    def model_caller(
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        role: str = "responder",
        run_id: str | None = None,
        trace_id: str | None = None,
        max_tokens: int = 2000,
        domain: str | None = None,
        model_role: str | None = None,
        explicit_model_id: str | None = None,
        job_class: str = "INTERACTIVE",
        **_kwargs: Any,
    ) -> dict[str, Any]:
        # orchestration role is public metadata — not a model id lookup key
        routing_role = model_role
        if routing_role is None:
            routing_role = _ORCH_TO_MODEL_ROLE.get(role)
        if routing_role is None and domain in {"research", "coding", "chat", "trading"}:
            routing_role = "chat" if domain == "chat" else domain

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

        async def _run() -> dict[str, Any]:
            async with model_plane.inference_session(
                consumer=f"cognition:{role}",
                domain=domain,
                model_role=routing_role,
                run_id=run_id,
                trace_id=trace_id,
                job_class=job_class,
                explicit_model_id=explicit_model_id,
                preferred_role=routing_role,
            ) as session:
                result = await session.complete_messages(
                    payload_messages,
                    max_tokens=max_tokens,
                )
                return {
                    "text": result["text"],
                    "content": result["text"],
                    "model_id": session.model_id,
                    "provider_model_id": session.backend_model_id,
                    "usage": result.get("usage") or {},
                    "route": session.target.route.public_dict(),
                    "run_id": run_id,
                    "trace_id": session.call_id or trace_id,
                    "usage_source": result.get("usage_source") or "unavailable",
                    "context_window": session.context_window,
                }

        try:
            return run_coro_sync(_run())
        except (ModelControlError, LLMUnavailable):
            raise

    model_caller.__leviathan_production_caller__ = True  # type: ignore[attr-defined]
    model_caller.__wrapped_plane__ = model_plane  # type: ignore[attr-defined]
    assert inspect.isfunction(model_caller) or callable(model_caller)
    return model_caller
