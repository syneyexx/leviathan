"""Sync adapter so CodingLoop uses the shared Model Control Plane.

Coding does not own a private model client — this bridges to
ModelControlPlane.inference_session (router + residency + gateway + transport).
"""

from __future__ import annotations

from typing import Any

from Data.modules.models.async_bridge import run_coro_sync


class CodingLLMAdapter:
    """Bridge CodingLoop.complete(...) → ModelControlPlane.inference_session."""

    def __init__(self, model_plane: Any, llm: Any | None = None) -> None:
        self.model_plane = model_plane
        self.llm = llm
        self.last_tool_calls: list[dict[str, Any]] = []
        self.last_tools_requested: list[dict[str, Any]] | None = None
        self.last_completion_source: str = "text"
        if llm is not None and hasattr(model_plane, "bind_llm"):
            model_plane.bind_llm(llm)

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        model_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[str, str | None]:
        self.last_tool_calls = []
        self.last_tools_requested = list(tools) if tools else None
        self.last_completion_source = "text"

        async def _run() -> tuple[str, str | None]:
            async with self.model_plane.inference_session(
                llm=self.llm,
                consumer="coding",
                domain="coding",
                model_role="coding",
                preferred_role="coding",
                explicit_model_id=model_id,
                job_class="INTERACTIVE",
            ) as session:
                kwargs: dict[str, Any] = {"temperature": temperature}
                if tools:
                    kwargs["tools"] = tools
                result = await session.complete_messages(messages, **kwargs)
                text = str(result.get("text") or "")
                raw_calls = result.get("tool_calls") or result.get("toolCalls") or []
                calls: list[dict[str, Any]] = []
                if isinstance(raw_calls, list):
                    for item in raw_calls:
                        if isinstance(item, dict):
                            calls.append(dict(item))
                self.last_tool_calls = calls
                if calls:
                    self.last_completion_source = "native_tools"
                mid = session.model_id or model_id
                return text, str(mid) if mid else model_id

        return run_coro_sync(_run(), timeout=600)
