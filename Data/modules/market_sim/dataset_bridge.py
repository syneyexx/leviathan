"""Bridge TradingGym trajectories into DatasetService (P1C / G29).

Does not create a parallel dataset runtime — uses DatasetService when bound,
otherwise writes a durable JSONL artifact under the markets/artifacts tree
and returns an honest registration status.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .trajectory import TrajectoryArtifact, write_trajectory_jsonl
from .types import MarketSimError


def export_trajectory_to_dataset(
    artifact: TrajectoryArtifact,
    *,
    artifacts_root: Path,
    dataset_service: Any | None = None,
    dataset_name: str | None = None,
) -> dict[str, Any]:
    """Persist trajectory JSONL and optionally register with DatasetService."""
    root = Path(artifacts_root)
    dest_dir = root / "trajectories" / artifact.run_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{artifact.trajectory_id}.jsonl"
    written = write_trajectory_jsonl(artifact, dest)

    result: dict[str, Any] = {
        "artifact": artifact.public_dict(),
        "export": written,
        "dataset": None,
        "truth": {
            "via_dataset_service": False,
            "kernel_owned_trajectory": True,
        },
    }

    if dataset_service is None:
        result["registration"] = "FILE_ONLY"
        result["note"] = "DatasetService not bound; trajectory JSONL written to artifacts_root"
        return result

    try:
        name = dataset_name or f"trading-trajectory-{artifact.run_id[:8]}"
        ds = dataset_service.create_dataset(
            name=name,
            description=f"TradingGym trajectory for run {artifact.run_id}",
            metadata={
                "kind": "trading_trajectory",
                "run_id": artifact.run_id,
                "trajectory_id": artifact.trajectory_id,
                "trajectory_hash": artifact.trajectory_hash,
                "split_role": artifact.split_role,
                "reward_spec": artifact.reward_spec,
                "source": "market_sim.trajectory",
            },
        )
        # Prefer enqueue_import_local when available so DatasetService owns ingest.
        dataset_id = getattr(ds, "dataset_id", None) or (ds.get("dataset_id") if isinstance(ds, dict) else None)
        job = None
        if hasattr(dataset_service, "enqueue_import_local"):
            job = dataset_service.enqueue_import_local(
                path=str(dest),
                name=name,
                description=f"TradingGym trajectory {artifact.trajectory_id}",
                dataset_id=dataset_id,
                materialize=True,
            )
        result["dataset"] = {
            "dataset_id": dataset_id,
            "job_id": getattr(job, "job_id", None) if job is not None else None,
            "name": name,
        }
        result["truth"]["via_dataset_service"] = True
        result["registration"] = "DATASET_QUEUED" if job is not None else "DATASET_CREATED"
        return result
    except Exception as exc:  # noqa: BLE001
        # Honest partial: file exists; dataset registration failed
        result["registration"] = "FILE_ONLY"
        result["dataset_error"] = str(exc)[:500]
        result["note"] = "trajectory JSONL written; DatasetService registration failed"
        return result


def trajectory_records_for_training(artifact: TrajectoryArtifact) -> list[dict[str, Any]]:
    """Flatten steps into training-oriented records (observation→action pairs)."""
    records: list[dict[str, Any]] = []
    for step in artifact.steps:
        records.append(
            {
                "id": f"{artifact.trajectory_id}:{step.step_index}",
                "text": json.dumps(
                    {
                        "observation": step.observation,
                        "action": step.action,
                        "reward": step.reward,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
                "split": str(artifact.split_role).lower(),
                "metadata": {
                    "run_id": artifact.run_id,
                    "trajectory_id": artifact.trajectory_id,
                    "trajectory_hash": artifact.trajectory_hash,
                    "bar_index": step.bar_index,
                    "done": step.done,
                    "reward_status": (step.reward or {}).get("status"),
                },
            }
        )
    return records
