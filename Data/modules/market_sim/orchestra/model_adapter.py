"""Model access for trade agents — Model Control Plane only (no private client).

Mirrors ``Data/modules/coding/llm_adapter.py``: sync bridge onto
``ModelControlPlane.inference_session`` with a trading consumer/role so the router can
place e.g. news extraction on a small local model and strategy authoring on the main model.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Protocol


class TradingModel(Protocol):
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        role: str,
        temperature: float = 0.1,
        model_id: str | None = None,
    ) -> tuple[str, str | None]: ...


class TradingModelAdapter:
    """Bridge → ModelControlPlane.inference_session(consumer='trading', model_role='trading.<role>')."""

    name = "model_control_plane"

    def __init__(self, model_plane: Any, llm: Any | None = None, *, timeout_seconds: float = 300.0) -> None:
        self.model_plane = model_plane
        self.llm = llm
        self.timeout_seconds = timeout_seconds

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        role: str,
        temperature: float = 0.1,
        model_id: str | None = None,
    ) -> tuple[str, str | None]:
        from Data.modules.models.async_bridge import run_coro_sync

        model_role = f"trading.{role}"

        async def _run() -> tuple[str, str | None]:
            async with self.model_plane.inference_session(
                llm=self.llm,
                consumer="trading",
                domain="market_sim",
                model_role=model_role,
                preferred_role=model_role,
                explicit_model_id=model_id,
                job_class="BACKGROUND",
            ) as session:
                result = await session.complete_messages(messages, temperature=temperature)
                text = str(result.get("text") or "")
                mid = session.model_id or model_id
                return text, str(mid) if mid else model_id

        return run_coro_sync(_run(), timeout=self.timeout_seconds)


class ScriptedTradingModel:
    """Deterministic fake for tests and offline campaigns: answers from a queue or a callable."""

    name = "scripted"

    def __init__(
        self,
        responses: list[str | dict[str, Any]] | None = None,
        *,
        responder: Callable[[list[dict[str, str]], str], str | dict[str, Any]] | None = None,
        model_id: str = "scripted-trading-model",
    ) -> None:
        self._queue = list(responses or [])
        self._responder = responder
        self.model_id = model_id
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        role: str,
        temperature: float = 0.1,
        model_id: str | None = None,
    ) -> tuple[str, str | None]:
        self.calls.append({"role": role, "messages": messages, "temperature": temperature})
        if self._responder is not None:
            out = self._responder(messages, role)
        elif self._queue:
            out = self._queue.pop(0)
        else:
            raise RuntimeError("ScriptedTradingModel exhausted")
        text = out if isinstance(out, str) else json.dumps(out)
        return text, model_id or self.model_id


class UnavailableTradingModel:
    """Honest stand-in when no Model Control Plane is bound: every call reports UNAVAILABLE."""

    name = "unavailable"

    def complete(self, messages: list[dict[str, str]], *, role: str, temperature: float = 0.1, model_id: str | None = None) -> tuple[str, str | None]:
        raise RuntimeError("MODEL_UNAVAILABLE: no Model Control Plane bound for trading agents")
