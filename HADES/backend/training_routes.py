"""Typed FastAPI surface for the isolated HADES training workspace."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field, SecretStr

from dataset_brain import DatasetBrainManager, read_manifest
from dataset_brain_invalidation import invalidate_mapping_projection
from huggingface_refs import normalize_huggingface_dataset_ref
from training_service import TrainingWorkspace, UPLOAD_LIMIT_BYTES


class LocalDatasetInput(BaseModel):
    path: str = Field(min_length=1, max_length=4000)
    name: str = Field(default="", max_length=160)
    text_field: str = Field(default="", max_length=200)
    approved_file_read: bool = False


class HuggingFaceInspectInput(BaseModel):
    dataset_id: str = Field(min_length=3, max_length=512)
    token: SecretStr | None = None
    approved_network: bool = False


class HuggingFacePreviewInput(HuggingFaceInspectInput):
    config: str = Field(min_length=1, max_length=160)
    split: str = Field(min_length=1, max_length=160)
    rows: int = Field(default=20, ge=1, le=100)


class HuggingFaceDatasetInput(HuggingFacePreviewInput):
    name: str = Field(default="", max_length=160)
    text_field: str = Field(default="", max_length=200)


class DatasetMappingInput(BaseModel):
    text_field: str = Field(default="", max_length=200)


class TrainingJobInput(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=100)
    base_model: str = Field(min_length=1, max_length=1000)
    max_steps: int = Field(default=200, ge=1, le=1_000_000)
    learning_rate: float = Field(default=2e-4, gt=0, le=1)
    sequence_length: int = Field(default=1024, ge=64, le=131_072)
    batch_size: int = Field(default=1, ge=1, le=128)
    gradient_accumulation_steps: int = Field(default=8, ge=1, le=4096)
    lora_r: int = Field(default=16, ge=1, le=1024)
    lora_alpha: int = Field(default=32, ge=1, le=8192)
    lora_dropout: float = Field(default=0.05, ge=0, lt=1)
    load_in_4bit: bool = False
    memory_strategy: str = Field(default="auto", max_length=64)
    activation_checkpointing: str = Field(default="auto", max_length=32)
    host_memory_limit_bytes: int | None = Field(default=None, ge=0)
    vram_reserve_bytes: int | None = Field(default=None, ge=0)
    stream_buffer_count: int | str = "auto"
    experimental_streaming_allowed: bool = False
    hf_token: SecretStr | None = None
    approved_network: bool = False
    approved_subprocess: bool = False


class ModelInspectInput(BaseModel):
    base_model: str = Field(min_length=1, max_length=1000)
    approved_network: bool = False


class PlanInput(BaseModel):
    base_model: str = Field(min_length=1, max_length=1000)
    dataset_id: str | None = Field(default=None, max_length=100)
    max_steps: int = Field(default=200, ge=1, le=1_000_000)
    learning_rate: float = Field(default=2e-4, gt=0, le=1)
    sequence_length: int = Field(default=1024, ge=64, le=131_072)
    batch_size: int = Field(default=1, ge=1, le=128)
    gradient_accumulation_steps: int = Field(default=8, ge=1, le=4096)
    lora_r: int = Field(default=16, ge=1, le=1024)
    lora_alpha: int = Field(default=32, ge=1, le=8192)
    lora_dropout: float = Field(default=0.05, ge=0, lt=1)
    memory_strategy: str = Field(default="auto", max_length=64)
    activation_checkpointing: str = Field(default="auto", max_length=32)
    host_memory_limit_bytes: int | None = Field(default=None, ge=0)
    vram_reserve_bytes: int | None = Field(default=None, ge=0)
    stream_buffer_count: int | str = "auto"
    experimental_streaming_allowed: bool = False
    load_in_4bit: bool | None = None
    approved_network: bool = False


class BenchmarkStartInput(BaseModel):
    approved: bool = False
    include_storage: bool = False
    include_gpu: bool = True


def mount_training_routes(ctx: dict[str, Any]) -> APIRouter:
    router = APIRouter(prefix="/training", tags=["training"])

    def workspace() -> TrainingWorkspace:
        database = ctx["database"]
        db_path = Path(str(database.path)).expanduser().resolve()
        return TrainingWorkspace(db_path.parent / "training")

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
            raise HTTPException(status_code=409, detail=f"Expliciete toestemming vereist voor {action} ({name}=ask).")

    def enforce_block_policy(name: str, action: str) -> None:
        """Honor an absolute block while a distinct one-shot approval contract is added separately."""
        if policy(name) == "block":
            raise HTTPException(status_code=403, detail=f"{action} is geblokkeerd door {name}.")

    def secret(value: SecretStr | None) -> str | None:
        return value.get_secret_value() if value is not None else None

    @router.get("/capabilities")
    async def capabilities() -> dict[str, Any]:
        return await asyncio.to_thread(workspace().capabilities)

    @router.get("/hardware")
    async def hardware() -> dict[str, Any]:
        return await asyncio.to_thread(workspace().hardware_snapshot)

    @router.post("/models/inspect")
    async def inspect_model(values: ModelInspectInput) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(workspace().inspect_model, values.base_model)
        except (ValueError, OSError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/plans")
    async def create_plan(values: PlanInput) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                workspace().create_plan,
                base_model=values.base_model,
                dataset_id=values.dataset_id,
                max_steps=values.max_steps,
                learning_rate=values.learning_rate,
                sequence_length=values.sequence_length,
                batch_size=values.batch_size,
                gradient_accumulation_steps=values.gradient_accumulation_steps,
                lora_r=values.lora_r,
                lora_alpha=values.lora_alpha,
                lora_dropout=values.lora_dropout,
                memory_strategy=values.memory_strategy,
                activation_checkpointing=values.activation_checkpointing,
                host_memory_limit_bytes=values.host_memory_limit_bytes,
                vram_reserve_bytes=values.vram_reserve_bytes,
                stream_buffer_count=values.stream_buffer_count,
                experimental_streaming_allowed=values.experimental_streaming_allowed,
                load_in_4bit=values.load_in_4bit,
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/benchmarks")
    async def start_benchmark(values: BenchmarkStartInput) -> dict[str, Any]:
        if not values.approved:
            raise HTTPException(status_code=409, detail="Expliciete toestemming vereist voor ATME-kalibratiebenchmark.")
        try:
            return await asyncio.to_thread(
                workspace().run_calibration_benchmark,
                include_storage=values.include_storage,
                include_gpu=values.include_gpu,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/benchmarks/latest")
    async def latest_benchmark() -> dict[str, Any]:
        result = await asyncio.to_thread(workspace().latest_benchmark)
        if result is None:
            raise HTTPException(status_code=404, detail="Geen ATME-benchmarkprofiel beschikbaar.")
        return result

    @router.get("/datasets")
    async def list_datasets() -> list[dict[str, Any]]:
        return await asyncio.to_thread(workspace().list_datasets)

    @router.post("/datasets/local", status_code=status.HTTP_201_CREATED)
    async def register_local_dataset(values: LocalDatasetInput) -> dict[str, Any]:
        enforce_policy("file_read_policy", values.approved_file_read, "lokale dataset lezen")
        try:
            return await asyncio.to_thread(workspace().register_local, values.path, name=values.name, text_field=values.text_field)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Datasetbestand niet gevonden: {exc}") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/datasets/upload", status_code=status.HTTP_201_CREATED)
    async def upload_dataset(
        file: UploadFile = File(...),
        name: str = Form(default=""),
        text_field: str = Form(default=""),
    ) -> dict[str, Any]:
        training = workspace()
        try:
            target = await asyncio.to_thread(training.prepare_upload_path, file.filename or "dataset.jsonl")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        written = 0
        registered = False
        try:
            with target.open("wb") as handle:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > UPLOAD_LIMIT_BYTES:
                        raise HTTPException(status_code=413, detail="Browser-upload is maximaal 512 MB. Registreer grotere datasets via een lokaal pad.")
                    handle.write(chunk)
            result = await asyncio.to_thread(training.register_local, target, name=name, text_field=text_field, managed_upload=True)
            registered = True
            return result
        except HTTPException:
            raise
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            await file.close()
            if not registered:
                await asyncio.to_thread(shutil.rmtree, target.parent, True)

    @router.post("/huggingface/inspect")
    async def inspect_huggingface(values: HuggingFaceInspectInput) -> dict[str, Any]:
        enforce_policy("network_policy", values.approved_network, "Hugging Face dataset inspecteren")
        try:
            dataset_id = normalize_huggingface_dataset_ref(values.dataset_id)
            return await workspace().inspect_huggingface(dataset_id, token=secret(values.token))
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Hugging Face is niet bereikbaar: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/huggingface/preview")
    async def preview_huggingface(values: HuggingFacePreviewInput) -> dict[str, Any]:
        enforce_policy("network_policy", values.approved_network, "Hugging Face dataset previewen")
        try:
            dataset_id = normalize_huggingface_dataset_ref(values.dataset_id)
            return await workspace().preview_huggingface(
                dataset_id,
                config=values.config,
                split=values.split,
                token=secret(values.token),
                rows=values.rows,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Hugging Face is niet bereikbaar: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/datasets/huggingface", status_code=status.HTTP_201_CREATED)
    async def register_huggingface_dataset(values: HuggingFaceDatasetInput) -> dict[str, Any]:
        enforce_policy("network_policy", values.approved_network, "Hugging Face dataset registreren")
        try:
            dataset_id = normalize_huggingface_dataset_ref(values.dataset_id)
            return await workspace().register_huggingface(
                dataset_id,
                config=values.config,
                split=values.split,
                name=values.name,
                text_field=values.text_field,
                token=secret(values.token),
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Hugging Face is niet bereikbaar: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/datasets/{dataset_id}/mapping")
    async def update_dataset_mapping(dataset_id: str, values: DatasetMappingInput) -> dict[str, Any]:
        training = workspace()
        try:
            current = await asyncio.to_thread(training.get_dataset, dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Dataset niet gevonden.") from exc

        text_field = values.text_field.strip()
        if text_field and text_field not in set(current.get("columns") or []):
            raise HTTPException(status_code=400, detail="De gekozen tekstkolom komt niet voor in de dataset-preview.")
        if str((current.get("mapping") or {}).get("text_field") or "").strip() == text_field:
            return current

        brain = DatasetBrainManager.from_database(ctx["database"])
        jobs = await asyncio.to_thread(brain.list_jobs, dataset_id=dataset_id)
        if any(job.get("status") in {"queued", "running", "cancelling"} for job in jobs):
            raise HTTPException(
                status_code=409,
                detail="Wijzig de datasetmapping pas nadat de actieve Brain-indexering is gestopt.",
            )

        brain_manifest = read_manifest(training.root, dataset_id)
        if brain_manifest is not None:
            await asyncio.to_thread(
                invalidate_mapping_projection,
                training.root,
                ctx["database"].path,
                dataset_id,
            )
        try:
            return await asyncio.to_thread(training.update_mapping, dataset_id, text_field=text_field)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Dataset niet gevonden.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_dataset(dataset_id: str) -> Response:
        training = workspace()
        try:
            brain_manifest = read_manifest(training.root, dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Dataset niet gevonden.") from exc
        if brain_manifest is not None:
            raise HTTPException(
                status_code=409,
                detail="Deze dataset zit in HADES Brain. Verwijder eerst expliciet de offline Brain-data; daarna kan de datasetregistratie weg.",
            )
        try:
            await asyncio.to_thread(training.delete_dataset, dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Dataset niet gevonden.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/jobs")
    async def list_jobs() -> list[dict[str, Any]]:
        return await asyncio.to_thread(workspace().list_jobs)

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(workspace().get_job, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trainingstaak niet gevonden.") from exc

    @router.get("/jobs/{job_id}/log")
    async def job_log(job_id: str) -> dict[str, str]:
        try:
            return {"content": await asyncio.to_thread(workspace().tail_log, job_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trainingstaak niet gevonden.") from exc

    @router.get("/jobs/{job_id}/telemetry")
    async def job_telemetry(job_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(workspace().job_telemetry, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trainingstaak niet gevonden.") from exc

    @router.post("/jobs", status_code=status.HTTP_201_CREATED)
    async def create_training_job(values: TrainingJobInput) -> dict[str, Any]:
        training = workspace()
        try:
            dataset = await asyncio.to_thread(training.get_dataset, values.dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Dataset niet gevonden.") from exc

        base_model = values.base_model.strip()
        expanded = Path(base_model).expanduser()
        looks_like_local_path = expanded.is_absolute() or base_model.startswith(".") or "\\" in base_model
        local_model = expanded.is_dir()
        if expanded.exists() and not expanded.is_dir():
            raise HTTPException(
                status_code=400,
                detail="Basismodel moet een Hugging Face model-ID of lokale Transformers-modelmap zijn; losse GGUF-bestanden zijn niet direct trainbaar.",
            )
        if looks_like_local_path and not local_model:
            raise HTTPException(status_code=404, detail="Lokale basismodelmap bestaat niet.")

        # Policy gates before Brain/plan work so blocked hosts never spawn a worker path.
        enforce_policy("subprocess_policy", values.approved_subprocess, "training worker starten")

        brain_manifest = None
        brain_snapshot = None
        try:
            brain_manifest = read_manifest(training.root, values.dataset_id)
        except KeyError:
            brain_manifest = None
        if brain_manifest and brain_manifest.get("materialized_complete"):
            candidate = Path(str(brain_manifest.get("snapshot_path") or "")).expanduser().resolve()
            brain_snapshot = candidate if candidate.is_file() else None
        dataset_needs_network = dataset.get("source_type") == "huggingface" and brain_snapshot is None
        model_needs_network = not local_model
        if dataset_needs_network or model_needs_network:
            enforce_policy("network_policy", values.approved_network, "trainingsbronnen/model downloaden")
        try:
            return await asyncio.to_thread(
                training.create_job,
                dataset_id=values.dataset_id,
                base_model=base_model,
                max_steps=values.max_steps,
                learning_rate=values.learning_rate,
                sequence_length=values.sequence_length,
                batch_size=values.batch_size,
                gradient_accumulation_steps=values.gradient_accumulation_steps,
                lora_r=values.lora_r,
                lora_alpha=values.lora_alpha,
                lora_dropout=values.lora_dropout,
                load_in_4bit=values.load_in_4bit,
                memory_strategy=values.memory_strategy,
                activation_checkpointing=values.activation_checkpointing,
                host_memory_limit_bytes=values.host_memory_limit_bytes,
                vram_reserve_bytes=values.vram_reserve_bytes,
                stream_buffer_count=values.stream_buffer_count,
                experimental_streaming_allowed=values.experimental_streaming_allowed,
                token=secret(values.hf_token),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/jobs/{job_id}/cancel")
    async def cancel_training_job(job_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(workspace().cancel_job, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trainingstaak niet gevonden.") from exc

    return router
