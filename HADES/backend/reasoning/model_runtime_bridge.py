"""ModelGateway ↔ Neural Runtime bridge (Phase 10).

Routes a single model call through existing ModelGateway capacity/retries while
honoring explicit Standard vs Neural selection. Does not replace reasoning,
tools, or verification. Lazy-imports neural code so normal HADES never requires
torch.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Callable, Mapping

from reasoning.model_gateway import ModelCallFailed, ModelGateway, model_gateway
from reasoning.runtime_selection import (
    NeuralRequirement,
    RuntimeKind,
    RuntimeSelectionDecision,
    RuntimeSelectionRequest,
    select_model_runtime,
    should_fail_closed,
)


def _attach_runtime_meta(response: dict[str, Any], decision: RuntimeSelectionDecision, **extra: Any) -> dict[str, Any]:
    meta = {
        "runtime": decision.to_dict(),
        **extra,
    }
    # Non-authoritative observability only — callers must not treat this as evidence.
    out = dict(response)
    existing = dict(out.get("_hades_runtime") or {})
    existing.update(meta)
    out["_hades_runtime"] = existing
    return out


async def gateway_chat_with_runtime(
    payload: dict[str, Any],
    *,
    chat_fn: Callable[..., Any],
    gateway: ModelGateway | None = None,
    selection: RuntimeSelectionRequest | Mapping[str, Any] | None = None,
    neural_infer_fn: Callable[[dict[str, Any]], Any] | None = None,
    shadow_infer_fn: Callable[[dict[str, Any]], Any] | None = None,
    model_id: str | None = None,
    endpoint: str = "",
    surface: str = "chat",
    run_id: str | None = None,
    cancel_event: asyncio.Event | None = None,
    shadow_rng: random.Random | None = None,
) -> dict[str, Any]:
    """Execute one chat call with auditable runtime selection.

    ``chat_fn`` is the Standard Runtime (typically LM Studio).
    ``neural_infer_fn`` / ``shadow_infer_fn`` are optional research hooks; when
    omitted, Neural READ/SHADOW cannot become primary and selection falls back
    or fails closed per policy.
    """
    gw = gateway or model_gateway
    req = (
        selection
        if isinstance(selection, RuntimeSelectionRequest)
        else RuntimeSelectionRequest.from_dict(selection)
    )
    # If hooks missing, reflect unreadiness even when caller claimed ready.
    effective = RuntimeSelectionRequest(
        neural_mode=req.neural_mode,
        neural_requirement=req.neural_requirement,
        shadow_sample_rate=req.shadow_sample_rate,
        neural_available=req.neural_available and neural_infer_fn is not None,
        neural_ready=req.neural_ready and neural_infer_fn is not None,
        allow_neural=req.allow_neural,
    )
    decision = select_model_runtime(effective)
    if should_fail_closed(decision):
        code = str(decision.fallback_reason or "neural_runtime_unavailable")
        message = (
            "Neural READ is research-only until LM fusion exists (not product ready)"
            if code == "neural_read_not_product_ready"
            else "Neural Runtime required but unavailable"
        )
        raise ModelCallFailed(
            message,
            code=code,
            detail=decision.to_dict(),
        )

    fallback = decision.fallback_reason

    if decision.primary is RuntimeKind.NEURAL:
        assert neural_infer_fn is not None

        async def _neural_chat(p: dict[str, Any]) -> dict[str, Any]:
            result = neural_infer_fn(p)
            if asyncio.iscoroutine(result):
                result = await result
            if not isinstance(result, dict):
                raise ModelCallFailed(
                    "neural infer hook must return a dict response",
                    detail={"type": type(result).__name__},
                )
            return result

        response = await gw.chat(
            _neural_chat,
            payload,
            model_id=model_id,
            endpoint=endpoint or "neural",
            surface=surface,
            run_id=run_id,
            cancel_event=cancel_event,
            fallback_reason=fallback,
        )
        out = _attach_runtime_meta(response, decision)
        gw._metrics["last_runtime"] = dict(out.get("_hades_runtime") or {})
        return out

    # Standard primary path — identical to conventional ModelGateway.chat.
    response = await gw.chat(
        chat_fn,
        payload,
        model_id=model_id,
        endpoint=endpoint,
        surface=surface,
        run_id=run_id,
        cancel_event=cancel_event,
        fallback_reason=fallback,
    )
    out = _attach_runtime_meta(response, decision)

    # SHADOW: never mutate user-visible content; optional diagnostics only.
    if decision.shadow and decision.neural_mode == "shadow":
        rng = shadow_rng or random.Random()
        if rng.random() <= float(effective.shadow_sample_rate):
            hook = shadow_infer_fn or neural_infer_fn
            shadow_meta: dict[str, Any] = {"sampled": True}
            if hook is None:
                shadow_meta["error"] = "neural_shadow_hook_missing"
            else:
                try:
                    shadow_result = hook(payload)
                    if asyncio.iscoroutine(shadow_result):
                        shadow_result = await shadow_result
                    shadow_meta["ok"] = True
                    if isinstance(shadow_result, dict):
                        # Store only non-content diagnostics keys when present.
                        shadow_meta["diagnostics"] = {
                            k: shadow_result.get(k)
                            for k in ("latency_ms", "mode", "bypassed", "base_checksum", "fusion_events")
                            if k in shadow_result
                        }
                except Exception as exc:  # noqa: BLE001 — shadow must not fail primary
                    shadow_meta["ok"] = False
                    shadow_meta["error"] = str(exc)[:300]
            content_before = out.get("choices")
            out["_hades_runtime"]["shadow"] = shadow_meta
            if out.get("choices") != content_before:
                raise ModelCallFailed("shadow path mutated user-visible response")
        else:
            out["_hades_runtime"]["shadow"] = {"sampled": False}

    gw._metrics["last_runtime"] = dict(out.get("_hades_runtime") or {})
    return out


def standard_only_request() -> RuntimeSelectionRequest:
    """Explicit OFF / Standard selection for conventional HADES callers."""
    return RuntimeSelectionRequest(
        neural_mode="off",
        neural_requirement=NeuralRequirement.OFF,
        shadow_sample_rate=0.0,
        allow_neural=False,
    )
