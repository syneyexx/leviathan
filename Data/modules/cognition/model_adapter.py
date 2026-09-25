"""Production model caller adapter — bridges CognitiveRuntime to Model Control Plane.

Uses the canonical inference_session path (residency + gateway + transport).
Orchestration role ≠ model routing role.

Native reasoning hints come from InferenceComputeController — never invented
from model names. Generic providers receive empty hints (TTC path).
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from Data.modules.model_runtime import LLMUnavailable, OpenAICompatibleLLM
from Data.modules.models import ModelControlError, ModelControlPlane
from Data.modules.models.async_bridge import run_coro_sync

from .inference_compute import InferenceComputeController
from .neural_compute import NeuralComputeBudget, ReasoningCapabilityProfile


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
    inference_controller = InferenceComputeController()

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
        neural_budget: NeuralComputeBudget | None = None,
        capability_profile: ReasoningCapabilityProfile | None = None,
        provider_family: str | None = None,
        reasoning_mode: str | None = None,
        settings_capability_override: dict[str, Any] | None = None,
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
                family = provider_family
                if family is None:
                    family = getattr(session, "provider_id", None) or "generic"
                    # Normalize common provider ids to families.
                    fam = str(family).lower()
                    if "ollama" in fam:
                        family = "ollama"
                    elif "llama" in fam:
                        family = "llama_cpp"
                    elif "lm" in fam and "studio" in fam:
                        family = "lm_studio"
                    elif "vllm" in fam:
                        family = "vllm_class"
                    elif fam not in {"generic"}:
                        family = "openai_compatible"

                plan = inference_controller.prepare(
                    mode=reasoning_mode,
                    neural_budget=neural_budget,
                    capability_profile=capability_profile,
                    provider_family=str(family),
                    settings_capability_override=settings_capability_override,
                )
                result = await session.complete_messages(
                    payload_messages,
                    max_tokens=max_tokens,
                    provider_hints=plan.provider_hints or None,
                )
                normalized = inference_controller.normalize_result(
                    plan=plan,
                    raw_result=result if isinstance(result, dict) else {},
                    public_text=str((result or {}).get("text") or "") if isinstance(result, dict) else "",
                )
                usage = dict(normalized.usage)
                # Preserve non-reasoning usage fields from provider result.
                if isinstance(result, dict) and isinstance(result.get("usage"), dict):
                    for k, v in result["usage"].items():
                        usage.setdefault(k, v)
                return {
                    "text": normalized.text,
                    "content": normalized.text,
                    "model_id": session.model_id,
                    "provider_model_id": session.backend_model_id,
                    "usage": usage,
                    "route": session.target.route.public_dict(),
                    "run_id": run_id,
                    "trace_id": session.call_id or trace_id,
                    "usage_source": result.get("usage_source") if isinstance(result, dict) else "unavailable",
                    "context_window": session.context_window,
                    "inference_compute": normalized.public_dict(),
                    "inference_plan": plan.public_dict(),
                    # Never include private CoT.
                    "truth": {
                        "private_cot_not_returned": True,
                        "native_hints_only_when_supported": plan.path == "native",
                    },
                }

        try:
            return run_coro_sync(_run())
        except (ModelControlError, LLMUnavailable):
            raise

    model_caller.__leviathan_production_caller__ = True  # type: ignore[attr-defined]
    model_caller.__wrapped_plane__ = model_plane  # type: ignore[attr-defined]
    model_caller.__inference_controller__ = inference_controller  # type: ignore[attr-defined]
    assert inspect.isfunction(model_caller) or callable(model_caller)
    return model_caller
