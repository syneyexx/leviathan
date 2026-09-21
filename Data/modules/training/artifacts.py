"""Artifact registration and export helpers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_file
from Data.modules.common.secrets import redact_secrets

from .store import TrainingStore
from .types import ArtifactRecord, DurableTrainingJob


def export_artifact(
    store: TrainingStore,
    job: DurableTrainingJob,
    *,
    export_root: Path,
) -> dict[str, Any]:
    if not job.artifact_id:
        raise ValueError("Job has no registered artifact to export")
    artifact = store.get_artifact(job.artifact_id)
    if artifact is None:
        raise KeyError(f"Artifact not found: {job.artifact_id}")
    src = Path(artifact.path)
    if not src.exists():
        raise FileNotFoundError(f"Artifact path missing: {artifact.path}")
    dest = export_root / job.job_id / artifact.artifact_id
    ensure_dir(dest.parent)
    if dest.exists():
        shutil.rmtree(dest)
    if src.is_dir():
        shutil.copytree(src, dest)
    else:
        ensure_dir(dest)
        shutil.copy2(src, dest / src.name)
    manifest = {
        "jobId": job.job_id,
        "artifactId": artifact.artifact_id,
        "sourcePath": artifact.path,
        "exportPath": str(dest),
        "method": artifact.method,
        "baseModelRef": artifact.base_model_ref,
        "configHash": artifact.config_hash,
        "contentHash": artifact.content_hash,
        "evaluation": artifact.evaluation,
    }
    manifest_path = dest / "export_manifest.json"
    atomic_write_text(manifest_path, redact_secrets(json.dumps(manifest, indent=2)))
    return {
        "exportPath": str(dest),
        "manifestPath": str(manifest_path),
        "manifestHash": sha256_file(manifest_path),
        "artifact": artifact.public_dict(),
    }


def list_job_artifacts(store: TrainingStore, job_id: str) -> list[ArtifactRecord]:
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if not job.artifact_id:
        return []
    art = store.get_artifact(job.artifact_id)
    return [art] if art else []
