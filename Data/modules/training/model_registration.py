"""Register completed training artifacts into the Model Control Plane registry."""

from __future__ import annotations

from typing import Any

from Data.modules.models.store import ModelStore, utc_now

from .store import TrainingStore
from .types import ArtifactRecord


def register_training_artifact_as_model(
    *,
    model_store: ModelStore,
    training_store: TrainingStore,
    artifact: ArtifactRecord,
) -> str:
    """Upsert a trained adapter into model_registry with honest compatibility.

    Returns the registered model_id. Does not claim the artifact is loadable
    by arbitrary providers — metadata.compatibility carries that truth.
    """
    model_id = f"trained:{artifact.artifact_id}"
    now = utc_now()
    if model_store.get_provider("local_trained") is None:
        model_store.upsert_provider(
            {
                "provider_id": "local_trained",
                "name": "Local Trained Artifacts",
                "provider_type": "local_artifact",
                "endpoint": "local://trained",
                "enabled": True,
                "auto_connect": False,
                "timeout_seconds": 1.0,
                "refresh_interval_seconds": 3600.0,
                "health": "unknown",
                "capabilities": {
                    "discoverModels": False,
                    "inference": False,
                    "streaming": False,
                    "note": "Registry only — not an inference endpoint",
                },
                "metadata": {"kind": "trained_artifact_registry"},
            }
        )
    model_store.upsert_model(
        {
            "model_id": model_id,
            "display_name": f"{artifact.method or 'adapter'} · {artifact.base_model_ref or 'base'}",
            "provider_id": "local_trained",
            "runtime_id": None,
            "source": "trained",
            "object_type": "adapter",
            "format": "peft" if (artifact.method or "").lower() in {"lora", "qlora"} else artifact.method,
            "capabilities": {},
            "lifecycle_state": "available",
            "health": "unknown",
            "active": False,
            "loaded": False,
            "local_path": artifact.path,
            "last_discovered_at": now,
            "tags": ["trained", artifact.method or "adapter"],
            "metadata": {
                "trainingArtifactId": artifact.artifact_id,
                "trainingJobId": artifact.job_id,
                "baseModelRef": artifact.base_model_ref,
                "datasetVersionId": artifact.dataset_version_id,
                "method": artifact.method,
                "configHash": artifact.config_hash,
                "contentHash": artifact.content_hash,
                "modelCardPath": artifact.model_card_path,
                "evaluation": artifact.evaluation,
                "compatibility": artifact.compatibility,
                "inferenceReady": bool((artifact.compatibility or {}).get("inference_ready")),
                "note": (
                    "Trained artifact registered for lineage; "
                    "loadability depends on a compatible runtime."
                ),
            },
            "created_at": now,
        }
    )
    training_store.update_artifact_registered_model(artifact.artifact_id, model_id)
    return model_id


def sync_completed_artifacts_to_models(
    *,
    model_store: ModelStore,
    training_store: TrainingStore,
) -> list[dict[str, Any]]:
    """Register any completed artifacts missing registered_model_id."""
    synced: list[dict[str, Any]] = []
    for job in training_store.list_jobs(limit=500):
        if not job.artifact_id:
            continue
        artifact = training_store.get_artifact(job.artifact_id)
        if artifact is None or artifact.registered_model_id:
            continue
        model_id = register_training_artifact_as_model(
            model_store=model_store,
            training_store=training_store,
            artifact=artifact,
        )
        synced.append(
            {
                "artifactId": artifact.artifact_id,
                "modelId": model_id,
                "jobId": job.job_id,
            }
        )
    return synced
