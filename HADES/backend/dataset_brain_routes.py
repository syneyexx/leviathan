"""FastAPI routes for the offline Dataset Brain.

Registered TRAINEN datasets can be materialized under the HADES data root and
projected into the existing Knowledge Library. Once materialized/indexed, normal
chat retrieval searches these chunks without internet access or model training.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, SecretStr

from dataset_brain import DatasetBrainManager
from dataset_brain_preflight import DatasetBrainStorageError, preflight_hf_disk
from platform_db import PlatformDatabase


class DatasetBrainIndexInput(BaseModel):
    hf_token: SecretStr | None = None
    approved_network: bool = False
    approved_file_read: bool = False
    approved_subprocess: bool = False
    rebuild_index: bool = False
    rematerialize: bool = False


def mount_dataset_brain_routes(ctx: dict[str, Any]) -> APIRouter:
    router = APIRouter(prefix="/training/brain", tags=["training", "dataset-brain"])

    def manager() -> DatasetBrainManager:
        return DatasetBrainManager.from_database(ctx["database"])

    def policy(name: str, default: str = "ask") -> str:
        try:
            values = ctx["database"].get_settings()
            return str(values.get(name) or default).lower()
        except Exception:
            return default

    def enforce_policy(name: str, approved: bool, action: str) -> None:
        current = policy(name)
        if current == "block":
            raise HTTPException(status_code=403, detail=f"{action} is geblokkeerd door {name}.")
        if current == "ask" and not approved:
            raise HTTPException(
                status_code=409,
                detail=f"Expliciete toestemming vereist voor {action} ({name}=ask).",
            )

    @router.get("/status")
    async def brain_statuses() -> list[dict[str, Any]]:
        return await asyncio.to_thread(manager().statuses)

    @router.get("/datasets/{dataset_id}")
    async def brain_dataset_status(dataset_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(manager().status, dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Dataset niet gevonden.") from exc

    @router.get("/jobs")
    async def brain_jobs() -> list[dict[str, Any]]:
        return await asyncio.to_thread(manager().list_jobs)

    @router.get("/jobs/{job_id}")
    async def brain_job(job_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(manager().get_job, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Brain-indexering niet gevonden.") from exc

    @router.get("/jobs/{job_id}/log")
    async def brain_job_log(job_id: str) -> dict[str, str]:
        try:
            return {"content": await asyncio.to_thread(manager().tail_log, job_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Brain-indexering niet gevonden.") from exc

    @router.post("/datasets/{dataset_id}/index", status_code=status.HTTP_201_CREATED)
    async def index_dataset(dataset_id: str, values: DatasetBrainIndexInput) -> dict[str, Any]:
        brain = manager()
        try:
            dataset = await asyncio.to_thread(brain.workspace.get_dataset, dataset_id)
            current = await asyncio.to_thread(brain.status, dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Dataset niet gevonden.") from exc

        needs_source_read = values.rematerialize or not bool(current.get("materialized_complete"))
        source_type = str(dataset.get("source_type") or "")
        if needs_source_read and source_type == "huggingface":
            enforce_policy("network_policy", values.approved_network, "Hugging Face dataset lokaal opslaan")
        elif needs_source_read:
            enforce_policy("file_read_policy", values.approved_file_read, "dataset lokaal materialiseren")

        token = values.hf_token.get_secret_value() if values.hf_token is not None else None
        storage_preflight: dict[str, Any] | None = None
        if needs_source_read and source_type == "huggingface":
            try:
                storage_preflight = await asyncio.to_thread(
                    preflight_hf_disk,
                    brain.root,
                    dataset,
                    token=token,
                )
            except DatasetBrainStorageError as exc:
                raise HTTPException(status_code=507, detail=str(exc)) from exc

        enforce_policy("subprocess_policy", values.approved_subprocess, "Dataset Brain worker starten")
        try:
            job = await asyncio.to_thread(
                brain.create_job,
                dataset_id=dataset_id,
                token=token,
                rebuild_index=values.rebuild_index,
                rematerialize=values.rematerialize,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if storage_preflight is not None:
            job = {**job, "storage_preflight": storage_preflight}
        return job

    @router.post("/jobs/{job_id}/cancel")
    async def cancel_brain_job(job_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(manager().cancel_job, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Brain-indexering niet gevonden.") from exc

    @router.delete("/datasets/{dataset_id}", status_code=status.HTTP_200_OK)
    async def remove_dataset_brain(dataset_id: str) -> dict[str, Any]:
        brain = manager()
        platform = PlatformDatabase(str(ctx["database"].path))
        platform.initialize()
        try:
            return await asyncio.to_thread(brain.remove_dataset_brain, dataset_id, platform_db=platform)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Dataset niet gevonden.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router
