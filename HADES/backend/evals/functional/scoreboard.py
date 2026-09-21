"""HADES quality scoreboard — never merge mechanical / model / agent into one vanity %.

A score based on 3 tasks must not look equivalent to one based on 300.
Confidence intervals are reported when sample size permits.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ScoreLayer = Literal["mechanical", "model_quality", "agent_quality"]

CATEGORIES = (
    "intent_nlu",
    "coding",
    "rag_knowledge",
    "tool_use",
    "planning",
    "verification",
    "long_horizon_work",
    "recovery",
)


@dataclass
class CategoryScore:
    category: str
    layer: ScoreLayer
    sample_size: int = 0
    successes: int = 0
    partials: int = 0
    failures: int = 0
    blocked: int = 0
    not_run: int = 0
    # Weighted safety for intent: false_execution heavily penalized
    weighted_score: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float | None:
        judged = self.successes + self.partials + self.failures
        if judged <= 0:
            return None
        return self.successes / judged

    def wilson_interval(self, z: float = 1.96) -> tuple[float, float] | None:
        """Wilson score interval for success rate (honest small-n reporting)."""
        n = self.successes + self.partials + self.failures
        if n <= 0:
            return None
        p = self.successes / n
        denom = 1 + z * z / n
        centre = p + z * z / (2 * n)
        margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
        low = max(0.0, (centre - margin) / denom)
        high = min(1.0, (centre + margin) / denom)
        return round(low, 4), round(high, 4)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["success_rate"] = self.success_rate
        interval = self.wilson_interval()
        payload["wilson_95"] = {"low": interval[0], "high": interval[1]} if interval else None
        payload["honesty"] = (
            "insufficient_sample"
            if (self.successes + self.partials + self.failures) < 10
            else "ok"
        )
        return payload


@dataclass
class QualityScoreboard:
    git_sha: str
    benchmark_version: str
    generated_at: float
    categories: list[CategoryScore] = field(default_factory=list)
    model_label: str | None = None
    overall_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        by_layer: dict[str, list[dict[str, Any]]] = {
            "mechanical": [],
            "model_quality": [],
            "agent_quality": [],
        }
        for cat in self.categories:
            by_layer[cat.layer].append(cat.to_dict())
        return {
            "git_sha": self.git_sha,
            "benchmark_version": self.benchmark_version,
            "generated_at": self.generated_at,
            "model_label": self.model_label,
            "layers": by_layer,
            "overall_notes": self.overall_notes
            + [
                "Do not collapse layers into a single HADES intelligence percentage.",
                "Sample sizes and Wilson intervals are part of the score.",
            ],
        }


def build_scoreboard(
    records: list[dict[str, Any]],
    *,
    git_sha: str,
    benchmark_version: str,
    generated_at: float,
    model_label: str | None = None,
) -> QualityScoreboard:
    buckets: dict[tuple[str, ScoreLayer], CategoryScore] = {}

    for rec in records:
        family = str(rec.get("task_family") or "unknown")
        category = _family_to_category(family)
        layer = _layer_from_record(rec)
        key = (category, layer)
        if key not in buckets:
            buckets[key] = CategoryScore(category=category, layer=layer)
        bucket = buckets[key]
        bucket.sample_size += 1
        outcome = str(rec.get("outcome") or "not_run")
        if outcome == "success" or rec.get("success") is True:
            bucket.successes += 1
        elif outcome == "partial" or rec.get("partial") is True:
            bucket.partials += 1
        elif outcome == "blocked":
            bucket.blocked += 1
        elif outcome == "not_run":
            bucket.not_run += 1
        else:
            bucket.failures += 1
        if rec.get("failure_class") == "false_execution":
            bucket.notes.append(f"false_execution:{rec.get('task_id')}")

    # Intent weighted score: false_execution counts as 5 failure equivalents.
    for bucket in buckets.values():
        if bucket.category == "intent_nlu":
            judged = bucket.successes + bucket.partials + bucket.failures
            if judged:
                fe = sum(1 for n in bucket.notes if n.startswith("false_execution:"))
                denom = judged + 4 * fe  # extra weight already in failures; +4 more
                bucket.weighted_score = round(bucket.successes / max(1, denom), 4)

    return QualityScoreboard(
        git_sha=git_sha,
        benchmark_version=benchmark_version,
        generated_at=generated_at,
        categories=sorted(buckets.values(), key=lambda c: (c.layer, c.category)),
        model_label=model_label,
    )


def _family_to_category(family: str) -> str:
    f = family.lower()
    mapping = {
        "intent": "intent_nlu",
        "nlu": "intent_nlu",
        "routing": "intent_nlu",
        "coding": "coding",
        "retrieval": "rag_knowledge",
        "rag": "rag_knowledge",
        "tool": "tool_use",
        "tool_use": "tool_use",
        "planning": "planning",
        "verification": "verification",
        "critic": "verification",
        "work": "long_horizon_work",
        "long_horizon": "long_horizon_work",
        "recovery": "recovery",
        "sandbox": "recovery",
    }
    for key, cat in mapping.items():
        if key in f:
            return cat
    return family if family in CATEGORIES else "intent_nlu"


def _layer_from_record(rec: dict[str, Any]) -> ScoreLayer:
    layer = str(rec.get("eval_layer") or "")
    if layer.startswith("A_") or layer == "infrastructure":
        return "mechanical"
    if layer.startswith("C_") or layer == "real_model":
        # Real model alone is model_quality; agent loops with tools → agent_quality
        family = str(rec.get("task_family") or "")
        if family in {"coding", "tool_use", "work", "long_horizon"}:
            return "agent_quality"
        return "model_quality"
    if layer.startswith("D_"):
        return "agent_quality"
    return "mechanical"
