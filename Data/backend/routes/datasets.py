"""FastAPI routes for the Datasets subsystem."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from Data.modules.datasets import DatasetError, DatasetService
from Data.modules.common.atomic import ensure_dir
from Data.modules.common.secrets import redact_secrets


def _raise(exc: DatasetError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.public_dict()) from exc


MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MiB per request; larger corpora use local/HF paths
ALLOWED_UPLOAD_SUFFIXES = {".jsonl", ".ndjson", ".json", ".csv", ".tsv", ".txt", ".md", ".markdown"}


class CreateDatasetBody(BaseModel):
    name: str
    description: str = ""
    license: str | None = None
    metadata: dict[str, Any] | None = None


class InspectPathBody(BaseModel):
    path: str


class ImportLocalBody(BaseModel):
    path: str
    name: str | None = None
    description: str = ""
    license: str | None = None
    materialize: bool = True
    datasetId: str | None = None


class ImportHfBody(BaseModel):
    repositoryId: str
    filename: str
    revision: str = "main"
    name: str | None = None
    description: str = ""
    license: str | None = None
    token: str | None = None
    materialize: bool = True
    datasetId: str | None = None


class TransformBody(BaseModel):
    transforms: list[dict[str, Any]] = Field(default_factory=list)


class SplitBody(BaseModel):
    seed: int = 42
    trainRatio: float = 0.8
    valRatio: float = 0.1
    testRatio: float = 0.1


class ExportBody(BaseModel):
    split: str | None = None


class IndexBody(BaseModel):
    scope: str = "dataset"
    maxRecords: int | None = None


class HfListBody(BaseModel):
    repositoryId: str
    revision: str = "main"
    token: str | None = None


def build_datasets_router(service: DatasetService) -> APIRouter:
    router = APIRouter(tags=["datasets"])

    @router.get("/api/datasets")
    def list_datasets(limit: int = 100) -> dict:
        items = service.list_datasets(limit=limit)
        return {"datasets": [d.public_dict() for d in items]}

    @router.post("/api/datasets")
    def create_dataset(body: CreateDatasetBody) -> dict:
        ds = service.create_dataset(
            name=body.name,
            description=body.description,
            license=body.license,
            metadata=body.metadata,
        )
        return {"dataset": ds.public_dict()}

    @router.post("/api/datasets/upload")
    async def upload_dataset(
        file: UploadFile = File(...),
        name: str | None = Form(default=None),
        description: str = Form(default=""),
        license: str | None = Form(default=None),
        materialize: bool = Form(default=True),
    ) -> dict:
        filename = Path(file.filename or "upload.bin").name
        if "\x00" in filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail={"code": "unsafe_filename", "message": "Invalid filename"})
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "unsupported_extension",
                    "message": f"Unsupported upload type: {suffix or '(none)'}",
                    "allowed": sorted(ALLOWED_UPLOAD_SUFFIXES),
                },
            )
        upload_root = ensure_dir(service.corpus.datasets_raw / "_uploads")
        dest = upload_root / f"{Path(filename).stem}-{Path(filename).suffix}"
        # Unique dest
        from uuid import uuid4

        dest = upload_root / f"{uuid4().hex}_{filename}"
        total = 0
        try:
            with dest.open("wb") as handle:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail={
                                "code": "upload_too_large",
                                "message": f"Upload exceeds {MAX_UPLOAD_BYTES} bytes; use local path or HF import",
                            },
                        )
                    handle.write(chunk)
        except HTTPException:
            dest.unlink(missing_ok=True)
            raise
        except Exception as exc:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail={"code": "upload_failed", "message": str(exc)}) from exc
        try:
            job = service.enqueue_import_local(
                path=str(dest),
                name=name or Path(filename).stem,
                description=description,
                license=license,
                materialize=materialize,
            )
        except DatasetError as exc:
            dest.unlink(missing_ok=True)
            _raise(exc)
            raise
        return {"job": service.public_job(job), "bytes": total, "filename": filename}

    @router.get("/api/datasets/{dataset_id}")
    def get_dataset(dataset_id: str) -> dict:
        try:
            ds = service.get_dataset(dataset_id)
        except DatasetError as exc:
            _raise(exc)
        return {
            "dataset": ds.public_dict(),
            "versions": [v.public_dict() for v in service.list_versions(dataset_id)],
            "files": [f.public_dict() for f in service.store.list_files(dataset_id)],
            "indexes": [i.public_dict() for i in service.store.list_indexes(dataset_id)],
        }

    @router.delete("/api/datasets/{dataset_id}")
    def delete_dataset(dataset_id: str) -> dict:
        try:
            service.get_dataset(dataset_id)
        except DatasetError as exc:
            _raise(exc)
        ok = service.store.delete_dataset(dataset_id)
        return {"deleted": ok, "datasetId": dataset_id}

    @router.post("/api/datasets/inspect")
    def inspect_path(body: InspectPathBody) -> dict:
        try:
            return {"inspection": service.inspect_path(body.path)}
        except DatasetError as exc:
            _raise(exc)
            raise  # pragma: no cover

    @router.post("/api/datasets/import/local")
    def import_local(body: ImportLocalBody) -> dict:
        try:
            job = service.enqueue_import_local(
                path=body.path,
                name=body.name,
                description=body.description,
                license=body.license,
                materialize=body.materialize,
                dataset_id=body.datasetId,
            )
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"job": service.public_job(job)}

    @router.post("/api/datasets/import/huggingface")
    def import_hf(body: ImportHfBody) -> dict:
        try:
            job = service.enqueue_import_hf(
                repository_id=body.repositoryId,
                filename=body.filename,
                revision=body.revision,
                name=body.name,
                description=body.description,
                license=body.license,
                token=body.token,
                materialize=body.materialize,
                dataset_id=body.datasetId,
            )
        except DatasetError as exc:
            _raise(exc)
            raise
        payload = service.public_job(job)
        # Ensure request body token never echoed
        return {"job": payload}

    @router.post("/api/datasets/huggingface/list")
    def hf_list(body: HfListBody) -> dict:
        try:
            files = service.list_hf_files(
                body.repositoryId, revision=body.revision, token=body.token
            )
        except DatasetError as exc:
            _raise(exc)
            raise
        # Redact any accidental secrets in file metadata strings
        safe = []
        for item in files:
            safe.append({k: redact_secrets(str(v)) if isinstance(v, str) else v for k, v in item.items()})
        return {"files": safe}

    @router.get("/api/datasets/{dataset_id}/versions")
    def list_versions(dataset_id: str) -> dict:
        try:
            versions = service.list_versions(dataset_id)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"versions": [v.public_dict() for v in versions]}

    @router.get("/api/datasets/versions/{version_id}")
    def get_version(version_id: str) -> dict:
        try:
            ver = service.get_version(version_id)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"version": ver.public_dict()}

    @router.get("/api/datasets/versions/{version_id}/preview")
    def preview_version(version_id: str, limit: int = 20) -> dict:
        try:
            rows = service.preview_version(version_id, limit=limit)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"rows": rows, "limit": limit}

    @router.get("/api/datasets/versions/{version_id}/pii")
    def scan_pii(version_id: str) -> dict:
        try:
            report = service.scan_pii(version_id)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"pii": report}

    @router.post("/api/datasets/{dataset_id}/materialize")
    def materialize(dataset_id: str) -> dict:
        try:
            job = service.enqueue_materialize(dataset_id)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"job": service.public_job(job)}

    @router.post("/api/datasets/{dataset_id}/versions/{version_id}/validate")
    def validate(dataset_id: str, version_id: str) -> dict:
        try:
            job = service.enqueue_validate(dataset_id, version_id)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"job": service.public_job(job)}

    @router.post("/api/datasets/{dataset_id}/versions/{version_id}/dedupe")
    def dedupe(dataset_id: str, version_id: str) -> dict:
        try:
            job = service.enqueue_dedupe(dataset_id, version_id)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"job": service.public_job(job)}

    @router.post("/api/datasets/{dataset_id}/versions/{version_id}/transform")
    def transform(dataset_id: str, version_id: str, body: TransformBody) -> dict:
        try:
            job = service.enqueue_transform(dataset_id, version_id, body.transforms)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"job": service.public_job(job)}

    @router.post("/api/datasets/{dataset_id}/versions/{version_id}/split")
    def split(dataset_id: str, version_id: str, body: SplitBody) -> dict:
        try:
            job = service.enqueue_split(
                dataset_id,
                version_id,
                seed=body.seed,
                train_ratio=body.trainRatio,
                val_ratio=body.valRatio,
                test_ratio=body.testRatio,
            )
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"job": service.public_job(job)}

    @router.post("/api/datasets/{dataset_id}/versions/{version_id}/tokenize-stats")
    def tokenize_stats(dataset_id: str, version_id: str) -> dict:
        try:
            job = service.enqueue_tokenize_stats(dataset_id, version_id)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"job": service.public_job(job)}

    @router.post("/api/datasets/{dataset_id}/versions/{version_id}/export")
    def export_version(dataset_id: str, version_id: str, body: ExportBody | None = None) -> dict:
        body = body or ExportBody()
        try:
            job = service.enqueue_export(dataset_id, version_id, split=body.split)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"job": service.public_job(job)}

    @router.post("/api/datasets/{dataset_id}/versions/{version_id}/index")
    def index_version(dataset_id: str, version_id: str, body: IndexBody | None = None) -> dict:
        body = body or IndexBody()
        try:
            job = service.enqueue_index(
                dataset_id, version_id, scope=body.scope, max_records=body.maxRecords
            )
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"job": service.public_job(job)}

    @router.get("/api/datasets/jobs")
    def list_jobs(datasetId: str | None = None, limit: int = 100) -> dict:
        jobs = service.store.list_jobs(dataset_id=datasetId, limit=limit)
        return {"jobs": [service.public_job(j) for j in jobs]}

    @router.get("/api/datasets/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        try:
            job = service.get_job(job_id)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"job": service.public_job(job)}

    @router.post("/api/datasets/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        try:
            job = service.cancel_job(job_id)
        except DatasetError as exc:
            _raise(exc)
            raise
        return {"job": service.public_job(job)}

    @router.post("/api/datasets/jobs/process")
    def process_jobs(maxJobs: int = 10) -> dict:
        done = service.process_jobs(max_jobs=maxJobs)
        return {"processed": [service.public_job(j) for j in done]}

    @router.post("/api/datasets/jobs/reconcile")
    def reconcile() -> dict:
        updated = service.reconcile()
        return {"updated": [service.public_job(j) for j in updated]}

    return router
