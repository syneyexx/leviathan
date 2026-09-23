"""Tokenizer packing simulation before training (U272)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .tokenize_stats import estimate_tokens
from .types import CanonicalRecord


@dataclass
class PackingSimulation:
    max_seq_length: int
    record_count: int
    total_tokens: int
    packed_sequences: int
    wasted_tokens: int
    packing_efficiency: float
    average_tokens_per_record: float
    method: str = "greedy_first_fit"

    def public_dict(self) -> dict[str, Any]:
        return {
            "max_seq_length": self.max_seq_length,
            "record_count": self.record_count,
            "total_tokens": self.total_tokens,
            "packed_sequences": self.packed_sequences,
            "wasted_tokens": self.wasted_tokens,
            "packing_efficiency": self.packing_efficiency,
            "average_tokens_per_record": self.average_tokens_per_record,
            "method": self.method,
            "truth": {
                "simulation_is_not_training": True,
                "token_estimates_may_be_heuristic": True,
            },
        }


def simulate_packing(
    records: Iterable[CanonicalRecord],
    *,
    max_seq_length: int = 512,
) -> PackingSimulation:
    if max_seq_length < 8:
        raise ValueError("max_seq_length must be >= 8")
    lengths: list[int] = []
    for rec in records:
        text = rec.text or ""
        if rec.messages:
            text = text + " " + " ".join(
                str(m.get("content") or "") for m in rec.messages if isinstance(m, dict)
            )
        n = min(max_seq_length, max(1, estimate_tokens(text)))
        lengths.append(n)
    # Greedy first-fit packing into sequences of max_seq_length.
    sequences = 0
    remaining = 0
    wasted = 0
    for n in lengths:
        if remaining == 0:
            sequences += 1
            remaining = max_seq_length
        if n > remaining:
            wasted += remaining
            sequences += 1
            remaining = max_seq_length
        remaining -= n
    if lengths:
        wasted += remaining
    total = sum(lengths)
    capacity = sequences * max_seq_length if sequences else 0
    efficiency = (total / capacity) if capacity else 0.0
    return PackingSimulation(
        max_seq_length=max_seq_length,
        record_count=len(lengths),
        total_tokens=total,
        packed_sequences=sequences,
        wasted_tokens=wasted,
        packing_efficiency=round(efficiency, 4),
        average_tokens_per_record=round(total / len(lengths), 2) if lengths else 0.0,
    )
