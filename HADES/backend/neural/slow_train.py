"""Phase 4: slow neural-memory training from frozen-model encodings.

Trains only memory slow parameters (optionally fast stays frozen/zero).
Never backpropagates into the base Transformer. Default runtime mode remains OFF.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Sequence

from neural.checkpoint import NeuralMemoryCheckpointStore
from neural.contracts import NeuralMode
from neural.deps import require_torch
from neural.encoding import FrozenTextEncoder, SlowMemoryExample
from neural.errors import NeuralError, NeuralNumericalInstability
from neural.runtime import NeuralModelRuntime
from neural.toy_transformer import assert_module_frozen, parameter_checksum


class SlowMemoryTrainError(NeuralError):
    code = "neural_slow_memory_train_error"


@dataclass
class SlowTrainConfig:
    learning_rate: float = 0.05
    max_steps_per_batch: int = 32
    batch_size: int = 4
    loss_tolerance: float = 0.08
    max_grad_norm: float = 1.0
    replay_size: int = 4
    replay_weight: float = 0.5
    replay_buffer_limit: int = 256
    weight_decay: float = 1e-4
    train_fast: bool = False  # Phase 4 focuses on slow memory
    checkpoint_every_batches: int = 0  # 0 = only final candidate


@dataclass
class SlowTrainReport:
    batches: int = 0
    examples_seen: int = 0
    steps: int = 0
    final_loss: float | None = None
    train_recall: float | None = None
    eval_recall: float | None = None
    base_checksum_before: str = ""
    base_checksum_after: str = ""
    base_unchanged: bool = False
    latency_ms: float = 0.0
    candidate_checkpoint_id: str | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batches": self.batches,
            "examples_seen": self.examples_seen,
            "steps": self.steps,
            "final_loss": self.final_loss,
            "train_recall": self.train_recall,
            "eval_recall": self.eval_recall,
            "base_checksum_before": self.base_checksum_before,
            "base_checksum_after": self.base_checksum_after,
            "base_unchanged": self.base_unchanged,
            "latency_ms": self.latency_ms,
            "candidate_checkpoint_id": self.candidate_checkpoint_id,
            "notes": dict(self.notes),
        }


class SlowNeuralMemoryTrainer:
    """Offline trainer: frozen encodings → slow neural memory."""

    def __init__(
        self,
        runtime: NeuralModelRuntime,
        *,
        config: SlowTrainConfig | None = None,
        checkpoint_store: NeuralMemoryCheckpointStore | None = None,
    ) -> None:
        self.runtime = runtime
        self.config = config or SlowTrainConfig()
        self.checkpoint_store = checkpoint_store
        self.encoder = FrozenTextEncoder(runtime)
        self.torch = require_torch()
        assert_module_frozen(runtime.base_model)
        # Keep fusion/runtime out of online LEARN; this trainer is offline-only.
        if runtime.mode is NeuralMode.LEARN:
            raise SlowMemoryTrainError("runtime must not be in LEARN during slow training")
        self._replay_keys: list[Any] = []
        self._replay_values: list[Any] = []

    def _encode_pair(self, example: SlowMemoryExample) -> tuple[Any, Any]:
        key = self.encoder.encode_text(example.key_text)
        value = self.encoder.encode_text(example.value_text)
        return key, value

    def _cosine_loss(self, pred: Any, target: Any) -> Any:
        torch = self.torch
        pred_n = torch.nn.functional.normalize(pred, dim=-1)
        tgt_n = torch.nn.functional.normalize(target, dim=-1)
        return (1.0 - (pred_n * tgt_n).sum(dim=-1)).mean()

    def _train_batch_tensors(self, keys: Any, values: Any) -> tuple[float, int]:
        torch = self.torch
        memory = self.runtime.memory
        slow_params = list(memory.slow.parameters())
        param_groups = [{"params": slow_params, "lr": self.config.learning_rate}]
        if self.config.train_fast:
            param_groups.append({"params": list(memory.fast.parameters()), "lr": self.config.learning_rate})
        else:
            for p in memory.fast.parameters():
                p.requires_grad_(False)

        optimizer = torch.optim.SGD(param_groups, weight_decay=self.config.weight_decay)
        final_loss = float("inf")
        steps = 0
        for step in range(max(1, self.config.max_steps_per_batch)):
            optimizer.zero_grad(set_to_none=True)
            pred = memory.encode(keys)
            if not torch.isfinite(pred).all():
                raise NeuralNumericalInstability("non-finite prediction in slow train")
            loss = self._cosine_loss(pred, values)
            if not torch.isfinite(loss):
                raise NeuralNumericalInstability("non-finite loss in slow train")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(slow_params, self.config.max_grad_norm)
            for p in slow_params:
                if p.grad is not None and not torch.isfinite(p.grad).all():
                    raise NeuralNumericalInstability("non-finite grad in slow train")
            optimizer.step()
            steps = step + 1
            final_loss = float(loss.detach().item())
            if final_loss <= self.config.loss_tolerance:
                break
        # Ensure base still frozen after optimizer step.
        assert_module_frozen(self.runtime.base_model)
        return final_loss, steps

    def _remember(self, keys: Any, values: Any) -> None:
        for i in range(keys.shape[0]):
            self._replay_keys.append(keys[i].detach().clone())
            self._replay_values.append(values[i].detach().clone())
        limit = self.config.replay_buffer_limit
        if len(self._replay_keys) > limit:
            overflow = len(self._replay_keys) - limit
            self._replay_keys = self._replay_keys[overflow:]
            self._replay_values = self._replay_values[overflow:]

    def _with_replay(self, keys: Any, values: Any) -> tuple[Any, Any]:
        torch = self.torch
        if not self._replay_keys or self.config.replay_size <= 0:
            return keys, values
        n = min(self.config.replay_size, len(self._replay_keys))
        # Deterministic tail replay (oldest retained associations) for stability.
        replay_k = torch.stack(self._replay_keys[:n])
        replay_v = torch.stack(self._replay_values[:n])
        return torch.cat([keys, replay_k], dim=0), torch.cat([values, replay_v], dim=0)

    def evaluate_recall(self, examples: Sequence[SlowMemoryExample]) -> float:
        if not examples:
            return 0.0
        torch = self.torch
        memory = self.runtime.memory
        scores: list[float] = []
        with torch.no_grad():
            for example in examples:
                key, value = self._encode_pair(example)
                pred = memory.encode(key.unsqueeze(0)).squeeze(0)
                pred_n = torch.nn.functional.normalize(pred, dim=0)
                val_n = torch.nn.functional.normalize(value, dim=0)
                scores.append(float((pred_n * val_n).sum().item()))
        return sum(scores) / len(scores)

    def fit(
        self,
        examples: Iterable[SlowMemoryExample],
        *,
        eval_examples: Sequence[SlowMemoryExample] | None = None,
        max_examples: int | None = None,
        checkpoint_id: str | None = None,
    ) -> SlowTrainReport:
        started = time.perf_counter()
        before = parameter_checksum(self.runtime.base_model)
        batch: list[SlowMemoryExample] = []
        batches = 0
        examples_seen = 0
        steps_total = 0
        last_loss: float | None = None
        train_held: list[SlowMemoryExample] = []

        def flush() -> None:
            nonlocal batches, steps_total, last_loss
            if not batch:
                return
            keys = self.torch.stack([self._encode_pair(ex)[0] for ex in batch])
            values = self.torch.stack([self._encode_pair(ex)[1] for ex in batch])
            train_keys, train_values = self._with_replay(keys, values)
            last_loss, steps = self._train_batch_tensors(train_keys, train_values)
            steps_total += steps
            self._remember(keys, values)
            train_held.extend(list(batch))
            batches += 1
            batch.clear()
            if (
                self.checkpoint_store is not None
                and self.config.checkpoint_every_batches > 0
                and batches % self.config.checkpoint_every_batches == 0
                and checkpoint_id
            ):
                self.checkpoint_store.save(
                    self.runtime.memory,
                    checkpoint_id=f"{checkpoint_id}_b{batches}",
                    candidate=True,
                    extra_metrics={"phase": 4, "batch": batches, "loss": last_loss},
                )

        for example in examples:
            if example.split == "eval":
                continue
            if not example.key_text or not example.value_text:
                continue
            batch.append(example)
            examples_seen += 1
            if max_examples is not None and examples_seen >= max_examples:
                flush()
                break
            if len(batch) >= self.config.batch_size:
                flush()
        flush()

        after = parameter_checksum(self.runtime.base_model)
        train_recall = self.evaluate_recall(train_held[:64]) if train_held else None
        eval_recall = self.evaluate_recall(list(eval_examples or [])) if eval_examples else None

        candidate_id = None
        if self.checkpoint_store is not None and checkpoint_id:
            self.checkpoint_store.save(
                self.runtime.memory,
                checkpoint_id=checkpoint_id,
                candidate=True,
                extra_metrics={
                    "phase": 4,
                    "train_recall": train_recall,
                    "eval_recall": eval_recall,
                    "final_loss": last_loss,
                    "base_checksum": after,
                    "runtime_fingerprint": self.runtime.compatibility_fingerprint(),
                },
            )
            candidate_id = checkpoint_id

        return SlowTrainReport(
            batches=batches,
            examples_seen=examples_seen,
            steps=steps_total,
            final_loss=last_loss,
            train_recall=train_recall,
            eval_recall=eval_recall,
            base_checksum_before=before,
            base_checksum_after=after,
            base_unchanged=(before == after),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            candidate_checkpoint_id=candidate_id,
            notes={"train_fast": self.config.train_fast, "objective": "cosine_reconstruction"},
        )


def iter_examples_from_jsonl_rows(
    rows: Iterable[tuple[int, dict[str, Any]]],
    *,
    dataset_id: str,
    eval_ratio: float = 0.1,
) -> Iterator[SlowMemoryExample]:
    from neural.encoding import example_from_row

    for row_index, row in rows:
        example = example_from_row(row_index, row, dataset_id=dataset_id, eval_ratio=eval_ratio)
        if example is not None:
            yield example
