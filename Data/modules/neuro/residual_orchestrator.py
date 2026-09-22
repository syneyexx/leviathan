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

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "residual_available": self.residual_available,
            "plans": [p.public_dict() for p in self.plans],
            "receipts": [r.public_dict() for r in self.receipts],
            "forward": self.forward.public_dict() if self.forward else None,
            "selected_layers": list(self.selected_layers),
            "detail": self.detail,
            "telemetry": self.telemetry,
            "truth": {
                "neural_signal_is_not_authority": True,
                "residual_injection_is_not_authority": True,
                "unapplied_is_not_success": True,
                "model_output_is_not_evidence": True,
                "discoverable_is_not_authorized": True,
                "unsupported_is_not_failure_of_core": True,
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
        observability: Any | None = None,
    ) -> None:
        self.residual_port = residual_port or UnsupportedResidualRuntime()
        self.enabled = enabled
        self.hook_layers = tuple(int(x) for x in (hook_layers or ()))
        self.default_mode = default_mode if default_mode in VALID_MODES else "ADDITIVE"
        self.max_injects = max(0, min(int(max_injects), 16))
        self.base_scale = max(0.0, float(base_scale))
        self.observability = observability
        self.telemetry: dict[str, Any] = {
            "orchestrations": 0,
            "injects_planned": 0,
            "injects_applied": 0,
            "degraded": 0,
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
        plans: list[ResidualInjectPlan] = []
        for idx, hook in enumerate(layers):
            # Mid layers: ADDITIVE; late layers: GATED when complex.
            layer_mode = inject_mode
            if available and inject_mode != "DISABLED" and idx == len(layers) - 1:
                if (complexity or "").lower() in {"high", "complex", "hard"}:
                    layer_mode = "GATED"
            plans.append(
                ResidualInjectPlan(
                    hook=hook,
                    mode=layer_mode,
                    scale=scale if layer_mode != "DISABLED" else 0.0,
                    source=source,
                    payload_ref=payload_ref,
                    reason=f"orchestrator layer={hook.layer_index} complexity={complexity}",
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
            )
            self._emit("residual_orchestrate", report.public_dict())
            return report

        plans = self.plan_injects(
            complexity=complexity,
            token_budget=token_budget,
            payload_ref=payload_ref,
            mode=mode,
        )
        self.telemetry["injects_planned"] += len(plans)
        requests = [p.to_request(run_id=run_id) for p in plans]
        requests.extend(list(extra_injects)[: max(0, self.max_injects - len(requests))])

        receipts: list[ResidualInjectReceipt] = []
        for req in requests:
            receipt = self.residual_port.inject(req)
            receipts.append(receipt)
            if receipt.applied:
                self.telemetry["injects_applied"] += 1
            if receipt.degraded_to_chat_completions or not receipt.applied:
                self.telemetry["degraded"] += 1

        forward: ResidualForwardResult | None = None
        if run_forward and messages is not None:
            forward = self.residual_port.run_forward(
                ResidualForwardRequest(
                    messages=messages,
                    engage_cortex=engage_cortex,
                    critic_rounds=critic_rounds,
                    inject=tuple(requests),
                    metadata={"orchestrator": True, "complexity": complexity},
                )
            )
            for receipt in forward.receipts:
                # Avoid double-counting injects already applied above when adapters re-inject.
                if receipt.applied and not any(
                    r.hook.layer_index == receipt.hook.layer_index and r.mode == receipt.mode and r.applied
                    for r in receipts
                ):
                    receipts.append(receipt)

        detail = (
            f"orchestrated {len(plans)} plan(s); applied="
            f"{sum(1 for r in receipts if r.applied)}; available={available}"
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
        )
        self._emit("residual_orchestrate", report.public_dict())
        return report
