"""Parametric associative neural memory (Phase 1).

Trainable MLP memory with separate slow (persistent) and fast (resettable)
parameter groups. Not a nearest-neighbor store — parameters are updated by
gradient descent under explicit safety bounds.
"""

from __future__ import annotations

import copy
import time
from typing import Any, Mapping, Sequence

from neural.config import NeuralMemoryConfig
from neural.contracts import (
    NeuralMemoryMetrics,
    NeuralMode,
    ReadResult,
    WriteResult,
)
from neural.deps import require_torch
from neural.errors import (
    NeuralMemoryUpdateRejected,
    NeuralModeUnsupported,
    NeuralNumericalInstability,
)


def _build_mlp(torch: Any, in_dim: int, hidden_dim: int, out_dim: int, depth: int) -> Any:
    layers: list[Any] = []
    width = in_dim
    for _ in range(max(1, depth)):
        layers.append(torch.nn.Linear(width, hidden_dim))
        layers.append(torch.nn.Tanh())
        width = hidden_dim
    layers.append(torch.nn.Linear(width, out_dim))
    return torch.nn.Sequential(*layers)


def _make_modules(config: NeuralMemoryConfig) -> tuple[Any, Any, Any]:
    torch = require_torch()

    class SlowNeuralMemory(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.query_proj = torch.nn.Linear(config.dim, config.hidden_dim, bias=False)
            self.memory = _build_mlp(
                torch, config.hidden_dim, config.hidden_dim, config.hidden_dim, config.slow_depth
            )
            self.out_proj = torch.nn.Linear(config.hidden_dim, config.dim, bias=False)

        def forward(self, x: Any) -> Any:
            q = torch.nn.functional.normalize(self.query_proj(x), dim=-1)
            m = self.memory(q)
            return self.out_proj(m)

    class FastNeuralMemory(torch.nn.Module):
        """High-plasticity residual memory; independently resettable."""

        def __init__(self) -> None:
            super().__init__()
            self.net = _build_mlp(
                torch, config.dim, config.fast_hidden_dim, config.dim, config.fast_depth
            )
            # Near-zero init so fast path starts with minimal effect.
            for module in self.net.modules():
                if isinstance(module, torch.nn.Linear):
                    torch.nn.init.zeros_(module.weight)
                    if module.bias is not None:
                        torch.nn.init.zeros_(module.bias)

        def forward(self, x: Any) -> Any:
            return self.net(x)

        def reset(self) -> None:
            for module in self.net.modules():
                if isinstance(module, torch.nn.Linear):
                    torch.nn.init.zeros_(module.weight)
                    if module.bias is not None:
                        torch.nn.init.zeros_(module.bias)

    slow = SlowNeuralMemory()
    fast = FastNeuralMemory()
    return torch, slow, fast


class NeuralMemory:
    """Vector-level neural memory with safe writes and checkpointable state."""

    def __init__(self, config: NeuralMemoryConfig | None = None) -> None:
        self.config = config or NeuralMemoryConfig()
        torch = require_torch()
        # Seed before module construction so weight init is reproducible.
        torch.manual_seed(int(self.config.seed))
        _, slow, fast = _make_modules(self.config)
        self._torch = torch
        device = torch.device(self.config.device)
        self.device = device
        self.slow = slow.to(device)
        self.fast = fast.to(device)
        self._generator = torch.Generator(device="cpu")
        self._generator.manual_seed(int(self.config.seed))
        self._association_count = 0
        self._write_count = 0
        self._read_count = 0
        self._rollback_count = 0
        self._last_write_loss: float | None = None
        self._last_write_latency_ms: float | None = None
        self._last_read_latency_ms: float | None = None
        self._last_delta_norm: float | None = None
        self._replay_keys: list[Any] = []
        self._replay_values: list[Any] = []
        self._replay_ids: list[str] = []

    @property
    def mode(self) -> NeuralMode:
        return self.config.mode

    def set_mode(self, mode: NeuralMode) -> None:
        payload = self.config.to_dict()
        payload["mode"] = mode
        self.config = NeuralMemoryConfig.from_dict(payload)

    def parameters(self) -> list[Any]:
        return list(self.slow.parameters()) + list(self.fast.parameters())

    def trainable_parameter_count(self) -> int:
        return sum(int(p.numel()) for p in self.parameters())

    def _as_batch(self, tensor: Any) -> Any:
        torch = self._torch
        if not isinstance(tensor, torch.Tensor):
            tensor = torch.as_tensor(tensor, dtype=torch.float32)
        tensor = tensor.to(self.device, dtype=torch.float32)
        if tensor.ndim == 1:
            tensor = tensor.unsqueeze(0)
        if tensor.shape[-1] != self.config.dim:
            raise ValueError(f"expected last dim {self.config.dim}, got {tuple(tensor.shape)}")
        return tensor

    def _forward(self, keys: Any) -> Any:
        return self.slow(keys) + self.fast(keys)

    def encode(self, query: Any) -> Any:
        """Parametric memory forward without mode gating.

        Runtime/fusion owns OFF/SHADOW/READ. This path must remain callable so
        SHADOW can compute diagnostics while leaving generation unchanged.
        """
        q = self._as_batch(query)
        out = self._forward(q)
        if not self._finite(out):
            raise NeuralNumericalInstability("non-finite memory encode output")
        return out

    def _finite(self, tensor: Any) -> bool:
        return bool(self._torch.isfinite(tensor).all().item())

    def _state_clone(self) -> dict[str, Any]:
        return {
            "slow": copy.deepcopy(self.slow.state_dict()),
            "fast": copy.deepcopy(self.fast.state_dict()),
            "association_count": self._association_count,
            "write_count": self._write_count,
            "read_count": self._read_count,
            "rollback_count": self._rollback_count,
            "last_write_loss": self._last_write_loss,
            "last_delta_norm": self._last_delta_norm,
            "replay_keys": [t.detach().cpu().clone() for t in self._replay_keys],
            "replay_values": [t.detach().cpu().clone() for t in self._replay_values],
            "replay_ids": list(self._replay_ids),
        }

    def _load_state_clone(self, state: Mapping[str, Any]) -> None:
        self.slow.load_state_dict(state["slow"])
        self.fast.load_state_dict(state["fast"])
        self._association_count = int(state.get("association_count", 0))
        self._write_count = int(state.get("write_count", 0))
        self._read_count = int(state.get("read_count", 0))
        self._rollback_count = int(state.get("rollback_count", 0))
        self._last_write_loss = state.get("last_write_loss")
        self._last_delta_norm = state.get("last_delta_norm")
        self._replay_keys = [t.to(self.device) for t in state.get("replay_keys", [])]
        self._replay_values = [t.to(self.device) for t in state.get("replay_values", [])]
        self._replay_ids = list(state.get("replay_ids", []))

    def snapshot(self) -> dict[str, Any]:
        return self._state_clone()

    def restore(self, state: Mapping[str, Any]) -> None:
        self._load_state_clone(state)

    def reset_fast_memory(self) -> None:
        self.fast.reset()

    def consolidate(self, **kwargs: Any) -> dict[str, Any]:
        """Phase 1 stub: copy fast residual into slow via one supervised step batch.

        Full consolidation (dedupe/eval/promote) belongs to later phases.
        """
        if not self._replay_keys:
            return {"consolidated": False, "reason": "empty_replay"}
        # Merge by training slow on replay while zeroing fast afterward.
        keys = self._torch.stack(self._replay_keys)
        values = self._torch.stack(self._replay_values)
        before = self._state_clone()
        try:
            # Temporarily disable fast contribution by zeroing it during consolidate.
            self.fast.reset()
            result = self._train_batch(keys, values, steps=int(kwargs.get("steps", 16)))
            if not result.accepted:
                self._load_state_clone(before)
                return {"consolidated": False, "reason": result.reason}
            self.fast.reset()
            return {"consolidated": True, "final_loss": result.final_loss, "steps": result.steps}
        except Exception as exc:  # noqa: BLE001 — roll back and report
            self._load_state_clone(before)
            return {"consolidated": False, "reason": str(exc)}

    def metrics(self) -> NeuralMemoryMetrics:
        slow_n = sum(int(p.numel()) for p in self.slow.parameters())
        fast_n = sum(int(p.numel()) for p in self.fast.parameters())
        return NeuralMemoryMetrics(
            association_count=self._association_count,
            write_count=self._write_count,
            read_count=self._read_count,
            rollback_count=self._rollback_count,
            last_write_loss=self._last_write_loss,
            last_write_latency_ms=self._last_write_latency_ms,
            last_read_latency_ms=self._last_read_latency_ms,
            parameter_count=slow_n + fast_n,
            parameter_delta_norm=self._last_delta_norm,
            fast_parameter_count=fast_n,
            slow_parameter_count=slow_n,
        )

    def read(self, query: Any) -> ReadResult:
        mode = self.config.mode
        if mode is NeuralMode.OFF:
            # Complete bypass — no forward, no side effects.
            return ReadResult(value=None, latency_ms=0.0, mode=mode, diagnostics={"bypassed": True})

        started = time.perf_counter()
        with self._torch.no_grad():
            q = self._as_batch(query)
            out = self._forward(q)
            if not self._finite(out):
                raise NeuralNumericalInstability("non-finite memory read output")
            value = out.squeeze(0).detach().cpu().clone() if out.shape[0] == 1 else out.detach().cpu().clone()
        latency = (time.perf_counter() - started) * 1000.0
        self._read_count += 1
        self._last_read_latency_ms = latency
        diagnostics: dict[str, Any] = {"output_norm": float(value.norm().item()) if value.ndim else None}
        if mode is NeuralMode.SHADOW:
            diagnostics["shadow"] = True
            # SHADOW must not influence callers that treat value as generation input;
            # return the vector for measurement only — fusion layers later must ignore it.
        return ReadResult(value=value, latency_ms=latency, mode=mode, diagnostics=diagnostics)

    def write(self, key: Any, value: Any, *, sample_id: str = "") -> WriteResult:
        mode = self.config.mode
        if mode is NeuralMode.OFF:
            return WriteResult(accepted=False, reason="mode_off", latency_ms=0.0)
        if mode is NeuralMode.SHADOW:
            return WriteResult(accepted=False, reason="mode_shadow_no_writes", latency_ms=0.0)
        if mode is NeuralMode.READ:
            return WriteResult(accepted=False, reason="mode_read_no_writes", latency_ms=0.0)
        if mode is not NeuralMode.LEARN:
            raise NeuralModeUnsupported(f"unsupported mode for write: {mode}")

        started = time.perf_counter()
        key_t = self._as_batch(key)
        value_t = self._as_batch(value)
        if not self._finite(key_t) or not self._finite(value_t):
            raise NeuralNumericalInstability("non-finite write key/value")

        before = self._state_clone()
        before_params = [p.detach().cpu().clone() for p in self.parameters()]

        keys = key_t
        values = value_t
        replay_n = 0
        if self.config.replay_enabled and self._replay_keys and self.config.replay_batch_size > 0:
            replay_n = min(self.config.replay_batch_size, len(self._replay_keys))
            # Deterministic sample from buffer using seeded generator.
            idx = self._torch.randperm(len(self._replay_keys), generator=self._generator)[:replay_n]
            replay_keys = self._torch.stack([self._replay_keys[int(i)] for i in idx])
            replay_values = self._torch.stack([self._replay_values[int(i)] for i in idx])
            keys = self._torch.cat([keys, replay_keys], dim=0)
            values = self._torch.cat([values, replay_values], dim=0)

        try:
            result = self._train_batch(keys, values, steps=self.config.max_update_steps)
            delta = self._parameter_delta_norm(before_params)
            result.parameter_delta_norm = delta
            result.replay_count = replay_n
            if not result.accepted:
                self._load_state_clone(before)
                self._rollback_count += 1
                result.rolled_back = True
                latency = (time.perf_counter() - started) * 1000.0
                result.latency_ms = latency
                self._last_write_latency_ms = latency
                return result
            if delta is not None and delta > self.config.max_parameter_delta_norm:
                self._load_state_clone(before)
                self._rollback_count += 1
                latency = (time.perf_counter() - started) * 1000.0
                return WriteResult(
                    accepted=False,
                    steps=result.steps,
                    final_loss=result.final_loss,
                    parameter_delta_norm=delta,
                    latency_ms=latency,
                    rolled_back=True,
                    reason="parameter_delta_exceeded",
                    replay_count=replay_n,
                )
            self._remember(key_t.squeeze(0), value_t.squeeze(0), sample_id=sample_id)
            self._association_count += 1
            self._write_count += 1
            self._last_write_loss = result.final_loss
            self._last_delta_norm = delta
            latency = (time.perf_counter() - started) * 1000.0
            self._last_write_latency_ms = latency
            result.latency_ms = latency
            return result
        except (NeuralNumericalInstability, NeuralMemoryUpdateRejected) as exc:
            self._load_state_clone(before)
            self._rollback_count += 1
            latency = (time.perf_counter() - started) * 1000.0
            self._last_write_latency_ms = latency
            return WriteResult(
                accepted=False,
                latency_ms=latency,
                rolled_back=True,
                reason=f"update_rejected:{exc}",
            )
        except Exception as exc:  # noqa: BLE001 — never leave memory half-updated
            self._load_state_clone(before)
            self._rollback_count += 1
            latency = (time.perf_counter() - started) * 1000.0
            self._last_write_latency_ms = latency
            return WriteResult(
                accepted=False,
                latency_ms=latency,
                rolled_back=True,
                reason=f"update_failed:{exc}",
            )

    def _remember(self, key: Any, value: Any, *, sample_id: str) -> None:
        self._replay_keys.append(key.detach().clone())
        self._replay_values.append(value.detach().clone())
        self._replay_ids.append(sample_id or f"assoc_{self._association_count}")
        limit = self.config.replay_buffer_limit
        if len(self._replay_keys) > limit:
            overflow = len(self._replay_keys) - limit
            self._replay_keys = self._replay_keys[overflow:]
            self._replay_values = self._replay_values[overflow:]
            self._replay_ids = self._replay_ids[overflow:]

    def _parameter_delta_norm(self, before: Sequence[Any]) -> float:
        total = 0.0
        for prev, cur in zip(before, self.parameters(), strict=True):
            diff = (cur.detach().cpu() - prev).float()
            total += float(diff.pow(2).sum().item())
        return total ** 0.5

    def _association_loss(self, pred: Any, target: Any, *, new_count: int) -> Any:
        torch = self._torch
        # Cosine reconstruction: 1 - cosine similarity, averaged.
        pred_n = torch.nn.functional.normalize(pred, dim=-1)
        tgt_n = torch.nn.functional.normalize(target, dim=-1)
        cos = (pred_n * tgt_n).sum(dim=-1)
        per = 1.0 - cos
        if new_count >= pred.shape[0] or self.config.replay_loss_weight <= 0:
            return per.mean()
        new_part = per[:new_count].mean()
        replay_part = per[new_count:].mean()
        return new_part + self.config.replay_loss_weight * replay_part

    def _train_batch(self, keys: Any, values: Any, *, steps: int) -> WriteResult:
        torch = self._torch
        lr = min(self.config.learning_rate, self.config.max_learning_rate)
        # Prefer fast parameters for online writes; always include slow at lower rate.
        slow_params = list(self.slow.parameters())
        fast_params = list(self.fast.parameters())
        optimizer = torch.optim.SGD(
            [
                {"params": slow_params, "lr": lr * 0.25},
                {"params": fast_params, "lr": lr},
            ],
            weight_decay=self.config.weight_decay,
        )
        new_count = 1 if keys.shape[0] == 1 else max(1, keys.shape[0] - min(self.config.replay_batch_size, max(0, keys.shape[0] - 1)))
        # When batch is exactly the new sample(+replay), first row(s) are new.
        if keys.shape[0] > 1 and self.config.replay_enabled:
            new_count = 1
        else:
            new_count = keys.shape[0]

        final_loss: float | None = None
        steps_run = 0
        max_steps = max(self.config.min_update_steps, min(steps, self.config.max_update_steps))
        for step in range(max_steps):
            optimizer.zero_grad(set_to_none=True)
            pred = self._forward(keys)
            if not self._finite(pred):
                raise NeuralNumericalInstability("non-finite prediction during write")
            loss = self._association_loss(pred, values, new_count=new_count)
            if not self._finite(loss):
                raise NeuralNumericalInstability("non-finite loss during write")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.parameters(), self.config.max_grad_norm)
            for p in self.parameters():
                if p.grad is not None and not self._finite(p.grad):
                    raise NeuralNumericalInstability("non-finite gradient during write")
            optimizer.step()
            steps_run = step + 1
            final_loss = float(loss.detach().item())
            if final_loss <= self.config.loss_tolerance:
                break

        accepted = final_loss is not None and final_loss <= max(self.config.loss_tolerance * 4.0, 0.35)
        reason = None if accepted else "loss_not_converged"
        if not accepted:
            return WriteResult(
                accepted=False,
                steps=steps_run,
                final_loss=final_loss,
                reason=reason,
            )
        return WriteResult(accepted=True, steps=steps_run, final_loss=final_loss, reason=None)

    def cosine_similarity(self, a: Any, b: Any) -> float:
        torch = self._torch
        a_t = self._as_batch(a)
        b_t = self._as_batch(b)
        a_n = torch.nn.functional.normalize(a_t, dim=-1)
        b_n = torch.nn.functional.normalize(b_t, dim=-1)
        return float((a_n * b_n).sum(dim=-1).mean().item())
