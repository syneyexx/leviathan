"""Phase 5: bounded fast neural-memory writes (test-time / session scope).

Design constraints:
- Update **fast** parameters only; slow memory and base model stay frozen.
- Conservative write policy: prefer false negatives over poisoning.
- Writes require an explicit verification signal by default.
- Surprise is a measurable reconstruction mismatch, not a magic score.
- Not wired into ModelGateway; NeuralModelRuntime LEARN remains rejected.
"""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from neural.contracts import WriteResult
from neural.deps import require_torch
from neural.errors import NeuralError, NeuralMemoryUpdateRejected, NeuralNumericalInstability
from neural.memory import NeuralMemory


class FastMemoryError(NeuralError):
    code = "neural_fast_memory_error"


@dataclass(frozen=True)
class FastWritePolicy:
    """Conservative gates for session-scoped fast writes."""

    require_verified: bool = True
    min_surprise: float = 0.25
    max_surprise: float = 1.5  # reject pathological inputs
    min_source_reliability: float = 0.5
    max_writes_per_session: int = 32
    max_update_steps: int = 16
    learning_rate: float = 0.05
    max_learning_rate: float = 0.2
    max_grad_norm: float = 1.0
    max_parameter_delta_norm: float = 10.0
    loss_tolerance: float = 0.1
    weight_decay: float = 1e-4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SurpriseReport:
    """HADES surprise = reconstruction mismatch under current memory.

    surprise = 1 - cosine(memory.encode(key), value) for L2-normalized vectors.
    Range is typically ``[0, 2]``; identical vectors → 0.
    """

    surprise: float
    cosine: float
    key_norm: float
    value_norm: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FastWriteDecision:
    allow: bool
    reason: str
    surprise: SurpriseReport | None = None
    verified: bool = False
    source_reliability: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "allow": self.allow,
            "reason": self.reason,
            "verified": self.verified,
            "source_reliability": self.source_reliability,
            "details": dict(self.details),
            "surprise": self.surprise.to_dict() if self.surprise else None,
        }
        return payload


@dataclass
class FastWriteResult:
    decision: FastWriteDecision
    write: WriteResult | None = None

    @property
    def accepted(self) -> bool:
        return bool(self.write and self.write.accepted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "decision": self.decision.to_dict(),
            "write": None
            if self.write is None
            else {
                "accepted": self.write.accepted,
                "steps": self.write.steps,
                "final_loss": self.write.final_loss,
                "parameter_delta_norm": self.write.parameter_delta_norm,
                "latency_ms": self.write.latency_ms,
                "rolled_back": self.write.rolled_back,
                "reason": self.write.reason,
            },
        }


