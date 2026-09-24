"""Lightweight micro-benchmark for tokenization + context compile paths.

Reports measured timings only - never fabricates speedups.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

from Data.modules.context import ContextBuilder, TokenizationService
from Data.modules.reasoning import ReasoningEngine


def _timed(fn, rounds: int = 20) -> dict[str, Any]:
    samples: list[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return {
        "rounds": rounds,
        "p50_ms": statistics.median(samples),
        "avg_ms": statistics.mean(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
        "truth": {"measured": True, "not_fabricated": True},
    }


def run_inference_efficiency_benchmark(*, rounds: int = 20) -> dict[str, Any]:
    svc = TokenizationService()
    text = "Benchmark tokenization " * 40
    cold = _timed(
        lambda: svc.count_text(text + str(time.time()), tokenizer_id="fixture:whitespace_v1"),
        rounds=5,
    )
    # Warm cache path
    svc.count_text(text, tokenizer_id="fixture:whitespace_v1")
    warm = _timed(
        lambda: svc.count_text(text, tokenizer_id="fixture:whitespace_v1"),
        rounds=rounds,
    )
    plan = ReasoningEngine().analyze("benchmark", has_knowledge=False)
    builder = ContextBuilder(tokenization=svc, model_id="fixture:demo")
    compile_stats = _timed(
        lambda: builder.build(
            history=[{"role": "user", "content": "benchmark turn"}],
            knowledge=[],
            plan=plan,
            behavior_profile_prompt="You are LEVIATHAN",
        ),
        rounds=max(5, rounds // 2),
    )
    return {
        "tokenization_cold_ms": cold,
        "tokenization_warm_cache_ms": warm,
        "context_compile_ms": compile_stats,
        "cache_snapshot": svc.cache_snapshot(),
        "truth": {
            "capability_gated_native_prefix_not_benchmarked_without_runtime": True,
            "measured_only": True,
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_inference_efficiency_benchmark(), indent=2))
