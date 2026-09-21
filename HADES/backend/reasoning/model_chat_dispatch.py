"""Shared model-chat dispatch used by main.gateway_chat (Phase 10 real path).

Keeps Neural Mode OFF as a hard Standard Runtime bypass. Heavy neural imports
remain lazy.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping

from reasoning.model_gateway import ModelGateway
from reasoning.model_runtime_bridge import gateway_chat_with_runtime
from reasoning.neural_settings import (
    build_runtime_selection,
    make_toy_neural_chat_hook,
    neural_allow,
    resolve_neural_mode,
)


async def dispatch_model_chat(
    payload: dict[str, Any],
    *,
    chat_fn: Callable[..., Any],
    gateway: ModelGateway,
    settings: Mapping[str, Any],
    model_id: str | None = None,
    endpoint: str = "",
    surface: str = "chat",
    run_id: str | None = None,
    cancel_event: asyncio.Event | None = None,
    neural_infer_fn: Callable[[dict[str, Any]], Any] | None | object = ...,
) -> dict[str, Any]:
    """Route one chat call through Standard or Neural selection policy.

    When ``neural_infer_fn is ...`` (default), a toy hook is created only if
    Neural Mode is enabled and allowed. Tests may inject a hook or ``None``.
    """
    mid = str(model_id or payload.get("model") or "")
    cfg = gateway.snapshot_config(endpoint=endpoint, source=surface)
    mode = resolve_neural_mode(settings)
    if mode == "off" or not neural_allow(settings):
        return await gateway.chat(
            chat_fn,
            payload,
            model_id=mid,
            endpoint=endpoint,
            surface=surface,
            run_id=run_id,
            config=cfg,
            cancel_event=cancel_event,
        )

    selection = build_runtime_selection(settings)
    if neural_infer_fn is ...:
        hook = make_toy_neural_chat_hook() if selection.allow_neural else None
    else:
        hook = neural_infer_fn  # type: ignore[assignment]
    body = dict(payload)
    body["_hades_neural_mode"] = mode
    return await gateway_chat_with_runtime(
        body,
        chat_fn=chat_fn,
        gateway=gateway,
        selection=selection,
        neural_infer_fn=hook,
        model_id=mid,
        endpoint=endpoint,
        surface=surface,
        run_id=run_id,
        cancel_event=cancel_event,
    )
