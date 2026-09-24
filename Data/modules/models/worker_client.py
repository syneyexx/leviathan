"""Process-safe Model Control Plane client for external workers.

Uses the shared ModelStore / ModelRegistry / ModelRouter (same database as the
API Model Control Plane) and invokes inference over OpenAICompatibleLLM HTTP
transport.

Does NOT:
- construct or own ModelControlPlane / ResidencyManager
- load model weights in the worker process
- start llama.cpp / vLLM serving workers
- silently degrade to deterministic mode when a model is configured

Managed serving endpoints are discovered from persisted serving-worker rows when
present; otherwise the resolved model/provider endpoint (or settings.llm_base_url)
is used. Absence of a usable endpoint is surfaced as ModelControlError.
"""

from __future__ import annotations

from typing import Any, Callable

from Data.modules.models.async_bridge import run_coro_sync
from Data.modules.models.contracts import ModelRequest
from Data.modules.models.errors import ModelControlError, ROUTER_EXHAUSTED, VALIDATION_ERROR
from Data.modules.models.gateway import ModelGateway
from Data.modules.models.profiles import ProfileService
from Data.modules.models.registry import ModelRegistry
from Data.modules.models.router import ModelRouter
from Data.modules.models.store import ModelStore


_ORCH_TO_MODEL_ROLE = {
    "responder": None,
    "critic": None,
    "planner": None,
    "researcher": "research",
    "coder": "coding",
}


class ProcessSafeModelClient:
    """Thin cross-process facade over canonical Model Store routing + HTTP transport."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.store = ModelStore(settings.database_path)
        self.registry = ModelRegistry(self.store)
        self.profiles = ProfileService(self.store)
        # Gateway here is only the admission counter required by ModelRouter —
        # it does not start serving processes.
        self.gateway = ModelGateway(
            global_limit=int(getattr(settings.resources, "max_model_concurrency", 4) or 4)
        )
        self.router = ModelRouter(
            self.store,
            self.gateway,
            get_models=self.registry.list_descriptors,
        )
        from Data.modules.model_runtime import OpenAICompatibleLLM

        self.llm = OpenAICompatibleLLM(settings)

    def resolve(
        self,
        *,
        preferred_role: str | None = None,
        explicit_model_id: str | None = None,
        job_class: str = "BACKGROUND",
    ) -> dict[str, Any]:
        role = preferred_role
        if role in {"general", "General"}:
            role = "chat"
        decision = self.router.resolve(
            ModelRequest(
                explicit_model_id=explicit_model_id,
                preferred_role=role,
                job_class=job_class,
            )
        )
        model = self.registry.get(decision.model_id)
        profile = self.profiles.get_or_default(model.id)
        provider = self.store.get_provider(model.provider_id)
        endpoint = model.endpoint or (provider["endpoint"] if provider else self.settings.llm_base_url)
        api_key = (provider.get("api_key_ciphertext") if provider else None) or self.settings.llm_api_key
        backend_model_id = str(model.metadata.get("provider_model_id") or model.display_name)
        endpoint = self._prefer_serving_endpoint(model.id, endpoint)
        return {
            "model": model,
            "profile": profile,
            "route": decision,
            "endpoint": endpoint,
            "api_key": api_key,
            "backend_model_id": backend_model_id,
            "provider_id": model.provider_id,
            "context_window": model.context_window,
        }

    def _prefer_serving_endpoint(self, model_id: str, fallback: str | None) -> str | None:
        try:
            for row in self.store.list_serving_workers():
                if str(row.get("model_id") or "") != str(model_id):
                    continue
                state = str(row.get("state") or "").lower()
                if state and state not in {"ready", "active", "busy", "idle", "running"}:
                    continue
                ep = (row.get("endpoint") or "").strip()
                if ep:
                    return ep
        except Exception:  # noqa: BLE001
            pass
        return (fallback or "").strip() or None


def build_process_safe_model_caller(settings: Any) -> Callable[..., dict[str, Any]]:
    """Build a sync model caller for external workers (Job Kernel research pool)."""
    from Data.modules.model_runtime import LLMUnavailable

    client = ProcessSafeModelClient(settings)

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
        job_class: str = "BACKGROUND",
        **_kwargs: Any,
    ) -> dict[str, Any]:
        routing_role = model_role
        if routing_role is None:
            routing_role = _ORCH_TO_MODEL_ROLE.get(role)
        if routing_role is None and domain in {"research", "coding", "chat", "trading"}:
            routing_role = "chat" if domain == "chat" else domain

        try:
            resolved = client.resolve(
                preferred_role=routing_role,
                explicit_model_id=explicit_model_id,
                job_class=job_class,
            )
        except ModelControlError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ModelControlError(
                code=ROUTER_EXHAUSTED,
                message=f"Model resolve failed in worker client: {exc}",
                http_status=503,
                retryable=True,
            ) from exc

        endpoint = resolved.get("endpoint")
        if not endpoint:
            raise ModelControlError(
                code=VALIDATION_ERROR,
                message=(
                    "No model endpoint available for research worker. "
                    "Start managed serving or configure llm_base_url / provider endpoint."
                ),
                model_id=getattr(resolved["model"], "id", None),
                http_status=503,
                retryable=True,
            )

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

        profile = resolved["profile"]
        effective_max = max_tokens
        if getattr(profile, "max_tokens", None) is not None:
            effective_max = min(int(profile.max_tokens), int(max_tokens))

        async def _run() -> dict[str, Any]:
            result = await client.llm.complete_messages(
                payload_messages,
                model_id=resolved["backend_model_id"],
                endpoint=endpoint,
                api_key=resolved["api_key"],
                temperature=getattr(profile, "temperature", None),
                max_tokens=effective_max,
                top_p=getattr(profile, "top_p", None),
            )
            route = resolved["route"]
            return {
                "text": result["text"],
                "content": result["text"],
                "model_id": resolved["model"].id,
                "provider_model_id": resolved["backend_model_id"],
                "usage": result.get("usage") or {},
                "route": route.public_dict() if hasattr(route, "public_dict") else {},
                "run_id": run_id,
                "trace_id": trace_id,
                "usage_source": result.get("usage_source") or "unavailable",
                "context_window": resolved["context_window"],
                "endpoint": endpoint,
                "transport": "process_safe_model_client",
            }

        try:
            return run_coro_sync(_run())
        except (ModelControlError, LLMUnavailable):
            raise

    model_caller.__leviathan_production_caller__ = True  # type: ignore[attr-defined]
    model_caller.__process_safe_client__ = True  # type: ignore[attr-defined]
    model_caller.__wrapped_client__ = client  # type: ignore[attr-defined]
    return model_caller
