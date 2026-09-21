"""Training evaluation helpers — measured metrics only."""

from __future__ import annotations

from typing import Any

from .store import TrainingStore
from .types import DurableTrainingJob


def evaluate_job(store: TrainingStore, job: DurableTrainingJob) -> dict[str, Any]:
    """Return evaluation summary from persisted metrics / job evaluation.

    Does not invent improvement claims. Fixture jobs are labeled as such.
    """
    metrics = store.list_metrics(job.job_id, limit=2000)
    eval_points = [m for m in metrics if m.metric_name == "eval_loss"]
    train_points = [m for m in metrics if m.metric_name == "train_loss"]
    summary: dict[str, Any] = {
        "jobId": job.job_id,
        "method": job.method,
        "status": job.status.value,
        "persistedEvaluation": job.evaluation,
        "trainLossLast": train_points[-1].metric_value if train_points else None,
        "evalLossLast": eval_points[-1].metric_value if eval_points else None,
        "metricCount": len(metrics),
        "truth": {
            "no_automatic_better_claim": True,
            "fixture": (job.method or "").lower() == "fixture"
            or bool((job.evaluation or {}).get("fixture")),
        },
    }
    if job.artifact_id:
        artifact = store.get_artifact(job.artifact_id)
        if artifact:
            summary["artifact"] = artifact.public_dict()
    return summary