class FastMemorySession:
    """Session-scoped controller for bounded fast-memory plasticity."""

    def __init__(
        self,
        memory: NeuralMemory,
        *,
        policy: FastWritePolicy | None = None,
    ) -> None:
        self.memory = memory
        self.policy = policy or FastWritePolicy()
        if self.policy.learning_rate <= 0 or self.policy.learning_rate > self.policy.max_learning_rate:
            raise FastMemoryError("learning_rate out of bounds", detail=self.policy.to_dict())
        self.torch = require_torch()
        self.writes_accepted = 0
        self.writes_rejected = 0
        self.rollbacks = 0
        self._slow_snapshot = {k: v.detach().cpu().clone() for k, v in memory.slow.state_dict().items()}

    def reset_session_counters(self) -> None:
        self.writes_accepted = 0
        self.writes_rejected = 0
        self.rollbacks = 0

    def reset_fast_memory(self) -> None:
        self.memory.reset_fast_memory()

    def measure_surprise(self, key: Any, value: Any) -> SurpriseReport:
        torch = self.torch
        key_t = self.memory._as_batch(key)
        value_t = self.memory._as_batch(value)
        with torch.no_grad():
            pred = self.memory.encode(key_t)
            pred_n = torch.nn.functional.normalize(pred, dim=-1)
            val_n = torch.nn.functional.normalize(value_t, dim=-1)
            cosine = float((pred_n * val_n).sum(dim=-1).mean().item())
            surprise = float(1.0 - cosine)
        return SurpriseReport(
            surprise=surprise,
            cosine=cosine,
            key_norm=float(key_t.norm(dim=-1).mean().item()),
            value_norm=float(value_t.norm(dim=-1).mean().item()),
        )

    def decide(
        self,
        key: Any,
        value: Any,
        *,
        verified: bool,
        source_reliability: float = 0.0,
    ) -> FastWriteDecision:
        if self.policy.require_verified and not verified:
            self.writes_rejected += 1
            return FastWriteDecision(
                allow=False,
                reason="unverified_experience",
                verified=verified,
                source_reliability=source_reliability,
            )
        if source_reliability < self.policy.min_source_reliability:
            self.writes_rejected += 1
            return FastWriteDecision(
                allow=False,
                reason="source_reliability_too_low",
                verified=verified,
                source_reliability=source_reliability,
                details={"min_required": self.policy.min_source_reliability},
            )
        if self.writes_accepted >= self.policy.max_writes_per_session:
            self.writes_rejected += 1
            return FastWriteDecision(
                allow=False,
                reason="session_write_budget_exhausted",
                verified=verified,
                source_reliability=source_reliability,
                details={"max_writes_per_session": self.policy.max_writes_per_session},
            )
        surprise = self.measure_surprise(key, value)
        if surprise.surprise < self.policy.min_surprise:
            self.writes_rejected += 1
            return FastWriteDecision(
                allow=False,
                reason="surprise_too_low",
                surprise=surprise,
                verified=verified,
                source_reliability=source_reliability,
                details={"min_surprise": self.policy.min_surprise},
            )
        if surprise.surprise > self.policy.max_surprise:
            self.writes_rejected += 1
            return FastWriteDecision(
                allow=False,
                reason="surprise_pathological",
                surprise=surprise,
                verified=verified,
                source_reliability=source_reliability,
                details={"max_surprise": self.policy.max_surprise},
            )
        return FastWriteDecision(
            allow=True,
            reason="accepted_by_policy",
            surprise=surprise,
            verified=verified,
            source_reliability=source_reliability,
        )

    def _assert_slow_unchanged(self, before: dict[str, Any]) -> None:
        for key, tensor in self.memory.slow.state_dict().items():
            if not self.torch.equal(before[key], tensor.detach().cpu()):
                raise NeuralMemoryUpdateRejected(
                    "slow memory changed during fast write — rolled back",
                    detail={"param": key},
                )

    def _fast_train(self, key: Any, value: Any) -> WriteResult:
        torch = self.torch
        key_t = self.memory._as_batch(key)
        value_t = self.memory._as_batch(value)
        if not self.memory._finite(key_t) or not self.memory._finite(value_t):
            raise NeuralNumericalInstability("non-finite fast-write key/value")

        slow_before = {k: v.detach().cpu().clone() for k, v in self.memory.slow.state_dict().items()}
        fast_before = copy.deepcopy(self.memory.fast.state_dict())
        # Freeze slow for this update.
        for p in self.memory.slow.parameters():
            p.requires_grad_(False)
        fast_params = list(self.memory.fast.parameters())
        for p in fast_params:
            p.requires_grad_(True)

        optimizer = torch.optim.SGD(
            fast_params,
            lr=min(self.policy.learning_rate, self.policy.max_learning_rate),
            weight_decay=self.policy.weight_decay,
        )
        before_fast = [p.detach().cpu().clone() for p in fast_params]
        final_loss: float | None = None
        steps = 0
        started = time.perf_counter()
        try:
            for step in range(max(1, self.policy.max_update_steps)):
                optimizer.zero_grad(set_to_none=True)
                pred = self.memory.encode(key_t)
                if not torch.isfinite(pred).all():
                    raise NeuralNumericalInstability("non-finite fast-write prediction")
                pred_n = torch.nn.functional.normalize(pred, dim=-1)
                val_n = torch.nn.functional.normalize(value_t, dim=-1)
                loss = (1.0 - (pred_n * val_n).sum(dim=-1)).mean()
                if not torch.isfinite(loss):
                    raise NeuralNumericalInstability("non-finite fast-write loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(fast_params, self.policy.max_grad_norm)
                for p in fast_params:
                    if p.grad is not None and not torch.isfinite(p.grad).all():
                        raise NeuralNumericalInstability("non-finite fast-write grad")
                optimizer.step()
                self._assert_slow_unchanged(slow_before)
                steps = step + 1
                final_loss = float(loss.detach().item())
                if final_loss <= self.policy.loss_tolerance:
                    break

            delta = 0.0
            for prev, cur in zip(before_fast, fast_params, strict=True):
                diff = (cur.detach().cpu() - prev).float()
                delta += float(diff.pow(2).sum().item())
            delta = delta ** 0.5
            if delta > self.policy.max_parameter_delta_norm:
                self.memory.fast.load_state_dict(fast_before)
                self.rollbacks += 1
                return WriteResult(
                    accepted=False,
                    steps=steps,
                    final_loss=final_loss,
                    parameter_delta_norm=delta,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    rolled_back=True,
                    reason="fast_parameter_delta_exceeded",
                )
            accepted = final_loss is not None and final_loss <= max(self.policy.loss_tolerance * 4.0, 0.4)
            if not accepted:
                self.memory.fast.load_state_dict(fast_before)
                self.rollbacks += 1
                return WriteResult(
                    accepted=False,
                    steps=steps,
                    final_loss=final_loss,
                    parameter_delta_norm=delta,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    rolled_back=True,
                    reason="fast_loss_not_converged",
                )
            return WriteResult(
                accepted=True,
                steps=steps,
                final_loss=final_loss,
                parameter_delta_norm=delta,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                rolled_back=False,
                reason=None,
            )
        except Exception:
            self.memory.fast.load_state_dict(fast_before)
            self.rollbacks += 1
            raise
        finally:
            # Leave slow frozen; fast remains trainable for subsequent session writes.
            for p in self.memory.slow.parameters():
                p.requires_grad_(False)

    def consider_write(
        self,
        key: Any,
        value: Any,
        *,
        verified: bool,
        source_reliability: float = 1.0,
        sample_id: str = "",
    ) -> FastWriteResult:
        decision = self.decide(
            key,
            value,
            verified=verified,
            source_reliability=source_reliability,
        )
        if not decision.allow:
            return FastWriteResult(decision=decision, write=None)
        try:
            write = self._fast_train(key, value)
        except (NeuralNumericalInstability, NeuralMemoryUpdateRejected) as exc:
            self.writes_rejected += 1
            return FastWriteResult(
                decision=FastWriteDecision(
                    allow=False,
                    reason=f"write_rejected:{exc}",
                    surprise=decision.surprise,
                    verified=verified,
                    source_reliability=source_reliability,
                    details={"sample_id": sample_id},
                ),
                write=WriteResult(accepted=False, rolled_back=True, reason=str(exc)),
            )
        if write.accepted:
            self.writes_accepted += 1
            # Keep session slow snapshot in sync (still unchanged).
            self._slow_snapshot = {
                k: v.detach().cpu().clone() for k, v in self.memory.slow.state_dict().items()
            }
        else:
            self.writes_rejected += 1
        return FastWriteResult(decision=decision, write=write)

    def metrics(self) -> dict[str, Any]:
        return {
            "writes_accepted": self.writes_accepted,
            "writes_rejected": self.writes_rejected,
            "rollbacks": self.rollbacks,
            "policy": self.policy.to_dict(),
        }
