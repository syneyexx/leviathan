"""Phase 7: offline consolidation of fast/experience memory into slow checkpoints.

Pipeline:

    accepted experiences (+ optional retention set)
            ↓
    dedupe / contradiction resolve
            ↓
    train slow memory offline (base frozen)
            ↓
    evaluate (not loss-only)
            ↓
    promote candidate OR reject and restore previous good

Never promotes solely because training loss decreased.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from neural.checkpoint import NeuralMemoryCheckpointStore
from neural.encoding import SlowMemoryExample
from neural.errors import NeuralError
from neural.experience import NeuralExperience, experience_to_slow_example
from neural.runtime import NeuralModelRuntime
from neural.slow_train import SlowNeuralMemoryTrainer, SlowTrainConfig


class ConsolidationError(NeuralError):
    code = "neural_consolidation_error"


@dataclass(frozen=True)
class ConsolidationGates:
    """Hard evaluation gates for slow-checkpoint promotion."""

    min_train_recall: float = 0.75
    min_eval_recall: float = 0.70
    max_retention_drop: float = 0.25
    require_eval_examples: bool = True
    require_base_unchanged: bool = True
    # Loss may inform diagnostics but must not be the sole promotion criterion.
    max_final_loss: float | None = 0.35

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConsolidationReport:
    promoted: bool
    reason: str
    checkpoint_id: str
    candidate_saved: bool = False
    examples_in: int = 0
    examples_after_dedupe: int = 0
    contradictions_resolved: int = 0
    train_recall: float | None = None
    eval_recall: float | None = None
    retention_before: float | None = None
    retention_after: float | None = None
    final_loss: float | None = None
    base_unchanged: bool = False
    fast_reset: bool = False
    gates: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stable_key(text: str) -> str:
    return hashlib.sha256(str(text or "").strip().lower().encode("utf-8")).hexdigest()


def dedupe_examples(
    examples: Sequence[SlowMemoryExample],
    *,
    priorities: dict[str, float] | None = None,
) -> tuple[list[SlowMemoryExample], int]:
    """Dedupe by normalized key_text; keep highest-priority / first stable winner.

    ``priorities`` maps example_id → score (higher wins). Contradictions (same key,
    different value) count toward the returned contradiction total.
    """
    priorities = priorities or {}
    best: dict[str, SlowMemoryExample] = {}
    best_score: dict[str, float] = {}
    contradictions = 0
    for example in examples:
        key = _stable_key(example.key_text)
        score = float(priorities.get(example.example_id, 0.0))
        if key not in best:
            best[key] = example
            best_score[key] = score
            continue
        existing = best[key]
        if existing.value_text.strip() != example.value_text.strip():
            contradictions += 1
        if score > best_score[key] or (
            score == best_score[key] and example.example_id < existing.example_id
        ):
            best[key] = example
            best_score[key] = score
    # Stable order by key hash for determinism.
    ordered = [best[k] for k in sorted(best.keys())]
    return ordered, contradictions


def examples_from_experiences(experiences: Sequence[NeuralExperience]) -> tuple[list[SlowMemoryExample], dict[str, float]]:
    examples: list[SlowMemoryExample] = []
    priorities: dict[str, float] = {}
    for experience in experiences:
        example = experience_to_slow_example(experience)
        if example is None:
            continue
        examples.append(example)
        priorities[example.example_id] = float(experience.reward.score)
    return examples, priorities


class ConsolidationPipeline:
    """Offline consolidate → evaluate → promote/reject slow memory checkpoint."""

    def __init__(
        self,
        runtime: NeuralModelRuntime,
        store: NeuralMemoryCheckpointStore,
        *,
        gates: ConsolidationGates | None = None,
        train_config: SlowTrainConfig | None = None,
    ) -> None:
        self.runtime = runtime
        self.store = store
        self.gates = gates or ConsolidationGates()
        self.train_config = train_config or SlowTrainConfig(
            learning_rate=0.1,
            max_steps_per_batch=80,
            batch_size=2,
            loss_tolerance=0.06,
            replay_size=2,
            train_fast=False,
        )
        self.trainer = SlowNeuralMemoryTrainer(
            runtime,
            config=self.train_config,
            checkpoint_store=store,
        )

    def run(
        self,
        *,
        checkpoint_id: str,
        experiences: Sequence[NeuralExperience] | None = None,
        examples: Sequence[SlowMemoryExample] | None = None,
        eval_examples: Sequence[SlowMemoryExample] | None = None,
        retention_examples: Sequence[SlowMemoryExample] | None = None,
        reset_fast_on_promote: bool = True,
    ) -> ConsolidationReport:
        if not checkpoint_id:
            raise ConsolidationError("checkpoint_id required")

        raw_examples: list[SlowMemoryExample] = list(examples or [])
        priorities: dict[str, float] = {}
        if experiences:
            exp_examples, exp_priorities = examples_from_experiences(experiences)
            raw_examples.extend(exp_examples)
            priorities.update(exp_priorities)

        examples_in = len(raw_examples)
        deduped, contradictions = dedupe_examples(raw_examples, priorities=priorities)
        if not deduped:
            return ConsolidationReport(
                promoted=False,
                reason="no_eligible_examples",
                checkpoint_id=checkpoint_id,
                examples_in=examples_in,
                examples_after_dedupe=0,
                contradictions_resolved=contradictions,
                gates=self.gates.to_dict(),
            )

        eval_set = list(eval_examples or [])
        if self.gates.require_eval_examples and not eval_set:
            # Deterministic holdout from deduped train set (last 25% or at least 1).
            holdout_n = max(1, len(deduped) // 4)
            eval_set = deduped[-holdout_n:]
            train_set = deduped[:-holdout_n] if len(deduped) > holdout_n else list(deduped)
        else:
            train_set = list(deduped)

        retention_set = list(retention_examples or [])
        retention_before = self.trainer.evaluate_recall(retention_set) if retention_set else None

        # Snapshot pre-consolidation memory for rollback.
        before_state = self.runtime.memory.snapshot()

        train_report = self.trainer.fit(
            train_set,
            eval_examples=eval_set,
            checkpoint_id=None,  # evaluate before publishing candidate
        )

        train_recall = train_report.train_recall
        eval_recall = self.trainer.evaluate_recall(eval_set) if eval_set else train_report.eval_recall
        retention_after = self.trainer.evaluate_recall(retention_set) if retention_set else None
        final_loss = train_report.final_loss
        base_unchanged = bool(train_report.base_unchanged)

        gate_failures: list[str] = []
        if self.gates.require_base_unchanged and not base_unchanged:
            gate_failures.append("base_checksum_changed")
        if train_recall is None or train_recall < self.gates.min_train_recall:
            gate_failures.append("train_recall_below_gate")
        if eval_set and (eval_recall is None or eval_recall < self.gates.min_eval_recall):
            gate_failures.append("eval_recall_below_gate")
        if (
            retention_before is not None
            and retention_after is not None
            and (retention_before - retention_after) > self.gates.max_retention_drop
        ):
            gate_failures.append("retention_drop_exceeded")
        if self.gates.max_final_loss is not None and final_loss is not None and final_loss > self.gates.max_final_loss:
            gate_failures.append("final_loss_above_gate")
        # Explicitly forbid loss-only promotion: require at least one recall gate evidence.
        if train_recall is None and eval_recall is None:
            gate_failures.append("missing_recall_metrics")

        if gate_failures:
            self.runtime.memory.restore(before_state)
            return ConsolidationReport(
                promoted=False,
                reason="evaluation_gates_failed",
                checkpoint_id=checkpoint_id,
                candidate_saved=False,
                examples_in=examples_in,
                examples_after_dedupe=len(deduped),
                contradictions_resolved=contradictions,
                train_recall=train_recall,
                eval_recall=eval_recall,
                retention_before=retention_before,
                retention_after=retention_after,
                final_loss=final_loss,
                base_unchanged=base_unchanged,
                gates=self.gates.to_dict(),
                details={"gate_failures": gate_failures, "train_report": train_report.to_dict()},
            )

        # Passed evaluation → write candidate then promote to good.
        self.store.save(
            self.runtime.memory,
            checkpoint_id=checkpoint_id,
            candidate=True,
            extra_metrics={
                "phase": 7,
                "train_recall": train_recall,
                "eval_recall": eval_recall,
                "retention_before": retention_before,
                "retention_after": retention_after,
                "final_loss": final_loss,
                "promoted_on_loss_only": False,
                "examples_after_dedupe": len(deduped),
                "contradictions_resolved": contradictions,
            },
        )
        self.store.promote_candidate(checkpoint_id)
        fast_reset = False
        if reset_fast_on_promote:
            self.runtime.memory.reset_fast_memory()
            fast_reset = True

        return ConsolidationReport(
            promoted=True,
            reason="promoted_after_evaluation",
            checkpoint_id=checkpoint_id,
            candidate_saved=True,
            examples_in=examples_in,
            examples_after_dedupe=len(deduped),
            contradictions_resolved=contradictions,
            train_recall=train_recall,
            eval_recall=eval_recall,
            retention_before=retention_before,
            retention_after=retention_after,
            final_loss=final_loss,
            base_unchanged=base_unchanged,
            fast_reset=fast_reset,
            gates=self.gates.to_dict(),
            details={"train_report": train_report.to_dict()},
        )

    def reject(self, checkpoint_id: str) -> None:
        self.store.reject_candidate(checkpoint_id)
