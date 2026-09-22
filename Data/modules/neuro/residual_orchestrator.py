"""ResidualOrchestrator — control-plane residual budget / layer selection.

EXTERNAL-FIRST: orchestration stays in Core; actual residual mutation happens on the
ResidualStreamPort (toy / HF / vLLM / llama.cpp / TRT adapters). Never authorizes
side-effects — injects remain advisory until ExecutionGateway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .residual import (
    ResidualForwardRequest,
    ResidualForwardResult,
    ResidualHookPoint,
    ResidualInjectReceipt,
    ResidualInjectRequest,
    ResidualStreamPort,
    UnsupportedResidualRuntime,
)

VALID_MODES = frozenset({"ADDITIVE", "GATED", "REPLACE_SLICE", "DISABLED"})


@dataclass(frozen=True)
class ResidualInjectPlan:
    """Planned inject — not authority, not success."""

    hook: ResidualHookPoint
    mode: str
    scale: float
    source: str
    payload_ref: str | None = None
    reason: str = ""

    def to_request(self, *, run_id: str | None = None) -> ResidualInjectRequest:
        return ResidualInjectRequest(
            hook=self.hook,
            mode=self.mode,
            scale=self.scale,
            source=self.source,
            payload_ref=self.payload_ref,
            run_id=run_id,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "hook": self.hook.public_dict(),
            "mode": self.mode,
            "scale": self.scale,
            "source": self.source,
            "payload_ref": self.payload_ref,
            "reason": self.reason,
            "truth": {
                "inject_plan_is_not_authority": True,
                "neural_signal_is_not_authority": True,
            },
        }


@dataclass(frozen=True)
class ResidualOrchestrationReport:
    enabled: bool
    residual_available: bool
    plans: tuple[ResidualInjectPlan, ...]
    receipts: tuple[ResidualInjectReceipt, ...]
    forward: ResidualForwardResult | None
    selected_layers: tuple[int, ...]
    detail: str
    telemetry: dict[str, Any] = field(default_factory=dict)
    alpha_budget: float = 0.0
    alpha_used: float = 0.0
    streaming_degraded: bool = False

    def public_dict(self) -> dict[str, Any]:
        applied = any(r.applied for r in self.receipts)
        implemented = any(r.implemented for r in self.receipts) or self.residual_available
        return {
            "enabled": self.enabled,
            "residual_available": self.residual_available,
            "plans": [p.public_dict() for p in self.plans],
            "receipts": [r.public_dict() for r in self.receipts],
            "forward": self.forward.public_dict() if self.forward else None,
            "selected_layers": list(self.selected_layers),
            "detail": self.detail,
            "telemetry": self.telemetry,
            "alpha_budget": self.alpha_budget,
            "alpha_used": self.alpha_used,
            "streaming_degraded": self.streaming_degraded,
            "truth": {
                "neural_signal_is_not_authority": True,
                "residual_injection_is_not_authority": True,
                "residual_implemented": bool(implemented),
                "residual_applied": bool(applied),
                "unapplied_is_not_success": True,
                "model_output_is_not_evidence": True,
                "discoverable_is_not_authorized": True,
                "unsupported_is_not_failure_of_core": True,
                "streaming_degraded": bool(self.streaming_degraded),
            },
        }


class ResidualOrchestrator:
    """Budget α/scale and mid+late hook layers; coordinate multi-inject forwards."""

    def __init__(
        self,
        *,
        residual_port: ResidualStreamPort | None = None,
        enabled: bool = False,
        hook_layers: Sequence[int] | None = None,
        default_mode: str = "ADDITIVE",
        max_injects: int = 4,
        base_scale: float = 0.12,
        max_total_alpha: float = 0.45,
        observability: Any | None = None,
    ) -> None:
        self.residual_port = residual_port or UnsupportedResidualRuntime()
        self.enabled = enabled
        self.hook_layers = tuple(int(x) for x in (hook_layers or ()))
        self.default_mode = default_mode if default_mode in VALID_MODES else "ADDITIVE"
        self.max_injects = max(0, min(int(max_injects), 16))
        self.base_scale = max(0.0, float(base_scale))
        self.max_total_alpha = max(0.0, float(max_total_alpha))
        self.observability = observability
        self.telemetry: dict[str, Any] = {
            "orchestrations": 0,
            "injects_planned": 0,
            "injects_applied": 0,
            "degraded": 0,
            "alpha_budget_hits": 0,
            "degrade_reasons": {},
        }

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self.observability is None:
            return
        try:
            self.observability.emit("neuro", name, payload=payload)
        except Exception:  # noqa: BLE001 — telemetry must never raise into control path
            return

    def select_layers(
        self,
        *,
        complexity: str = "medium",
        token_budget: int = 6000,
        prefer_mid: bool = True,
    ) -> tuple[ResidualHookPoint, ...]:
        hooks = list(self.residual_port.list_hook_points())
        if not hooks:
            return ()
        if self.hook_layers:
            wanted = set(self.hook_layers)
            selected = [h for h in hooks if h.layer_index in wanted]
            if selected:
                return tuple(selected[: self.max_injects])
        n = len(hooks)
        mid = max(0, n // 3)
        late = max(mid + 1, (2 * n) // 3)
        complexity_l = (complexity or "").lower()
        if complexity_l in {"low", "lean", "simple"}:
            idxs = [mid] if prefer_mid else [late]
        elif complexity_l in {"high", "complex", "hard"} and token_budget >= 4000:
            idxs = [mid, late]
            if n >= 6 and token_budget >= 8000:
                idxs.append(min(n - 1, late + 1))
        else:
            idxs = [mid, late] if token_budget >= 3000 else [mid]
        # Deduplicate while preserving order.
        seen: set[int] = set()
        out: list[ResidualHookPoint] = []
        for i in idxs:
            i = max(0, min(n - 1, i))
            if i in seen:
                continue
            seen.add(i)
            out.append(hooks[i])
            if len(out) >= self.max_injects:
                break
        return tuple(out)

    def budget_scale(self, *, complexity: str = "medium", residual_available: bool = False) -> float:
        if not residual_available:
            return 0.0
        complexity_l = (complexity or "").lower()
        scale = self.base_scale
        if complexity_l in {"high", "complex", "hard"}:
            scale = min(0.35, scale * 1.5)
        elif complexity_l in {"low", "lean", "simple"}:
            scale = max(0.05, scale * 0.6)
        return round(scale, 4)

    def _distribute_alpha(
        self,
        *,
        per_layer: float,
        n_layers: int,
    ) -> tuple[list[float], float, float]:
        """Return (scales, alpha_budget, alpha_used) under max_total_alpha."""
        if n_layers <= 0 or per_layer <= 0:
            return [], self.max_total_alpha, 0.0
        raw_total = per_layer * n_layers
        budget = self.max_total_alpha
        if raw_total <= budget:
            scales = [round(per_layer, 4) for _ in range(n_layers)]
            return scales, budget, round(sum(scales), 4)
        # Shrink uniformly so Σα ≤ budget.
        self.telemetry["alpha_budget_hits"] = int(self.telemetry.get("alpha_budget_hits") or 0) + 1
        factor = budget / raw_total if raw_total > 0 else 0.0
        scales = [round(per_layer * factor, 4) for _ in range(n_layers)]
        return scales, budget, round(sum(scales), 4)

    def plan_injects(
        self,
        *,
        complexity: str = "medium",
        token_budget: int = 6000,
        payload_ref: str | None = None,
        source: str = "neuro.residual_orchestrator",
        mode: str | None = None,
    ) -> tuple[ResidualInjectPlan, ...]:
        if not self.enabled:
            return ()
        available = self.residual_port.supports_residuals()
        layers = self.select_layers(complexity=complexity, token_budget=token_budget)
        if not layers:
            return ()
        scale = self.budget_scale(complexity=complexity, residual_available=available)
        inject_mode = mode if mode in VALID_MODES else self.default_mode
        if not available:
            inject_mode = "DISABLED"
            scale = 0.0
        scales, _budget, _used = self._distribute_alpha(per_layer=scale, n_layers=len(layers))
        plans: list[ResidualInjectPlan] = []
        for idx, hook in enumerate(layers):
            # Mid layers: ADDITIVE; late layers: GATED when complex.
            layer_mode = inject_mode
            if available and inject_mode != "DISABLED" and idx == len(layers) - 1:
                if (complexity or "").lower() in {"high", "complex", "hard"}:
                    layer_mode = "GATED"
            layer_scale = scales[idx] if layer_mode != "DISABLED" and scales else 0.0
            plans.append(
                ResidualInjectPlan(
                    hook=hook,
                    mode=layer_mode,
                    scale=layer_scale,
                    source=source,
                    payload_ref=payload_ref,
                    reason=(
                        f"orchestrator layer={hook.layer_index} complexity={complexity} "
                        f"alpha={layer_scale}"
                    ),
                )
            )
        return tuple(plans)

    def orchestrate(
        self,
        *,
        messages: list[dict[str, str]] | None = None,
        complexity: str = "medium",
        token_budget: int = 6000,
        payload_ref: str | None = None,
        run_forward: bool = False,
        engage_cortex: bool = False,
        critic_rounds: int = 0,
        extra_injects: Sequence[ResidualInjectRequest] = (),
        mode: str | None = None,
        run_id: str | None = None,
    ) -> ResidualOrchestrationReport:
        self.telemetry["orchestrations"] += 1
        available = self.residual_port.supports_residuals()
        streaming_forward = bool(
            getattr(self.residual_port, "supports_streaming_forward", lambda: False)()
        )
        if not self.enabled:
            self.telemetry["degraded"] += 1
            report = ResidualOrchestrationReport(
                enabled=False,
                residual_available=available,
                plans=(),
                receipts=(),
                forward=None,
                selected_layers=(),
                detail="Residual orchestrator feature flag OFF",
                telemetry=dict(self.telemetry),
                alpha_budget=self.max_total_alpha,
                alpha_used=0.0,
                streaming_degraded=False,
            )
            self._emit("residual_orchestrate", report.public_dict())
            return report

        plans = self.plan_injects(
            complexity=complexity,
            token_budget=token_budget,
            payload_ref=payload_ref,
            mode=mode,
        )
        alpha_used = round(sum(p.scale for p in plans), 4)
        self.telemetry["injects_planned"] += len(plans)
        requests = [p.to_request(run_id=run_id) for p in plans]
        requests.extend(list(extra_injects)[: max(0, self.max_injects - len(requests))])

        receipts: list[ResidualInjectReceipt] = []
        degrade_reasons = dict(self.telemetry.get("degrade_reasons") or {})
        for req in requests:
            receipt = self.residual_port.inject(req)
            receipts.append(receipt)
            if receipt.applied:
                self.telemetry["injects_applied"] += 1
            if receipt.degraded_to_chat_completions or not receipt.applied:
                self.telemetry["degraded"] += 1
                key = receipt.reason or "unapplied"
                degrade_reasons[key] = int(degrade_reasons.get(key) or 0) + 1
        self.telemetry["degrade_reasons"] = degrade_reasons

        forward: ResidualForwardResult | None = None
        if run_forward and messages is not None:
            # Multi-inject coordination: one forward with the full inject set.
            forward = self.residual_port.run_forward(
                ResidualForwardRequest(
                    messages=messages,
                    engage_cortex=engage_cortex,
                    critic_rounds=critic_rounds,
                    inject=tuple(requests),
                    metadata={
                        "orchestrator": True,
                        "complexity": complexity,
                        "alpha_budget": self.max_total_alpha,
                        "alpha_used": alpha_used,
                        "multi_inject": len(requests),
                    },
                )
            )
            for receipt in forward.receipts:
                # Avoid double-counting injects already applied above when adapters re-inject.
                if receipt.applied and not any(
                    r.hook.layer_index == receipt.hook.layer_index and r.mode == receipt.mode and r.applied
                    for r in receipts
                ):
                    receipts.append(receipt)

        streaming_degraded = bool(available and not streaming_forward)
        detail = (
            f"orchestrated {len(plans)} plan(s); applied="
            f"{sum(1 for r in receipts if r.applied)}; available={available}; "
            f"alpha_used={alpha_used}/{self.max_total_alpha}"
        )
        report = ResidualOrchestrationReport(
            enabled=True,
            residual_available=available,
            plans=plans,
            receipts=tuple(receipts),
            forward=forward,
            selected_layers=tuple(p.hook.layer_index for p in plans),
            detail=detail,
            telemetry=dict(self.telemetry),
            alpha_budget=self.max_total_alpha,
            alpha_used=alpha_used,
            streaming_degraded=streaming_degraded,
        )
        self._emit("residual_orchestrate", report.public_dict())
        return report
