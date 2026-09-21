
"""Explainable learning from ContentDNA + metrics — no overconfident tiny samples."""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any


def confidence_for_sample(n: int) -> str:
    if n < 10:
        return "low"
    if n < 30:
        return "moderate"
    return "high"


class LearningEngine:
    def __init__(self, store: Any) -> None:
        self.store = store

    def analyze_hook_performance(
        self,
        *,
        channel_id: str | None,
        rows: list[dict[str, Any]],
        platform: str = "",
        min_samples: int = 10,
    ) -> dict[str, Any] | None:
        """rows: [{hook_type, metric_value, platform, format}]"""
        by_hook: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if platform and row.get("platform") and row.get("platform") != platform:
                continue
            value = row.get("metric_value")
            hook = row.get("hook_type")
            if value is None or not hook:
                continue
            by_hook[str(hook)].append(float(value))
        if len(by_hook) < 2:
            return None
        ranked = sorted(((k, median(v), len(v)) for k, v in by_hook.items() if v), key=lambda x: x[1], reverse=True)
        if not ranked:
            return None
        best, best_med, best_n = ranked[0]
        worst, worst_med, worst_n = ranked[-1]
        sample = best_n + worst_n
        if sample < min_samples:
            conf = "low"
        else:
            conf = confidence_for_sample(sample)
        effect = best_med - worst_med
        finding = (
            f"{best} hooks show {effect:+.1f} median metric vs {worst} hooks "
            f"(sample={sample}). Correlation ≠ causation."
        )
        recommendation = ""
        if conf in {"moderate", "high"} and effect > 0:
            recommendation = f"Gradually increase exploration of {best} hooks; retain control traffic."
        else:
            recommendation = "Collect more samples before changing policy."
        record = self.store.add_learning_finding(
            {
                "channel_id": channel_id,
                "scope": "PLATFORM" if platform else "CHANNEL",
                "platform": platform,
                "finding": finding,
                "sample_size": sample,
                "effect_size": effect,
                "confidence": conf,
                "recommendation": recommendation,
                "evidence": {"by_hook": {k: {"n": len(v), "median": median(v)} for k, v in by_hook.items()}},
            }
        )
        return record
