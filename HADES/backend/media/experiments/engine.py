
"""Experiment engine with minimum sample thresholds."""

from __future__ import annotations

from typing import Any


class ExperimentEngine:
    def __init__(self, store: Any) -> None:
        self.store = store

    def create(
        self,
        *,
        channel_id: str | None,
        name: str,
        hypothesis: str,
        control: dict[str, Any],
        variant: dict[str, Any],
        primary_metric: str,
        min_samples: int = 20,
    ) -> dict[str, Any]:
        return self.store.create_experiment(
            {
                "channel_id": channel_id,
                "name": name,
                "hypothesis": hypothesis,
                "control": control,
                "variant": variant,
                "primary_metric": primary_metric,
                "min_samples": max(5, int(min_samples)),
                "status": "active",
                "results": {"control_n": 0, "variant_n": 0, "winner": None},
            }
        )

    def evaluate(self, experiment: dict[str, Any], *, control_values: list[float], variant_values: list[float]) -> dict[str, Any]:
        min_samples = int(experiment.get("min_samples") or 20)
        control_n = len(control_values)
        variant_n = len(variant_values)
        results = {
            "control_n": control_n,
            "variant_n": variant_n,
            "control_mean": sum(control_values) / control_n if control_n else None,
            "variant_mean": sum(variant_values) / variant_n if variant_n else None,
            "winner": None,
            "premature": False,
        }
        if control_n < min_samples or variant_n < min_samples:
            results["premature"] = True
            results["note"] = "Insufficient samples — no winner declared."
            status = "active"
        else:
            if results["variant_mean"] is not None and results["control_mean"] is not None:
                if results["variant_mean"] > results["control_mean"]:
                    results["winner"] = "variant"
                elif results["variant_mean"] < results["control_mean"]:
                    results["winner"] = "control"
                else:
                    results["winner"] = "tie"
            status = "completed"
        # Persist via store update path (re-create results on experiment row).
        with self.store.connection() as db:
            import json

            db.execute(
                "UPDATE media_experiments SET results_json=?, status=?, updated_at=datetime('now') WHERE id=?",
                (json.dumps(results), status, experiment["id"]),
            )
        updated = self.store.get_experiment(experiment["id"])
        return updated or {**experiment, "results": results, "status": status}
