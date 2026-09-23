"""DatasetService — import, materialize, transform, split, index orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import ensure_dir
from Data.modules.common.corpus import CorpusLayout, build_corpus_layout
from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import PathEscapeError, safe_join
from Data.modules.common.secrets import redact_secrets
from Data.modules.knowledge import KnowledgeStore

from Data.backend.config import Settings, load_settings

from .canonicalize import canonical_schema_dict
from .dedupe import exact_dedupe
from .export import export_jsonl, preview_jsonl
from .formats import detect_format
from .huggingface import HfDownloadCheckpoint, download_hf_file, list_hf_dataset_files
from .importers import copy_immutable_raw, inspect_local_file, reject_traversal_components, resolve_import_path
from .indexing import index_version_file
from .jobs import DatasetJobRunner
from .materialize import load_materialized_jsonl, materialize_from_raw, write_canonical_jsonl, write_manifest
from .pii import scan_records_pii
from .splits import deterministic_split
from .store import DatasetStore, utc_now
from .tokenize_stats import compute_token_stats
from .transforms import apply_transforms
from .types import (
    DatasetError,
    DatasetJob,
    DatasetJobStatus,
    DatasetJobType,
    DatasetRecord,
    DatasetStatus,
    DatasetVersion,
    DetectedFormat,
    IndexStatus,
    SourceType,
    VersionKind,
    VersionStatus,
)
from .validation import validate_records


class DatasetService:
    """Production dataset control plane (local + HF import through indexing)."""

    def __init__(
        self,
        store: DatasetStore,
        *,
        corpus: CorpusLayout,
        knowledge: KnowledgeStore | None = None,
        settings: Settings | None = None,
        allowed_import_roots: list[Path] | None = None,
    ) -> None:
        self.store = store
        self.corpus = corpus
        self.settings = settings or load_settings()
        self.knowledge = knowledge
        self.allowed_import_roots = allowed_import_roots or [
            self.corpus.root,
            Path(self.settings.knowledge.data_root),
        ]
        self._hf_tokens: dict[str, str | None] = {}
        self.runner = DatasetJobRunner(store, self._build_handlers())

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        *,
        db_path: Path | None = None,
        knowledge: KnowledgeStore | None = None,
    ) -> "DatasetService":
        settings = settings or load_settings()
        path = db_path or Path(settings.database_path)
        store = DatasetStore(path)
        store.initialize()
        corpus = build_corpus_layout(settings)
        if knowledge is None:
            knowledge = KnowledgeStore(path, data_root=Path(settings.knowledge.data_root))
            knowledge.initialize()
        return cls(store, corpus=corpus, knowledge=knowledge, settings=settings)

    def _build_handlers(self) -> dict[str, Any]:
        return {
            DatasetJobType.IMPORT_LOCAL.value: self._handle_import_local,
            DatasetJobType.IMPORT_HF.value: self._handle_import_hf,
            DatasetJobType.MATERIALIZE.value: self._handle_materialize,
            DatasetJobType.VALIDATE.value: self._handle_validate,
            DatasetJobType.DEDUPE.value: self._handle_dedupe,
            DatasetJobType.TRANSFORM.value: self._handle_transform,
            DatasetJobType.SPLIT.value: self._handle_split,
            DatasetJobType.TOKENIZE_STATS.value: self._handle_tokenize_stats,
            DatasetJobType.EXPORT.value: self._handle_export,
            DatasetJobType.INDEX.value: self._handle_index,
        }

    # --- Queries ---

    def list_datasets(self, *, limit: int = 100) -> list[DatasetRecord]:
        return self.store.list_datasets(limit=limit)

    def get_dataset(self, dataset_id: str) -> DatasetRecord:
        ds = self.store.get_dataset(dataset_id)
        if ds is None:
            raise DatasetError("Dataset not found", code="not_found", http_status=404)
        return ds

    def list_versions(self, dataset_id: str) -> list[DatasetVersion]:
        self.get_dataset(dataset_id)
        return self.store.list_versions(dataset_id)

    def get_version(self, version_id: str) -> DatasetVersion:
        ver = self.store.get_version(version_id)
        if ver is None:
            raise DatasetError("Version not found", code="not_found", http_status=404)
        return ver

    def get_job(self, job_id: str) -> DatasetJob:
        job = self.store.get_job(job_id)
        if job is None:
            raise DatasetError("Job not found", code="not_found", http_status=404)
        return job

    # --- Create / import ---

    def create_dataset(
        self,
        *,
        name: str,
        description: str = "",
        license: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DatasetRecord:
        return self.store.create_dataset(
            name=name,
            source_type=SourceType.LOCAL,
            description=description,
            license=license,
            metadata=metadata,
            status=DatasetStatus.CREATED,
        )

    def inspect_path(self, path: str) -> dict[str, Any]:
        reject_traversal_components(path)
        resolved = resolve_import_path(path, allowed_roots=self.allowed_import_roots)
        return inspect_local_file(resolved)

    def enqueue_import_local(
        self,
        *,
        path: str,
        name: str | None = None,
        description: str = "",
        license: str | None = None,
        materialize: bool = True,
        dataset_id: str | None = None,
    ) -> DatasetJob:
        reject_traversal_components(path)
        # Validate early so API fails fast on traversal / missing files
        resolve_import_path(path, allowed_roots=self.allowed_import_roots)
        if dataset_id:
            ds = self.get_dataset(dataset_id)
        else:
            ds = self.store.create_dataset(
                name=name or Path(path).name,
                source_type=SourceType.LOCAL,
                description=description,
                license=license,
                original_filename=Path(path).name,
                status=DatasetStatus.IMPORTING,
            )
        return self.store.create_job(
            job_type=DatasetJobType.IMPORT_LOCAL,
            dataset_id=ds.dataset_id,
            config={"path": path, "materialize": materialize},
        )

    def enqueue_import_hf(
        self,
        *,
        repository_id: str,
        filename: str,
        revision: str = "main",
        name: str | None = None,
        description: str = "",
        license: str | None = None,
        token: str | None = None,
        materialize: bool = True,
        dataset_id: str | None = None,
    ) -> DatasetJob:
        if ".." in Path(filename.replace("\\", "/")).parts:
            raise DatasetError("Parent traversal refused", code="path_traversal", http_status=400)
        if dataset_id:
            ds = self.get_dataset(dataset_id)
        else:
            ds = self.store.create_dataset(
                name=name or f"{repository_id}/{filename}",
                source_type=SourceType.HUGGINGFACE,
                description=description,
                license=license,
                original_uri=f"hf://datasets/{repository_id}@{revision}/{filename}",
                original_filename=Path(filename).name,
                status=DatasetStatus.IMPORTING,
                provenance={"repositoryId": repository_id, "revision": revision, "filename": filename},
            )
        # Never persist raw token in config — redact if present
        safe_config = {
            "repositoryId": repository_id,
            "filename": filename,
            "revision": revision,
            "materialize": materialize,
            "hasToken": bool(token),
        }
        job = self.store.create_job(
            job_type=DatasetJobType.IMPORT_HF,
            dataset_id=ds.dataset_id,
            config=safe_config,
        )
        # Keep token only in-memory via ephemeral map keyed by job id
        self._hf_tokens[job.job_id] = token
        return job

    def enqueue_materialize(self, dataset_id: str, *, fmt: str | None = None) -> DatasetJob:
        self.get_dataset(dataset_id)
        return self.store.create_job(
            job_type=DatasetJobType.MATERIALIZE,
            dataset_id=dataset_id,
            config={"format": fmt},
        )

    def enqueue_validate(self, dataset_id: str, version_id: str) -> DatasetJob:
        self.get_dataset(dataset_id)
        self.get_version(version_id)
        return self.store.create_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=dataset_id,
            version_id=version_id,
            config={},
        )

    def enqueue_dedupe(self, dataset_id: str, version_id: str) -> DatasetJob:
        self.get_dataset(dataset_id)
        self.get_version(version_id)
        return self.store.create_job(
            job_type=DatasetJobType.DEDUPE,
            dataset_id=dataset_id,
            version_id=version_id,
            config={},
        )

    def enqueue_transform(
        self,
        dataset_id: str,
        version_id: str,
        transforms: list[dict[str, Any]],
    ) -> DatasetJob:
        self.get_dataset(dataset_id)
        self.get_version(version_id)
        return self.store.create_job(
            job_type=DatasetJobType.TRANSFORM,
            dataset_id=dataset_id,
            version_id=version_id,
            config={"transforms": transforms},
        )

    def enqueue_split(
        self,
        dataset_id: str,
        version_id: str,
        *,
        seed: int = 42,
        train_ratio: float = 0.8,
        val_ratio: float = 0.1,
        test_ratio: float = 0.1,
    ) -> DatasetJob:
        self.get_dataset(dataset_id)
        self.get_version(version_id)
        return self.store.create_job(
            job_type=DatasetJobType.SPLIT,
            dataset_id=dataset_id,
            version_id=version_id,
            config={
                "seed": seed,
                "trainRatio": train_ratio,
                "valRatio": val_ratio,
                "testRatio": test_ratio,
            },
        )

    def enqueue_tokenize_stats(self, dataset_id: str, version_id: str) -> DatasetJob:
        self.get_dataset(dataset_id)
        self.get_version(version_id)
        return self.store.create_job(
            job_type=DatasetJobType.TOKENIZE_STATS,
            dataset_id=dataset_id,
            version_id=version_id,
            config={},
        )

    def enqueue_export(
        self,
        dataset_id: str,
        version_id: str,
        *,
        split: str | None = None,
    ) -> DatasetJob:
        self.get_dataset(dataset_id)
        self.get_version(version_id)
        return self.store.create_job(
            job_type=DatasetJobType.EXPORT,
            dataset_id=dataset_id,
            version_id=version_id,
            config={"split": split},
        )

    def enqueue_index(
        self,
        dataset_id: str,
        version_id: str,
        *,
        scope: str = "dataset",
        max_records: int | None = None,
        offline_only: bool = False,
        source_fingerprint: str | None = None,
    ) -> DatasetJob:
        self.get_dataset(dataset_id)
        self.get_version(version_id)
        return self.store.create_job(
            job_type=DatasetJobType.INDEX,
            dataset_id=dataset_id,
            version_id=version_id,
            config={
                "scope": scope,
                "maxRecords": max_records,
                "offlineOnly": offline_only,
                "sourceFingerprint": source_fingerprint,
            },
        )

    def discover_offline_sources(self, *, max_files: int = 500) -> dict[str, Any]:
        from .offline import discover_under_roots

        roots = [
            ("datasets_raw", self.corpus.datasets_raw),
            ("datasets_materialized", self.corpus.datasets_materialized),
            ("datasets_exports", self.corpus.datasets_exports),
        ]
        sources = discover_under_roots(roots, max_files=max_files, follow_symlinks=False)
        return {
            "roots": [{"id": rid, "path": str(path)} for rid, path in roots],
            "sources": [s.public_dict() for s in sources],
            "count": len(sources),
            "truth": {
                "explicit_allowed_roots_only": True,
                "no_full_filesystem_scan": True,
            },
        }

    def offline_brain_preflight(
        self,
        dataset_id: str,
        version_id: str,
        *,
        offline_only: bool = True,
    ) -> dict[str, Any]:
        from .offline import offline_index_preflight

        self.get_dataset(dataset_id)
        ver = self.get_version(version_id)
        size = int(ver.byte_size or 0)
        embedding_status = None
        if self.knowledge is not None:
            embeddings = getattr(self.knowledge, "embeddings", None)
            if embeddings is not None and hasattr(embeddings, "status"):
                embedding_status = embeddings.status()
        pf = offline_index_preflight(
            target_dir=self.corpus.datasets_manifests,
            source_size_bytes=size,
            embedding_status=embedding_status,
            offline_only=offline_only,
        )
        return pf.public_dict()

    def list_brain_indexes(self, *, limit: int = 100) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for ds in self.store.list_datasets(limit=max(1, min(limit, 200))):
            for idx in self.store.list_indexes(ds.dataset_id):
                out.append(idx.public_dict())
                if len(out) >= limit:
                    return out
        return out

    def enqueue_offline_brain_index(
        self,
        dataset_id: str,
        version_id: str,
        *,
        scope: str = "dataset",
        max_records: int | None = None,
        source_fingerprint: str | None = None,
    ) -> DatasetJob:
        pf = self.offline_brain_preflight(dataset_id, version_id, offline_only=True)
        if not pf.get("ok"):
            raise DatasetError(
                "; ".join(pf.get("blockers") or ["offline preflight blocked"]),
                code="OFFLINE_PREFLIGHT_BLOCKED",
                http_status=409,
            )
        return self.enqueue_index(
            dataset_id,
            version_id,
            scope=scope,
            max_records=max_records,
            offline_only=True,
            source_fingerprint=source_fingerprint,
        )

    def cancel_job(self, job_id: str) -> DatasetJob:
        self.get_job(job_id)
        return self.store.request_cancel(job_id)

    def process_jobs(self, *, max_jobs: int = 50) -> list[DatasetJob]:
        return self.runner.drain(max_jobs=max_jobs)

    def reconcile(self) -> list[DatasetJob]:
        return self.runner.reconcile_interrupted()

    # --- Synchronous helpers for tests / API ---

    def import_local_sync(
        self,
        path: str,
        *,
        name: str | None = None,
        materialize: bool = True,
    ) -> dict[str, Any]:
        job = self.enqueue_import_local(path=path, name=name, materialize=materialize)
        done = self.runner.process_next()
        assert done is not None and done.job_id == job.job_id
        if done.status != DatasetJobStatus.COMPLETED:
            raise DatasetError(done.error or "import failed", code="import_failed", http_status=500)
        ds = self.get_dataset(done.dataset_id or "")
        return {"job": done.public_dict(), "dataset": ds.public_dict()}

    def preview_version(self, version_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        ver = self.get_version(version_id)
        if not ver.storage_path:
            raise DatasetError("Version has no storage path", code="no_storage", http_status=400)
        return preview_jsonl(Path(ver.storage_path), limit=limit)

    def scan_pii(self, version_id: str) -> dict[str, Any]:
        ver = self.get_version(version_id)
        if not ver.storage_path:
            raise DatasetError("Version has no storage path", code="no_storage", http_status=400)
        records = load_materialized_jsonl(Path(ver.storage_path))
        return scan_records_pii(records)

    # --- Job handlers ---

    def _dataset_dirs(self, dataset_id: str) -> dict[str, Path]:
        raw = ensure_dir(self.corpus.datasets_raw / dataset_id)
        mat = ensure_dir(self.corpus.datasets_materialized / dataset_id)
        proc = ensure_dir(self.corpus.datasets_processed / dataset_id)
        exp = ensure_dir(self.corpus.datasets_exports / dataset_id)
        man = ensure_dir(self.corpus.datasets_manifests / dataset_id)
        return {"raw": raw, "materialized": mat, "processed": proc, "exports": exp, "manifests": man}

    def _handle_import_local(self, job: DatasetJob) -> dict[str, Any]:
        assert job.dataset_id
        path = str(job.config.get("path") or "")
        reject_traversal_components(path)
        source = resolve_import_path(path, allowed_roots=self.allowed_import_roots)
        dirs = self._dataset_dirs(job.dataset_id)
        detection = detect_format(source)
        dest, digest, size = copy_immutable_raw(source, dirs["raw"])
        self.store.add_file(
            dataset_id=job.dataset_id,
            role="raw",
            path=str(dest),
            content_hash=digest,
            byte_size=size,
            metadata={"originalPath": str(source), "detection": detection.public_dict()},
        )
        self.store.update_dataset(
            job.dataset_id,
            status=DatasetStatus.RAW,
            content_hash=digest,
            byte_size=size,
            raw_path=str(dest),
            detected_format=detection.format,
            format_confidence=detection.confidence,
            original_filename=source.name,
            provenance={"sourcePath": str(source)},
        )
        raw_version = self.store.create_version(
            dataset_id=job.dataset_id,
            version_label="raw-v1",
            kind=VersionKind.RAW,
            status=VersionStatus.READY,
            storage_path=str(dest),
            schema={"type": "raw", "format": detection.format.value},
        )
        self.store.update_version(
            raw_version.version_id,
            content_hash=digest,
            byte_size=size,
        )
        self.store.update_job(job.job_id, progress=0.5, phase="raw_stored", version_id=raw_version.version_id)
        result: dict[str, Any] = {
            "rawPath": str(dest),
            "contentHash": digest,
            "byteSize": size,
            "detection": detection.public_dict(),
            "rawVersionId": raw_version.version_id,
        }
        if job.config.get("materialize", True):
            mat = self._materialize_dataset(job.dataset_id, raw_path=dest, fmt=detection.format)
            result["materialized"] = mat
        if self.runner.is_cancel_requested(job.job_id):
            raise DatasetError("cancelled", code="cancelled", http_status=409)
        return result

    def _handle_import_hf(self, job: DatasetJob) -> dict[str, Any]:
        assert job.dataset_id
        repo = str(job.config.get("repositoryId") or "")
        filename = str(job.config.get("filename") or "")
        revision = str(job.config.get("revision") or "main")
        token = self._hf_tokens.pop(job.job_id, None)
        dirs = self._dataset_dirs(job.dataset_id)
        dest = dirs["raw"] / Path(filename).name
        cp = HfDownloadCheckpoint.from_dict(job.checkpoint or {})
        if not cp.repository_id:
            cp = HfDownloadCheckpoint(repository_id=repo, revision=revision, filename=filename)

        def cancel() -> bool:
            return self.runner.is_cancel_requested(job.job_id)

        def on_progress(info: dict[str, Any]) -> None:
            self.store.update_job(
                job.job_id,
                checkpoint=info.get("checkpoint") or cp.to_dict(),
                phase=str(info.get("phase") or "downloading"),
                progress=None
                if not info.get("totalBytes")
                else min(0.9, (info.get("bytesDownloaded") or 0) / max(1, info["totalBytes"])),
            )

        downloaded = download_hf_file(
            repository_id=repo,
            filename=filename,
            dest_path=dest,
            revision=revision,
            token=token,
            checkpoint=cp,
            cancel_check=cancel,
            progress_cb=on_progress,
        )
        # Re-copy into content-addressed raw for immutability
        final, digest, size = copy_immutable_raw(downloaded.path, dirs["raw"])
        if downloaded.path != final and downloaded.path.exists():
            # Keep both; prefer content-addressed
            pass
        detection = detect_format(final)
        self.store.add_file(
            dataset_id=job.dataset_id,
            role="raw",
            path=str(final),
            content_hash=digest,
            byte_size=size,
            metadata={
                "repositoryId": repo,
                "revision": revision,
                "filename": filename,
                "url": downloaded.url,
                "detection": detection.public_dict(),
            },
        )
        self.store.update_dataset(
            job.dataset_id,
            status=DatasetStatus.RAW,
            content_hash=digest,
            byte_size=size,
            raw_path=str(final),
            detected_format=detection.format,
            format_confidence=detection.confidence,
            original_uri=f"hf://datasets/{repo}@{revision}/{filename}",
            provenance={
                "repositoryId": repo,
                "revision": revision,
                "filename": filename,
                "rateLimitEvents": downloaded.checkpoint.rate_limit_events,
            },
        )
        raw_version = self.store.create_version(
            dataset_id=job.dataset_id,
            version_label="raw-v1",
            kind=VersionKind.RAW,
            status=VersionStatus.READY,
            storage_path=str(final),
            schema={"type": "raw", "format": detection.format.value},
        )
        self.store.update_version(raw_version.version_id, content_hash=digest, byte_size=size)
        result: dict[str, Any] = {
            "rawPath": str(final),
            "contentHash": digest,
            "byteSize": size,
            "detection": detection.public_dict(),
            "checkpoint": downloaded.checkpoint.to_dict(),
            "rawVersionId": raw_version.version_id,
        }
        if job.config.get("materialize", True):
            mat = self._materialize_dataset(job.dataset_id, raw_path=final, fmt=detection.format)
            result["materialized"] = mat
        return result

    def _materialize_dataset(
        self,
        dataset_id: str,
        *,
        raw_path: Path,
        fmt: DetectedFormat | None = None,
    ) -> dict[str, Any]:
        self.store.update_dataset(dataset_id, status=DatasetStatus.MATERIALIZING)
        dirs = self._dataset_dirs(dataset_id)
        dest = dirs["materialized"] / "canonical.jsonl"
        outcome = materialize_from_raw(raw_path, dest, fmt=fmt)
        records = outcome.pop("records")
        validation = validate_records(records)
        version = self.store.create_version(
            dataset_id=dataset_id,
            version_label="materialized-v1",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY if validation["valid"] else VersionStatus.FAILED,
            storage_path=str(dest),
            schema=canonical_schema_dict(),
        )
        self.store.update_version(
            version.version_id,
            row_count=outcome["rowCount"],
            byte_size=outcome["byteSize"],
            content_hash=outcome["contentHash"],
            validation=validation,
        )
        self.store.add_file(
            dataset_id=dataset_id,
            version_id=version.version_id,
            role="materialized",
            path=str(dest),
            content_hash=outcome["contentHash"],
            byte_size=outcome["byteSize"],
        )
        write_manifest(
            dirs["manifests"] / f"{version.version_id}.json",
            {
                "datasetId": dataset_id,
                "versionId": version.version_id,
                "contentHash": outcome["contentHash"],
                "rowCount": outcome["rowCount"],
                "validation": validation,
            },
        )
        self.store.update_dataset(
            dataset_id,
            status=DatasetStatus.READY if validation["valid"] else DatasetStatus.FAILED,
            row_count=outcome["rowCount"],
        )
        return {
            "versionId": version.version_id,
            "contentHash": outcome["contentHash"],
            "rowCount": outcome["rowCount"],
            "byteSize": outcome["byteSize"],
            "validation": validation,
            "storagePath": str(dest),
        }

    def _handle_materialize(self, job: DatasetJob) -> dict[str, Any]:
        assert job.dataset_id
        ds = self.get_dataset(job.dataset_id)
        if not ds.raw_path:
            raise DatasetError("Dataset has no raw_path", code="no_raw")
        fmt_name = job.config.get("format")
        fmt = DetectedFormat(fmt_name) if fmt_name else ds.detected_format
        return self._materialize_dataset(job.dataset_id, raw_path=Path(ds.raw_path), fmt=fmt)

    def _load_version_records(self, version_id: str) -> tuple[DatasetVersion, list]:
        ver = self.get_version(version_id)
        if not ver.storage_path:
            raise DatasetError("Version has no storage", code="no_storage")
        return ver, load_materialized_jsonl(Path(ver.storage_path))

    def _write_derived_version(
        self,
        *,
        dataset_id: str,
        parent: DatasetVersion,
        label: str,
        kind: VersionKind,
        records: list,
        lineage_extra: list[dict[str, Any]] | None = None,
        split: dict[str, Any] | None = None,
        token_stats: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DatasetVersion:
        dirs = self._dataset_dirs(dataset_id)
        dest = dirs["processed"] / f"{label}.jsonl"
        content_hash, byte_size, row_count = write_canonical_jsonl(records, dest)
        lineage = list(parent.transform_lineage) + list(lineage_extra or [])
        version = self.store.create_version(
            dataset_id=dataset_id,
            version_label=label,
            kind=kind,
            parent_version_id=parent.version_id,
            status=VersionStatus.READY,
            storage_path=str(dest),
            schema=canonical_schema_dict(),
            transform_lineage=lineage,
            metadata=metadata,
        )
        self.store.update_version(
            version.version_id,
            content_hash=content_hash,
            byte_size=byte_size,
            row_count=row_count,
            split=split or {},
            token_stats=token_stats or {},
            validation=validation or validate_records(records),
            transform_lineage=lineage,
        )
        self.store.add_file(
            dataset_id=dataset_id,
            version_id=version.version_id,
            role="processed",
            path=str(dest),
            content_hash=content_hash,
            byte_size=byte_size,
        )
        return self.get_version(version.version_id)

    def _handle_validate(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        ver, records = self._load_version_records(job.version_id)
        report = validate_records(records)
        self.store.update_version(ver.version_id, validation=report)
        return report

    def _handle_dedupe(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        parent, records = self._load_version_records(job.version_id)
        kept, stats = exact_dedupe(records)
        version = self._write_derived_version(
            dataset_id=job.dataset_id,
            parent=parent,
            label=f"deduped-from-{parent.version_label}",
            kind=VersionKind.TRANSFORMED,
            records=kept,
            lineage_extra=[{"name": "exact_dedupe", "params": {}, "stats": stats, "appliedAt": utc_now()}],
            metadata={"dedupe": stats},
        )
        return {"versionId": version.version_id, "dedupe": stats}

    def _handle_transform(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        parent, records = self._load_version_records(job.version_id)
        transforms = list(job.config.get("transforms") or [])
        out, lineage = apply_transforms(records, transforms)
        version = self._write_derived_version(
            dataset_id=job.dataset_id,
            parent=parent,
            label=f"xform-{parent.version_label}",
            kind=VersionKind.TRANSFORMED,
            records=out,
            lineage_extra=lineage,
        )
        return {"versionId": version.version_id, "lineage": lineage, "rowCount": version.row_count}

    def _handle_split(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        parent, records = self._load_version_records(job.version_id)
        out, summary = deterministic_split(
            records,
            seed=int(job.config.get("seed", 42)),
            train_ratio=float(job.config.get("trainRatio", 0.8)),
            val_ratio=float(job.config.get("valRatio", 0.1)),
            test_ratio=float(job.config.get("testRatio", 0.1)),
        )
        version = self._write_derived_version(
            dataset_id=job.dataset_id,
            parent=parent,
            label=f"split-{parent.version_label}",
            kind=VersionKind.SPLIT,
            records=out,
            split=summary,
            lineage_extra=[{"name": "deterministic_split", "params": summary, "appliedAt": utc_now()}],
        )
        return {"versionId": version.version_id, "split": summary}

    def _handle_tokenize_stats(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id
        ver, records = self._load_version_records(job.version_id)
        stats = compute_token_stats(records)
        self.store.update_version(ver.version_id, token_stats=stats)
        return stats

    def _handle_export(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        ver, records = self._load_version_records(job.version_id)
        split = job.config.get("split")
        dirs = self._dataset_dirs(job.dataset_id)
        name = f"export-{ver.version_id}" + (f"-{split}" if split else "") + ".jsonl"
        dest = dirs["exports"] / name
        result = export_jsonl(records, dest, split=split)
        export_version = self.store.create_version(
            dataset_id=job.dataset_id,
            version_label=f"export-{ver.version_label}",
            kind=VersionKind.EXPORT,
            parent_version_id=ver.version_id,
            status=VersionStatus.READY,
            storage_path=str(dest),
            schema=canonical_schema_dict(),
        )
        self.store.update_version(
            export_version.version_id,
            content_hash=result["contentHash"],
            byte_size=result["byteSize"],
            row_count=result["rowCount"],
        )
        result["versionId"] = export_version.version_id
        return result

    def _handle_index(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        if self.knowledge is None:
            raise DatasetError("KnowledgeStore not configured", code="no_knowledge", http_status=500)
        ver = self.get_version(job.version_id)
        if not ver.storage_path:
            raise DatasetError("Version has no storage", code="no_storage")
        scope = str(job.config.get("scope") or "dataset")
        max_records = job.config.get("maxRecords")
        offline_only = bool(job.config.get("offlineOnly"))
        source_fingerprint = job.config.get("sourceFingerprint")
        embedding_status = None
        embeddings = getattr(self.knowledge, "embeddings", None)
        if embeddings is not None and hasattr(embeddings, "status"):
            embedding_status = embeddings.status()
        if offline_only:
            from .offline import offline_index_preflight

            pf = offline_index_preflight(
                target_dir=self.corpus.datasets_manifests,
                source_size_bytes=int(ver.byte_size or 0),
                embedding_status=embedding_status,
                offline_only=True,
            )
            if not pf.ok:
                raise DatasetError(
                    "; ".join(pf.blockers),
                    code="OFFLINE_PREFLIGHT_BLOCKED",
                    http_status=409,
                )
        index = self.store.create_index(
            dataset_id=job.dataset_id,
            version_id=job.version_id,
            knowledge_scope=scope,
            status=IndexStatus.INDEXING,
        )
        try:
            outcome = index_version_file(
                self.knowledge,
                Path(ver.storage_path),
                dataset_id=job.dataset_id,
                version_id=job.version_id,
                scope=scope,
                max_records=int(max_records) if max_records is not None else None,
            )
            from .offline import build_projection_manifest
            from Data.modules.common.atomic import atomic_write_text

            manifest = build_projection_manifest(
                projection_id=index.index_id,
                dataset_id=job.dataset_id,
                version_id=job.version_id,
                source_fingerprint=str(source_fingerprint or ver.content_hash or ""),
                job_id=job.job_id,
                outcome=outcome,
                embedding_status=embedding_status,
                offline_only=offline_only,
            )
            manifest_path = self.corpus.datasets_manifests / f"brain-{index.index_id}.json"
            ensure_dir(manifest_path.parent)
            atomic_write_text(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            manifest["manifestPath"] = str(manifest_path)
            provenance = {**outcome, "manifest": manifest, "offlineOnly": offline_only}
            self.store.update_index(
                index.index_id,
                status=IndexStatus.READY,
                chunk_count=outcome["chunkCount"],
                provenance=provenance,
            )
            return {"indexId": index.index_id, **outcome, "manifest": manifest}
        except Exception as exc:
            self.store.update_index(
                index.index_id,
                status=IndexStatus.FAILED,
                provenance={"error": redact_secrets(str(exc))},
            )
            raise

    def list_hf_files(self, repository_id: str, *, revision: str = "main", token: str | None = None) -> list[dict[str, Any]]:
        return list_hf_dataset_files(repository_id, revision=revision, token=token)

    def public_job(self, job: DatasetJob) -> dict[str, Any]:
        """Redact secrets from job payload for API responses."""
        data = job.public_dict()
        data["error"] = redact_secrets(data["error"]) if data.get("error") else None
        # Ensure no token fields leak
        cfg = dict(data.get("config") or {})
        for key in list(cfg.keys()):
            if "token" in key.lower() or "secret" in key.lower() or "password" in key.lower() or "authorization" in key.lower():
                cfg[key] = "[REDACTED]"
        data["config"] = cfg
        if data.get("logPath"):
            data["logPath"] = redact_secrets(str(data["logPath"]))
        return data
