"""Deterministic evaluation helpers for Phase 1 neural memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from neural.contracts import NeuralMode
from neural.deps import require_torch
from neural.memory import NeuralMemory


@dataclass
class PairScore:
    sample_id: str
    cosine: float


@dataclass
class EvalReport:
    name: str
    mean_cosine: float
    min_cosine: float
    scores: list[PairScore]
    latency_ms_mean: float
    notes: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


def _unit_pair(torch: Any, dim: int, seed: int, index: int, *, similar: bool = False) -> tuple[Any, Any]:
    g = torch.Generator()
    g.manual_seed(seed + index * 9973)
    key = torch.randn(dim, generator=g)
    if similar:
        # Nearby key for interference tests.
        noise = torch.randn(dim, generator=g) * 0.05
        key = key + noise
    value = torch.randn(dim, generator=g)
    key = torch.nn.functional.normalize(key, dim=0)
    value = torch.nn.functional.normalize(value, dim=0)
    return key, value


def make_association_pairs(
    dim: int,
    count: int,
    *,
    seed: int = 0,
    similar: bool = False,
) -> list[tuple[str, Any, Any]]:
    torch = require_torch()
    pairs: list[tuple[str, Any, Any]] = []
    for i in range(count):
        key, value = _unit_pair(torch, dim, seed, i, similar=similar)
        pairs.append((f"p{i}", key, value))
    return pairs


def evaluate_recall(
    memory: NeuralMemory,
    pairs: Sequence[tuple[str, Any, Any]],
    *,
    name: str = "recall",
) -> EvalReport:
    """Measure cosine(read(key), value) for stored associations."""
    previous = memory.mode
    if previous is NeuralMode.OFF:
        memory.set_mode(NeuralMode.READ)
    scores: list[PairScore] = []
    latencies: list[float] = []
    try:
        for sample_id, key, value in pairs:
            result = memory.read(key)
            if result.value is None:
                scores.append(PairScore(sample_id=sample_id, cosine=-1.0))
            else:
                cos = memory.cosine_similarity(result.value, value)
                scores.append(PairScore(sample_id=sample_id, cosine=cos))
            latencies.append(result.latency_ms)
    finally:
        if previous is NeuralMode.OFF:
            memory.set_mode(NeuralMode.OFF)
    cosines = [s.cosine for s in scores]
    mean = sum(cosines) / max(1, len(cosines))
    return EvalReport(
        name=name,
        mean_cosine=mean,
        min_cosine=min(cosines) if cosines else -1.0,
        scores=scores,
        latency_ms_mean=(sum(latencies) / max(1, len(latencies))),
        notes={"n": len(pairs)},
    )


def train_pairs(
    memory: NeuralMemory,
    pairs: Sequence[tuple[str, Any, Any]],
) -> list[dict[str, Any]]:
    previous = memory.mode
    memory.set_mode(NeuralMode.LEARN)
    results: list[dict[str, Any]] = []
    try:
        for sample_id, key, value in pairs:
            wr = memory.write(key, value, sample_id=sample_id)
            results.append(
                {
                    "sample_id": sample_id,
                    "accepted": wr.accepted,
                    "final_loss": wr.final_loss,
                    "steps": wr.steps,
                    "reason": wr.reason,
                    "rolled_back": wr.rolled_back,
                }
            )
    finally:
        memory.set_mode(previous)
    return results
