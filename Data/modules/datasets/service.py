"""DatasetService — import, materialize, transform, split, index orchestration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Data.modules.common.atomic import ensure_dir
from Data.modules.common.corpus import CorpusLayout, build_corpus_layout
from Data.modules.common.hashing import sha256_file
from Data.modules.common.paths import PathEscapeError, safe_join, safe_relpath
from Data.modules.common.secrets import redact_secrets
from Data.modules.knowledge import KnowledgeStore

from Data.backend.config import Settings, load_settings

if TYPE_CHECKING:
    from Data.modules.jobs.runtime import JobRuntime
    from Data.modules.jobs.types import JobRecord

from .annotation import AnnotationQueue
from .canonicalize import canonical_schema_dict
from .contamination import scan_contamination
from .dedupe import exact_dedupe
from .export import export_jsonl, preview_jsonl
from .formats import detect_format
from .huggingface import (
    HfDownloadCheckpoint,
    discover_hf_repository,
    download_hf_file,
    download_hf_repository,
    infer_config_from_path,
    infer_split_from_path,
    list_hf_dataset_files,
    load_repo_manifest,
    resolve_hf_token,
    safe_dest_path,
    write_repo_manifest,
)
from .importers import copy_immutable_raw, inspect_local_file, reject_traversal_components, resolve_import_path
from .indexing import index_version_file
from .jobs import DatasetJobRunner, enqueue_kernel_for_domain_job, kernel_idempotency_key
from .materialize import (
    load_materialized_jsonl,
    materialize_from_raw,
    materialize_from_sources,
    write_canonical_jsonl,
    write_manifest,
)
from .mixtures import MixtureComponent, build_mixture_manifest
from .packing_sim import simulate_packing
from .pii import scan_records_pii
from .shards import ShardIngestCheckpoint, build_shard_plan, ingest_shards
from .sidecar import (
    SIDECAR_FILENAME,
    build_sidecar_payload,
    find_sidecars_under_roots,
    read_sidecar,
    write_sidecar,
    write_tombstone,
)
from .splits import deterministic_split
from .store import DatasetStore, utc_now
from .tokenize_stats import compute_token_stats
from .transforms import apply_transforms
from .types import (
    CAPABILITY_PROCESS,
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

# Canonical file-backed kinds accepted by the JSONL indexer.
# RAW (including HF repository directories) is never indexable.
_INDEXABLE_VERSION_KINDS: tuple[VersionKind, ...] = (
    VersionKind.MATERIALIZED,
    VersionKind.TRANSFORMED,
    VersionKind.SPLIT,
    VersionKind.EXPORT,
)
# Preference when resolving RAW / directory-backed versions to an indexable sibling.
_INDEX_RESOLUTION_KIND_ORDER: tuple[VersionKind, ...] = (
    VersionKind.MATERIALIZED,
    VersionKind.TRANSFORMED,
    VersionKind.SPLIT,
)


def _elapsed_seconds(started_at: str | None, ended_at: str | None) -> float | None:
    if not started_at or not ended_at:
        return None
    try:
        from datetime import datetime

        def _parse(value: str) -> datetime:
            text = value.replace("Z", "+00:00")
            return datetime.fromisoformat(text)

        delta = _parse(ended_at) - _parse(started_at)
        return max(0.0, delta.total_seconds())
    except (TypeError, ValueError):
        return None


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
        job_runtime: JobRuntime | None = None,
    ) -> None:
        self.store = store
        self.corpus = corpus
        self.settings = settings or load_settings()
        self.knowledge = knowledge
        self.jobs = job_runtime
        self.allowed_import_roots = allowed_import_roots or [
            self.corpus.root,
            Path(self.settings.knowledge.data_root),
        ]
        self._hf_tokens: dict[str, str | None] = {}
        self.annotation_queue = AnnotationQueue()
        self.runner = DatasetJobRunner(
            store,
            self._build_handlers(),
            job_runtime=job_runtime,
        )
        # Hot-bindable; defaults from research_integration settings.
        self.datasets_auto_index_ready_to_knowledge = bool(
            getattr(
                getattr(self.settings, "research_integration", None),
                "datasets_auto_index_ready_to_knowledge",
                True,
            )
        )
        ri = getattr(self.settings, "research_integration", None)
        self.index_write_batch_size = max(
            1,
            int(getattr(ri, "dataset_index_batch_size", None) or 50),
        )
        self.max_relations_per_doc = max(
            1,
            int(getattr(ri, "dataset_max_relations_per_doc", None) or 24),
        )
        self.extract_relations_on_index = bool(
            getattr(ri, "dataset_extract_relations", True)
        )

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        *,
        db_path: Path | None = None,
        knowledge: KnowledgeStore | None = None,
        job_runtime: JobRuntime | None = None,
    ) -> "DatasetService":
        settings = settings or load_settings()
        path = db_path or Path(settings.database_path)
        store = DatasetStore(path)
        store.initialize()
        corpus = build_corpus_layout(settings)
        if knowledge is None:
            knowledge = KnowledgeStore(path, data_root=Path(settings.knowledge.data_root))
            knowledge.initialize()
        return cls(
            store,
            corpus=corpus,
            knowledge=knowledge,
            settings=settings,
            job_runtime=job_runtime,
        )

    def bind_job_runtime(self, job_runtime: JobRuntime | None) -> None:
        """Wire (or clear) the Job Kernel after construction — used by API boot."""
        self.jobs = job_runtime
        self.runner.jobs = job_runtime

    def _queue_domain_job(self, **kwargs: Any) -> DatasetJob:
        """Create domain dataset_jobs row and enqueue linked kernel job when available."""
        job = self.store.create_job(**kwargs)
        if job.status == DatasetJobStatus.QUEUED and self.jobs is not None:
            enqueue_kernel_for_domain_job(self.jobs, job)
        return job

    def _kernel_for_domain(self, domain_job_id: str) -> JobRecord | None:
        if self.jobs is None:
            return None
        try:
            return self.jobs.store.get_by_idempotency_key(kernel_idempotency_key(domain_job_id))
        except Exception:  # noqa: BLE001
            return None

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
            DatasetJobType.DUPLICATE.value: self._handle_duplicate,
            DatasetJobType.SHARD_INGEST.value: self._handle_shard_ingest,
            DatasetJobType.CONTAMINATION_SCAN.value: self._handle_contamination_scan,
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
        return self._queue_domain_job(
            job_type=DatasetJobType.IMPORT_LOCAL,
            dataset_id=ds.dataset_id,
            config={"path": path, "materialize": materialize},
        )

    def enqueue_import_hf(
        self,
        *,
        repository_id: str,
        filename: str | None = None,
        revision: str = "main",
        name: str | None = None,
        description: str = "",
        license: str | None = None,
        token: str | None = None,
        materialize: bool = True,
        dataset_id: str | None = None,
    ) -> DatasetJob:
        """Enqueue Hugging Face import.

        ``filename`` omitted/null → full repository import (preferred).
        ``filename`` set → legacy single-file import (backward compatible).
        """
        repo = repository_id.strip().strip("/")
        if not repo:
            raise DatasetError("repositoryId is required", code="invalid_request", http_status=400)
        legacy_file = (filename or "").strip() or None
        if legacy_file and ".." in Path(legacy_file.replace("\\", "/")).parts:
            raise DatasetError("Parent traversal refused", code="path_traversal", http_status=400)
        if dataset_id:
            ds = self.get_dataset(dataset_id)
        else:
            uri = (
                f"hf://datasets/{repo}@{revision}/{legacy_file}"
                if legacy_file
                else f"hf://datasets/{repo}@{revision}"
            )
            ds = self.store.create_dataset(
                name=name or (f"{repo}/{legacy_file}" if legacy_file else repo),
                source_type=SourceType.HUGGINGFACE,
                description=description,
                license=license,
                original_uri=uri,
                original_filename=Path(legacy_file).name if legacy_file else None,
                status=DatasetStatus.IMPORTING,
                provenance={
                    "repositoryId": repo,
                    "revision": revision,
                    **({"filename": legacy_file} if legacy_file else {"mode": "repository"}),
                },
            )
        # Never persist raw token in config
        safe_config: dict[str, Any] = {
            "repositoryId": repo,
            "revision": revision,
            "materialize": materialize,
            "hasToken": bool(token) or bool(resolve_hf_token(None)),
            "mode": "file" if legacy_file else "repository",
        }
        if legacy_file:
            safe_config["filename"] = legacy_file
        job = self._queue_domain_job(
            job_type=DatasetJobType.IMPORT_HF,
            dataset_id=ds.dataset_id,
            config=safe_config,
        )
        # Keep token only in-memory via ephemeral map keyed by job id
        self._hf_tokens[job.job_id] = token
        return job

    def enqueue_materialize(self, dataset_id: str, *, fmt: str | None = None) -> DatasetJob:
        self.get_dataset(dataset_id)
        return self._queue_domain_job(
            job_type=DatasetJobType.MATERIALIZE,
            dataset_id=dataset_id,
            config={"format": fmt},
        )

    def enqueue_validate(self, dataset_id: str, version_id: str) -> DatasetJob:
        self.get_dataset(dataset_id)
        self.get_version(version_id)
        return self._queue_domain_job(
            job_type=DatasetJobType.VALIDATE,
            dataset_id=dataset_id,
            version_id=version_id,
            config={},
        )

    def enqueue_dedupe(self, dataset_id: str, version_id: str) -> DatasetJob:
        self.get_dataset(dataset_id)
        self.get_version(version_id)
        return self._queue_domain_job(
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
        return self._queue_domain_job(
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
        return self._queue_domain_job(
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
        return self._queue_domain_job(
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
        return self._queue_domain_job(
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
        rebuild: bool = False,
    ) -> DatasetJob:
        # Early routing validation — worker re-resolves before indexing.
        resolved = self._resolve_indexable_version(dataset_id, version_id)
        return self._queue_domain_job(
            job_type=DatasetJobType.INDEX,
            dataset_id=dataset_id,
            version_id=resolved.version_id,
            config={
                "scope": scope,
                "maxRecords": max_records,
                "offlineOnly": offline_only,
                "sourceFingerprint": source_fingerprint,
                "rebuild": rebuild,
                "requestedVersionId": version_id,
                "resolvedVersionId": resolved.version_id,
            },
        )

    def _data_root(self) -> Path:
        return Path(self.settings.knowledge.data_root)

    def _discovery_skip_paths(self) -> list[Path]:
        """Derived trees that must not be re-registered as source datasets."""
        return [
            self.corpus.datasets_materialized,
            self.corpus.datasets_processed,
            self.corpus.datasets_exports,
            self.corpus.datasets_manifests,
            self.corpus.training,
            self.corpus.research,
            self.corpus.models_artifacts,
            self.corpus.models_cache,
        ]

    def discover_offline_sources(self, *, max_files: int = 500) -> dict[str, Any]:
        from .offline import build_discovery_roots, discover_under_roots

        data_root = self._data_root()
        roots = build_discovery_roots(
            data_root=data_root,
            corpus_root=self.corpus.root,
            datasets_raw=self.corpus.datasets_raw,
            hf_cache=self.corpus.hf_cache,
        )
        sources = discover_under_roots(
            roots,
            max_files=max_files,
            follow_symlinks=False,
            skip_under=self._discovery_skip_paths(),
        )
        return {
            "roots": [{"id": rid, "path": str(path)} for rid, path in roots],
            "sources": [s.public_dict() for s in sources],
            "count": len(sources),
            "dataRoot": str(data_root),
            "truth": {
                "explicit_allowed_roots_only": True,
                "no_full_filesystem_scan": True,
                "local_dataset_is_not_learned_knowledge": True,
                "no_copy_on_discover": True,
            },
        }

    def _path_keys_for_dataset(self, ds: DatasetRecord) -> set[str]:
        from Data.modules.common.paths import normalize_path_key

        keys: set[str] = set()
        for candidate in (
            ds.raw_path,
            ds.original_uri,
            (ds.provenance or {}).get("sourcePath"),
            (ds.provenance or {}).get("canonicalPath"),
            (ds.metadata or {}).get("sourcePath"),
        ):
            if candidate:
                keys.add(normalize_path_key(str(candidate)))
        for ver in self.store.list_versions(ds.dataset_id):
            if ver.kind == VersionKind.RAW and ver.storage_path:
                keys.add(normalize_path_key(ver.storage_path))
        return {k for k in keys if k}

    def _find_dataset_by_path_key(self, path_key: str) -> DatasetRecord | None:
        if not path_key:
            return None
        for ds in self.store.list_datasets(limit=500):
            if path_key in self._path_keys_for_dataset(ds):
                return ds
        return None

    def _register_discovered_source(self, source: dict[str, Any]) -> tuple[DatasetRecord, bool]:
        """Register a discovered filesystem source without copying bytes.

        Returns ``(dataset, created)``. Idempotent on normalized path key.
        """
        from Data.modules.common.paths import normalize_path_key

        path_str = str(source.get("path") or "")
        path_key = str(source.get("pathKey") or normalize_path_key(path_str))
        existing = self._find_dataset_by_path_key(path_key)
        path = Path(path_str)
        source_missing = not path.exists()
        kind = str(source.get("kind") or "file")
        display = str(source.get("displayName") or path.stem or path.name or "discovered")
        fmt_name = source.get("format")
        fmt = None
        if fmt_name:
            try:
                fmt = DetectedFormat(str(fmt_name))
            except ValueError:
                fmt = DetectedFormat.UNKNOWN
        size = int(source.get("sizeBytes") or 0) or None
        hf_repo = source.get("hfRepoId")
        provenance = {
            "sourcePath": path_str,
            "canonicalPath": path_str,
            "pathKey": path_key,
            "discovered": True,
            "discoveryRootId": source.get("rootId"),
            "discoveryKind": kind,
            "fingerprint": source.get("fingerprint"),
            "hfRepoId": hf_repo,
            "noCopy": True,
        }
        metadata = {
            "sourcePath": path_str,
            "pathKey": path_key,
            "discovered": True,
            "fileCount": source.get("fileCount"),
            "sourceMissing": source_missing,
            "hfRepoId": hf_repo,
        }

        if existing is not None:
            meta = dict(existing.metadata or {})
            meta.update({k: v for k, v in metadata.items() if v is not None})
            prov = dict(existing.provenance or {})
            prov.update({k: v for k, v in provenance.items() if v is not None})
            updates: dict[str, Any] = {
                "metadata": meta,
                "provenance": prov,
            }
            if size is not None:
                updates["byte_size"] = size
            if fmt is not None and existing.detected_format is None:
                updates["detected_format"] = fmt
            if existing.raw_path is None and not source_missing:
                updates["raw_path"] = path_str
            if hf_repo and not existing.original_uri:
                updates["original_uri"] = f"hf://{hf_repo}"
            self.store.update_dataset(existing.dataset_id, **updates)
            # Ensure a RAW version referencing the source exists.
            versions = self.store.list_versions(existing.dataset_id)
            has_raw = any(
                v.kind == VersionKind.RAW
                and v.storage_path
                and normalize_path_key(v.storage_path) == path_key
                for v in versions
            )
            if not has_raw and not source_missing:
                ver = self.store.create_version(
                    dataset_id=existing.dataset_id,
                    version_label="raw-discovered",
                    kind=VersionKind.RAW,
                    status=VersionStatus.READY,
                    storage_path=path_str,
                    schema={"type": "raw", "format": (fmt or DetectedFormat.UNKNOWN).value, "discovered": True},
                    metadata={"pathKey": path_key, "noCopy": True},
                )
                if size is not None:
                    self.store.update_version(ver.version_id, byte_size=size)
            try:
                self.write_dataset_sidecar(existing.dataset_id)
            except Exception:  # noqa: BLE001
                pass
            return self.get_dataset(existing.dataset_id), False

        source_type = SourceType.HUGGINGFACE if hf_repo or kind == "hf_cache" else SourceType.LOCAL
        ds = self.store.create_dataset(
            name=self._unique_dataset_name(display),
            source_type=source_type,
            description="Discovered under configured ModelData root (no copy).",
            original_filename=path.name if kind == "file" else None,
            original_uri=f"hf://{hf_repo}" if hf_repo else path_str,
            provenance=provenance,
            metadata=metadata,
            status=DatasetStatus.RAW if not source_missing else DatasetStatus.CREATED,
        )
        self.store.update_dataset(
            ds.dataset_id,
            raw_path=path_str if not source_missing else None,
            byte_size=size,
            detected_format=fmt,
            format_confidence=0.7 if fmt and fmt != DetectedFormat.UNKNOWN else None,
        )
        if not source_missing:
            ver = self.store.create_version(
                dataset_id=ds.dataset_id,
                version_label="raw-discovered",
                kind=VersionKind.RAW,
                status=VersionStatus.READY,
                storage_path=path_str,
                schema={"type": "raw", "format": (fmt or DetectedFormat.UNKNOWN).value, "discovered": True},
                metadata={"pathKey": path_key, "noCopy": True},
            )
            if size is not None:
                self.store.update_version(ver.version_id, byte_size=size)
        try:
            self.write_dataset_sidecar(ds.dataset_id)
        except Exception:  # noqa: BLE001
            pass
        return self.get_dataset(ds.dataset_id), True

    def refresh_dataset_library(self, *, max_files: int = 500) -> dict[str, Any]:
        """Scan configured roots, register missing datasets, refresh cheap metadata.

        Does not copy source bytes. Does not delete Brain knowledge. Marks
        registered datasets whose source path is gone as ``sourceMissing``.
        """
        from Data.modules.common.paths import normalize_path_key

        discovery = self.discover_offline_sources(max_files=max_files)
        created = 0
        updated = 0
        registered_ids: list[str] = []
        seen_keys: set[str] = set()
        for raw in discovery["sources"]:
            if raw.get("error") or not raw.get("readable", True):
                continue
            path_key = str(raw.get("pathKey") or normalize_path_key(str(raw.get("path") or "")))
            if not path_key or path_key in seen_keys:
                continue
            seen_keys.add(path_key)
            ds, was_created = self._register_discovered_source(raw)
            registered_ids.append(ds.dataset_id)
            if was_created:
                created += 1
            else:
                updated += 1

        # Non-destructive: flag missing sources on previously registered datasets.
        missing = 0
        for ds in self.store.list_datasets(limit=500):
            meta = dict(ds.metadata or {})
            path_candidates = [
                ds.raw_path,
                (ds.provenance or {}).get("sourcePath"),
                (ds.provenance or {}).get("canonicalPath"),
            ]
            source_path = next((p for p in path_candidates if p), None)
            if not source_path:
                continue
            if not Path(str(source_path)).exists():
                if not meta.get("sourceMissing"):
                    meta["sourceMissing"] = True
                    self.store.update_dataset(ds.dataset_id, metadata=meta)
                    missing += 1
            elif meta.get("sourceMissing"):
                meta["sourceMissing"] = False
                self.store.update_dataset(ds.dataset_id, metadata=meta)

        datasets = [self.brain_library_entry(d) for d in self.store.list_datasets(limit=500)]
        return {
            "created": created,
            "updated": updated,
            "missingSources": missing,
            "discovered": discovery["count"],
            "registeredDatasetIds": registered_ids,
            "roots": discovery["roots"],
            "dataRoot": discovery.get("dataRoot"),
            "datasets": datasets,
            "truth": {
                "idempotent": True,
                "no_copy_on_discover": True,
                "no_brain_delete_on_refresh": True,
                "local_dataset_is_not_learned_knowledge": True,
            },
        }

    def brain_status_for_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Map existing index/job state into Brain-ingestion truth for the UI."""
        indexes = self.store.list_indexes(dataset_id)
        ready = [i for i in indexes if i.status == IndexStatus.READY]
        indexing = [i for i in indexes if i.status == IndexStatus.INDEXING]
        failed = [i for i in indexes if i.status == IndexStatus.FAILED]
        active_jobs = [
            j
            for j in self.store.list_jobs(dataset_id=dataset_id, limit=40)
            if j.job_type == DatasetJobType.INDEX
            and j.status in {DatasetJobStatus.QUEUED, DatasetJobStatus.RUNNING}
        ]
        ds = self.get_dataset(dataset_id)
        source_missing = bool((ds.metadata or {}).get("sourceMissing"))
        ladder = self.learning_ladder_for_dataset(dataset_id)
        # READY Brain index is authoritative — a queued auto-index must not hide it.
        if ready and not any(
            bool((j.config or {}).get("rebuild")) and j.status == DatasetJobStatus.RUNNING
            for j in active_jobs
        ):
            idx = sorted(ready, key=lambda i: i.updated_at or "", reverse=True)[0]
            prov = idx.provenance or {}
            return {
                "brainStatus": "learned",
                "label": "Geleerd",
                "indexId": idx.index_id,
                "chunkCount": idx.chunk_count,
                "documentCount": prov.get("documentCount"),
                "jobId": None,
                "progress": 1.0,
                "phase": "ready",
                "updatedAt": idx.updated_at,
                "sourceMissing": source_missing,
                "learned": True,
                "versionId": idx.version_id,
                "embeddingMode": prov.get("embeddingMode"),
                "embeddingsSemantic": prov.get("embeddingsSemantic"),
                "relationsAccepted": prov.get("relationsAccepted"),
                "relationsRejected": prov.get("relationsRejected"),
                "learning": ladder,
            }
        if active_jobs:
            job = active_jobs[0]
            status = "queued" if job.status == DatasetJobStatus.QUEUED else "indexing"
            checkpoint = dict(job.checkpoint or {})
            return {
                "brainStatus": status,
                "label": "In wachtrij" if status == "queued" else "Bezig met leren",
                "indexId": None,
                "chunkCount": checkpoint.get("chunkCount"),
                "documentCount": checkpoint.get("indexed"),
                "jobId": job.job_id,
                "progress": job.progress,
                "phase": job.phase,
                "updatedAt": job.updated_at,
                "sourceMissing": source_missing,
                "learned": False,
                "embeddingMode": checkpoint.get("embeddingMode"),
                "embeddingsSemantic": checkpoint.get("embeddingsSemantic"),
                "relationsAccepted": checkpoint.get("relationsAccepted"),
                "relationsRejected": checkpoint.get("relationsRejected"),
                "processed": checkpoint.get("processed"),
                "learning": ladder,
            }
        if indexing:
            idx = indexing[0]
            return {
                "brainStatus": "indexing",
                "label": "Bezig met leren",
                "indexId": idx.index_id,
                "chunkCount": idx.chunk_count,
                "documentCount": (idx.provenance or {}).get("documentCount"),
                "jobId": None,
                "progress": None,
                "phase": "indexing",
                "updatedAt": idx.updated_at,
                "sourceMissing": source_missing,
                "learned": False,
                "learning": ladder,
            }
        if failed and not ready:
            idx = sorted(failed, key=lambda i: i.updated_at or "", reverse=True)[0]
            return {
                "brainStatus": "failed",
                "label": "Leren mislukt",
                "indexId": idx.index_id,
                "chunkCount": idx.chunk_count,
                "documentCount": (idx.provenance or {}).get("documentCount"),
                "jobId": None,
                "progress": None,
                "phase": "failed",
                "updatedAt": idx.updated_at,
                "sourceMissing": source_missing,
                "learned": False,
                "error": (idx.provenance or {}).get("error"),
                "learning": ladder,
            }
        return {
            "brainStatus": "not_learned",
            "label": "Nog niet geleerd",
            "indexId": None,
            "chunkCount": None,
            "documentCount": None,
            "jobId": None,
            "progress": None,
            "phase": None,
            "updatedAt": None,
            "sourceMissing": source_missing,
            "learned": False,
            "learning": ladder,
        }

    def brain_library_entry(self, ds: DatasetRecord) -> dict[str, Any]:
        entry = ds.public_dict()
        brain = self.brain_status_for_dataset(ds.dataset_id)
        entry["brain"] = brain
        entry["brainStatus"] = brain["brainStatus"]
        entry["learned"] = brain["learned"]
        entry["sourceMissing"] = brain["sourceMissing"]
        return entry

    def list_library_datasets(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [self.brain_library_entry(d) for d in self.store.list_datasets(limit=limit)]

    def list_learned_datasets(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Datasets with verified READY Brain indexes (Dataset Offline semantics)."""
        out: list[dict[str, Any]] = []
        for ds in self.store.list_datasets(limit=500):
            brain = self.brain_status_for_dataset(ds.dataset_id)
            if not brain.get("learned"):
                continue
            entry = self.brain_library_entry(ds)
            # Attach richest ready index metadata.
            indexes = [
                i.public_dict()
                for i in self.store.list_indexes(ds.dataset_id)
                if i.status == IndexStatus.READY
            ]
            indexes.sort(key=lambda i: i.get("updatedAt") or "", reverse=True)
            entry["indexes"] = indexes
            out.append(entry)
            if len(out) >= limit:
                break
        return out

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
            embeddings = getattr(self.knowledge, "embedding_provider", None)
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
                payload = idx.public_dict()
                payload["datasetName"] = ds.name
                payload["learned"] = idx.status == IndexStatus.READY
                out.append(payload)
                if len(out) >= limit:
                    return out
        return out

    def enqueue_learn_to_brain(
        self,
        dataset_id: str,
        version_id: str | None = None,
        *,
        scope: str = "dataset",
        max_records: int | None = None,
        source_fingerprint: str | None = None,
        rebuild: bool = False,
        offline_only: bool = True,
    ) -> DatasetJob:
        """Start Brain ingestion (Kennis leren) via the existing Knowledge index path.

        Materializes RAW sources when needed (derived JSONL only — no source copy).
        Idempotent when a READY index already exists unless ``rebuild=True``.
        """
        ds = self.get_dataset(dataset_id)
        if (ds.metadata or {}).get("sourceMissing"):
            raise DatasetError(
                "Dataset source path is missing on disk",
                code="source_missing",
                http_status=409,
            )
        ver = self.pick_usable_version(dataset_id, version_id=version_id)
        if ver is None:
            raise DatasetError(
                "Dataset has no version to learn from",
                code="no_version",
                http_status=409,
            )
        # Block duplicate concurrent learn jobs (not auto-index companions).
        for job in self.store.list_jobs(dataset_id=dataset_id, limit=40):
            if (
                job.job_type == DatasetJobType.INDEX
                and job.status in {DatasetJobStatus.QUEUED, DatasetJobStatus.RUNNING}
                and bool((job.config or {}).get("learnToBrain"))
            ):
                raise DatasetError(
                    "Brain ingestion already in progress for this dataset",
                    code="learn_in_progress",
                    http_status=409,
                    details={"jobId": job.job_id},
                )
        if not rebuild:
            brain = self.brain_status_for_dataset(dataset_id)
            if brain.get("learned"):
                raise DatasetError(
                    "Dataset is already learned into Brain; use rebuild/opnieuw leren to reindex",
                    code="already_learned",
                    http_status=409,
                    details={
                        "indexId": brain.get("indexId"),
                        "brainStatus": brain.get("brainStatus"),
                    },
                )
        if offline_only:
            pf = self.offline_brain_preflight(dataset_id, ver.version_id, offline_only=True)
            if not pf.get("ok"):
                raise DatasetError(
                    "; ".join(pf.get("blockers") or ["offline preflight blocked"]),
                    code="OFFLINE_PREFLIGHT_BLOCKED",
                    http_status=409,
                )
        # Prefer an already-indexable sibling when resolving; else ensure materialize.
        ensure_materialized = not self._is_directly_indexable(ver)
        if ensure_materialized:
            sibling = self._pick_indexable_sibling(dataset_id)
            if sibling is not None:
                ver = sibling
                ensure_materialized = False
        return self._queue_domain_job(
            job_type=DatasetJobType.INDEX,
            dataset_id=dataset_id,
            version_id=ver.version_id,
            config={
                "scope": scope,
                "maxRecords": max_records,
                "offlineOnly": offline_only,
                "sourceFingerprint": source_fingerprint,
                "rebuild": rebuild,
                "requestedVersionId": ver.version_id,
                "ensureMaterialized": ensure_materialized,
                "learnToBrain": True,
            },
        )

    def enqueue_offline_brain_index(
        self,
        dataset_id: str,
        version_id: str,
        *,
        scope: str = "dataset",
        max_records: int | None = None,
        source_fingerprint: str | None = None,
        rebuild: bool = False,
    ) -> DatasetJob:
        """Compatibility wrapper — Brain index is Kennis leren (no separate offline copy)."""
        return self.enqueue_learn_to_brain(
            dataset_id,
            version_id,
            scope=scope,
            max_records=max_records,
            source_fingerprint=source_fingerprint,
            rebuild=rebuild,
            offline_only=True,
        )

    def _unique_dataset_name(self, base: str) -> str:
        """Return a collision-safe dataset name starting from ``base``."""
        name = (base or "untitled").strip() or "untitled"
        existing = {ds.name for ds in self.store.list_datasets(limit=500)}
        if name not in existing:
            return name
        for i in range(2, 10_000):
            candidate = f"{name} ({i})"
            if candidate not in existing:
                return candidate
        raise DatasetError("Unable to allocate unique dataset name", code="name_collision", http_status=409)

    def pick_usable_version(
        self,
        dataset_id: str,
        *,
        version_id: str | None = None,
    ) -> DatasetVersion | None:
        """Prefer an explicit version, else ready materialized, else any ready version."""
        self.get_dataset(dataset_id)
        if version_id:
            ver = self.get_version(version_id)
            if ver.dataset_id != dataset_id:
                raise DatasetError(
                    "Version does not belong to dataset",
                    code="version_mismatch",
                    http_status=400,
                )
            return ver
        versions = self.list_versions(dataset_id)
        ready = [v for v in versions if v.status == VersionStatus.READY]
        for kind in (VersionKind.MATERIALIZED, VersionKind.TRANSFORMED, VersionKind.SPLIT, VersionKind.RAW):
            for ver in ready:
                if ver.kind == kind and ver.storage_path:
                    return ver
        for ver in ready:
            if ver.storage_path:
                return ver
        return versions[0] if versions else None

    def _storage_is_indexable_file(self, storage_path: str | None) -> bool:
        if not storage_path:
            return False
        path = Path(storage_path)
        return path.is_file()

    def _is_directly_indexable(self, ver: DatasetVersion) -> bool:
        """True when a version can be passed straight to the JSONL indexer."""
        if ver.status != VersionStatus.READY:
            return False
        if ver.kind == VersionKind.RAW:
            return False
        if ver.kind not in _INDEXABLE_VERSION_KINDS:
            return False
        return self._storage_is_indexable_file(ver.storage_path)

    def _pick_indexable_sibling(
        self,
        dataset_id: str,
        *,
        exclude_version_id: str | None = None,
    ) -> DatasetVersion | None:
        """Deterministic READY file-backed sibling by preferred kind, then created_at DESC."""
        # list_versions is ORDER BY created_at DESC — first match per kind is newest.
        ready = [
            v
            for v in self.list_versions(dataset_id)
            if v.status == VersionStatus.READY
            and v.version_id != exclude_version_id
            and v.kind in _INDEX_RESOLUTION_KIND_ORDER
            and self._storage_is_indexable_file(v.storage_path)
        ]
        for kind in _INDEX_RESOLUTION_KIND_ORDER:
            for ver in ready:
                if ver.kind == kind:
                    return ver
        return None

    def _resolve_indexable_version(
        self,
        dataset_id: str,
        version_id: str,
    ) -> DatasetVersion:
        """Resolve a request to one authoritative file-backed indexable version.

        RAW and directory-backed storage must never reach ``index_version_file``.
        """
        self.get_dataset(dataset_id)
        ver = self.get_version(version_id)
        if ver.dataset_id != dataset_id:
            raise DatasetError(
                "Version does not belong to dataset",
                code="version_mismatch",
                http_status=400,
            )

        if self._is_directly_indexable(ver):
            return ver

        # RAW, directory-backed, missing/non-file storage, or unsuitable kind:
        # attempt sibling resolution before failing.
        sibling = self._pick_indexable_sibling(
            dataset_id,
            exclude_version_id=ver.version_id if ver.kind == VersionKind.RAW else None,
        )
        # When a supposedly canonical version points at a directory, prefer another
        # valid sibling of the same dataset; do not treat the directory as JSONL.
        if sibling is not None:
            return sibling
        if ver.kind == VersionKind.RAW or (ver.storage_path and Path(ver.storage_path).is_dir()):
            raise DatasetError(
                "Dataset has no indexable materialized version. "
                "Materialize the dataset before indexing.",
                code="no_indexable_version",
                http_status=409,
            )

        if not ver.storage_path:
            raise DatasetError(
                "Version has no storage path",
                code="no_storage",
                http_status=400,
            )
        path = Path(ver.storage_path)
        if not path.exists():
            raise DatasetError(
                f"Version storage path does not exist: {path}",
                code="storage_missing",
                http_status=400,
            )
        if not path.is_file():
            raise DatasetError(
                f"Version storage path is not a file: {path}",
                code="storage_not_file",
                http_status=400,
            )
        if ver.status != VersionStatus.READY:
            raise DatasetError(
                f"Version is not ready for indexing (status={ver.status.value})",
                code="version_not_ready",
                http_status=409,
            )
        if ver.kind not in _INDEXABLE_VERSION_KINDS:
            raise DatasetError(
                "Dataset has no indexable materialized version. "
                "Materialize the dataset before indexing.",
                code="no_indexable_version",
                http_status=409,
            )
        return ver

    def enqueue_duplicate(
        self,
        dataset_id: str,
        *,
        version_id: str | None = None,
        name: str | None = None,
    ) -> DatasetJob:
        """Enqueue durable duplication of a dataset into independent storage."""
        source = self.get_dataset(dataset_id)
        source_version = self.pick_usable_version(dataset_id, version_id=version_id)
        if version_id and source_version is None:
            raise DatasetError("Version not found", code="not_found", http_status=404)

        base_name = (name or f"{source.name} copy").strip() or f"{source.name} copy"
        unique_name = self._unique_dataset_name(base_name)
        empty = source_version is None or not source_version.storage_path
        target = self.store.create_dataset(
            name=unique_name,
            source_type=SourceType.DERIVED,
            description=source.description,
            license=source.license,
            metadata=dict(source.metadata or {}),
            provenance={
                "duplicatedFromDatasetId": source.dataset_id,
                "duplicatedFromVersionId": source_version.version_id if source_version else None,
                "sourceContentHash": source.content_hash,
                "sourceName": source.name,
            },
            status=DatasetStatus.CREATED if empty else DatasetStatus.IMPORTING,
            original_filename=source.original_filename,
            original_uri=source.original_uri,
        )
        if source.detected_format is not None or source.format_confidence is not None:
            self.store.update_dataset(
                target.dataset_id,
                detected_format=source.detected_format,
                format_confidence=source.format_confidence,
            )
        return self._queue_domain_job(
            job_type=DatasetJobType.DUPLICATE,
            dataset_id=target.dataset_id,
            version_id=None,
            config={
                "sourceDatasetId": source.dataset_id,
                "sourceVersionId": source_version.version_id if source_version else None,
                "targetDatasetId": target.dataset_id,
                "empty": empty,
            },
        )

    def resolve_export_download(self, dataset_id: str, version_id: str) -> Path:
        """Resolve a downloadable export artifact path under canonical exports storage."""
        self.get_dataset(dataset_id)
        ver = self.get_version(version_id)
        if ver.dataset_id != dataset_id:
            raise DatasetError(
                "Version does not belong to dataset",
                code="version_mismatch",
                http_status=400,
            )
        if ver.kind != VersionKind.EXPORT:
            raise DatasetError(
                "Version is not an export artifact",
                code="not_export",
                http_status=400,
            )
        if not ver.storage_path:
            raise DatasetError("Export artifact path missing", code="no_storage", http_status=404)
        path = Path(ver.storage_path).resolve()
        root = (self.corpus.datasets_exports / dataset_id).resolve()
        try:
            safe_relpath(root, path)
        except PathEscapeError as exc:
            raise DatasetError(
                "Export path escapes canonical exports storage",
                code="path_traversal",
                http_status=400,
            ) from exc
        if not path.is_file():
            raise DatasetError("Export artifact not found", code="not_found", http_status=404)
        return path

    def cancel_job(self, job_id: str) -> DatasetJob:
        self.get_job(job_id)
        cancelled = self.store.request_cancel(job_id)
        kernel = self._kernel_for_domain(job_id)
        if kernel is not None and self.jobs is not None:
            try:
                from Data.modules.jobs.states import TERMINAL_JOB_STATES

                if kernel.state not in TERMINAL_JOB_STATES:
                    self.jobs.cancel(kernel.job_id, reason="dataset domain cancel")
            except Exception:  # noqa: BLE001
                pass
        return cancelled

    def process_jobs(self, *, max_jobs: int = 50) -> list[DatasetJob]:
        return self.runner.drain(max_jobs=max_jobs)

    def process_kernel_job(self, kernel_job_id: str) -> DatasetJob | None:
        """Execute a specific kernel job already claimed by a pool worker."""
        if self.jobs is None:
            return None
        kernel = self.jobs.store.get(kernel_job_id)
        if kernel is None:
            return None
        return self.runner.process_kernel_job(kernel)

    def reconcile(self) -> list[DatasetJob]:
        updated = self.runner.reconcile_interrupted()
        try:
            self.reconcile_sidecars()
        except Exception:  # noqa: BLE001 — catalog recovery must not block job reconcile
            pass
        # Backfill sidecars for existing catalog rows (idempotent).
        try:
            for ds in self.store.list_datasets(limit=200):
                try:
                    self.write_dataset_sidecar(ds.dataset_id)
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        return updated

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

    def _sidecar_directory_for(self, ds: DatasetRecord) -> Path:
        """Always place sidecars under corpus ``raw/{dataset_id}`` (never next to sources).

        Keeps recovery files inside the managed corpus so discovery under
        ``data_root`` cannot treat ``.leviathan-dataset.json`` as a new dataset.
        """
        return self._dataset_dirs(ds.dataset_id)["raw"]

    def write_dataset_sidecar(self, dataset_id: str) -> Path | None:
        """Persist durable identity sidecar for an existing catalog record."""
        ds = self.get_dataset(dataset_id)
        versions = self.store.list_versions(dataset_id)
        preferred = None
        for ver in versions:
            if ver.kind == VersionKind.MATERIALIZED and ver.status == VersionStatus.READY:
                preferred = ver
                break
        if preferred is None and versions:
            preferred = versions[0]
        directory = self._sidecar_directory_for(ds)
        payload = build_sidecar_payload(
            dataset_id=ds.dataset_id,
            name=ds.name,
            source_type=ds.source_type.value if ds.source_type else None,
            content_hash=ds.content_hash,
            original_uri=ds.original_uri,
            original_filename=ds.original_filename,
            raw_path=ds.raw_path,
            version_id=preferred.version_id if preferred else None,
            version_label=preferred.version_label if preferred else None,
            detected_format=ds.detected_format.value if ds.detected_format else None,
            row_count=ds.row_count,
            byte_size=ds.byte_size,
            provenance=ds.provenance,
            created_at=ds.created_at,
            updated_at=ds.updated_at,
        )
        return write_sidecar(directory, payload)

    def learning_ladder_for_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Honest capability ladder: disk file ≠ learned knowledge."""
        ds = self.get_dataset(dataset_id)
        files = self.store.list_files(dataset_id)
        versions = self.store.list_versions(dataset_id)
        indexes = self.store.list_indexes(dataset_id)
        ready_indexes = [i for i in indexes if i.status == IndexStatus.READY]
        source_path = Path(ds.raw_path) if ds.raw_path else None
        files_discovered = bool(
            (source_path and source_path.exists())
            or any(Path(f.path).exists() for f in files if f.path)
            or bool((ds.metadata or {}).get("discovered"))
        )
        in_catalog = True
        indexed = bool(ready_indexes)
        embeddings_available = False
        embeddings_semantic = False
        relations_verified = False
        brain_searchable = False
        relation_count = 0
        if ready_indexes:
            prov = ready_indexes[0].provenance or {}
            emb = prov.get("embeddings") if isinstance(prov.get("embeddings"), dict) else {}
            embeddings_available = bool(
                prov.get("embeddingsAvailable")
                or emb.get("available")
                or (prov.get("embeddingMode") not in {None, "lexical_only"})
            )
            embeddings_semantic = bool(prov.get("embeddingsSemantic") or emb.get("is_semantic"))
            relation_count = int(prov.get("relationsAccepted") or 0)
            relations_verified = relation_count > 0 or bool(prov.get("relationsVerified"))
            brain_searchable = indexed and int(prov.get("documentCount") or prov.get("chunkCount") or 0) > 0
        sidecar_dir = self._sidecar_directory_for(ds)
        sidecar = read_sidecar(sidecar_dir / SIDECAR_FILENAME)
        return {
            "filesDiscovered": files_discovered,
            "inCatalog": in_catalog,
            "sidecarPresent": sidecar is not None,
            "indexed": indexed,
            "embeddingsAvailable": embeddings_available,
            "embeddingsSemantic": embeddings_semantic,
            "relationsVerified": relations_verified,
            "relationCount": relation_count,
            "brainSearchable": brain_searchable,
            "sourceMissing": bool((ds.metadata or {}).get("sourceMissing")),
            "versionCount": len(versions),
            "truth": {
                "file_on_disk_is_not_learned_knowledge": True,
                "learned_requires_ready_index": True,
                "non_semantic_fallback_is_not_semantic_embedding": not embeddings_semantic,
            },
        }

    def learning_activity(self, *, limit: int = 40) -> dict[str, Any]:
        """Live Dataset Learning activity for Agents page — real jobs only."""
        jobs = self.store.list_jobs(limit=max(1, min(int(limit), 200)))
        index_jobs = [j for j in jobs if j.job_type == DatasetJobType.INDEX]
        active = [
            j
            for j in index_jobs
            if j.status in {DatasetJobStatus.QUEUED, DatasetJobStatus.RUNNING}
        ]
        recent = index_jobs[:limit]

        def _enrich(job: DatasetJob) -> dict[str, Any]:
            payload = self.public_job(job)
            ds_name = None
            ladder = None
            if job.dataset_id:
                try:
                    ds_name = self.get_dataset(job.dataset_id).name
                    ladder = self.learning_ladder_for_dataset(job.dataset_id)
                except DatasetError:
                    ds_name = None
            checkpoint = dict(job.checkpoint or {})
            result = dict(job.result or {})
            payload["datasetName"] = ds_name
            payload["learning"] = ladder
            payload["activity"] = {
                "datasetId": job.dataset_id,
                "datasetName": ds_name,
                "jobId": job.job_id,
                "phase": job.phase,
                "progress": job.progress,
                "status": job.status.value,
                "processed": checkpoint.get("processed") or result.get("processedCount"),
                "indexed": checkpoint.get("indexed") or result.get("indexedCount"),
                "chunkCount": checkpoint.get("chunkCount") or result.get("chunkCount"),
                "relationsAccepted": checkpoint.get("relationsAccepted")
                or result.get("relationsAccepted"),
                "relationsRejected": checkpoint.get("relationsRejected")
                or result.get("relationsRejected"),
                "embeddingMode": checkpoint.get("embeddingMode") or result.get("embeddingMode"),
                "embeddingsSemantic": checkpoint.get("embeddingsSemantic")
                if "embeddingsSemantic" in checkpoint
                else result.get("embeddingsSemantic"),
                "lastRecordId": checkpoint.get("lastRecordId") or result.get("lastRecordId"),
                "updatedAt": job.updated_at,
                "startedAt": job.started_at,
                "finishedAt": job.finished_at,
                "error": payload.get("error"),
                "blocked": bool(job.cancel_requested)
                or job.status == DatasetJobStatus.INTERRUPTED
                or (
                    isinstance(payload.get("error"), str)
                    and "blocked" in str(payload.get("error")).lower()
                ),
                "elapsedSeconds": _elapsed_seconds(job.started_at, job.finished_at or job.updated_at),
            }
            return payload

        return {
            "agentSystemKey": "dataset_learning",
            "agentName": "Dataset Learning",
            "activeCount": len(active),
            "active": [_enrich(j) for j in active],
            "recent": [_enrich(j) for j in recent],
            "truth": {
                "reflects_real_dataset_jobs": True,
                "no_fictional_missions_or_success_rates": True,
            },
        }

    def reconcile_sidecars(self, *, max_files: int = 2000) -> dict[str, Any]:
        """Restore catalog rows from validated sidecars under allowed roots only."""
        from Data.modules.common.paths import normalize_path_key

        roots = [
            ("datasets_raw", self.corpus.datasets_raw),
            ("data_root", self._data_root()),
            ("corpus", self.corpus.root),
        ]
        # Restrict to configured allowed roots intersection.
        allowed = []
        for root_id, root in roots:
            try:
                resolved = root.resolve()
            except OSError:
                continue
            if any(self._path_under_allowed(resolved, allow) for allow in self.allowed_import_roots):
                allowed.append((root_id, root))
        found = find_sidecars_under_roots(allowed, max_files=max_files)
        created = 0
        updated = 0
        skipped_tombstone = 0
        conflicts: list[dict[str, Any]] = []
        restored_ids: list[str] = []

        for item in found:
            if item.get("tombstoned"):
                skipped_tombstone += 1
                continue
            sidecar = item.get("sidecar")
            if not sidecar:
                conflicts.append(
                    {
                        "path": item.get("path"),
                        "reason": "invalid_or_unreadable_sidecar",
                    }
                )
                continue
            dataset_id = str(sidecar["datasetId"])
            name = str(sidecar["name"])
            existing = self.store.get_dataset(dataset_id)
            directory = Path(str(item["directory"]))
            raw_path = sidecar.get("rawPath") or str(directory)
            # Prefer concrete file if directory only holds sidecar + one data file.
            if Path(raw_path).is_dir():
                data_files = [
                    p
                    for p in Path(raw_path).iterdir()
                    if p.is_file() and p.name not in {SIDECAR_FILENAME, ".leviathan-dataset.deleted"}
                ]
                if len(data_files) == 1:
                    raw_path = str(data_files[0])

            if existing is None:
                # Do not invent missing provenance — only restore what sidecar provides.
                source_type_raw = sidecar.get("sourceType") or "local"
                try:
                    source_type = SourceType(str(source_type_raw))
                except ValueError:
                    source_type = SourceType.LOCAL
                fmt = None
                if sidecar.get("detectedFormat"):
                    try:
                        fmt = DetectedFormat(str(sidecar["detectedFormat"]))
                    except ValueError:
                        fmt = None
                ds = self.store.create_dataset(
                    name=name,
                    source_type=source_type,
                    description="Restored from durable dataset sidecar",
                    original_filename=sidecar.get("originalFilename"),
                    original_uri=sidecar.get("originalUri"),
                    provenance={
                        **dict(sidecar.get("provenance") or {}),
                        "restoredFromSidecar": True,
                        "sidecarPath": item.get("path"),
                    },
                    metadata={
                        "restoredFromSidecar": True,
                        "pathKey": normalize_path_key(raw_path),
                        "sourcePath": raw_path,
                    },
                    status=DatasetStatus.RAW,
                    dataset_id=dataset_id,
                )
                self.store.update_dataset(
                    ds.dataset_id,
                    raw_path=raw_path,
                    content_hash=sidecar.get("contentHash"),
                    byte_size=sidecar.get("byteSize"),
                    row_count=sidecar.get("rowCount"),
                    detected_format=fmt,
                )
                if Path(raw_path).exists():
                    self.store.create_version(
                        dataset_id=ds.dataset_id,
                        version_label=str(sidecar.get("versionLabel") or "raw-restored"),
                        kind=VersionKind.RAW,
                        status=VersionStatus.READY,
                        storage_path=raw_path,
                        version_id=sidecar.get("versionId"),
                        schema={"type": "raw", "restoredFromSidecar": True},
                        metadata={"restoredFromSidecar": True},
                    )
                created += 1
                restored_ids.append(dataset_id)
                continue

            # Conflict: same id, different name/hash — report, do not invent merge.
            if existing.name != name:
                conflicts.append(
                    {
                        "datasetId": dataset_id,
                        "path": item.get("path"),
                        "reason": "name_conflict",
                        "catalogName": existing.name,
                        "sidecarName": name,
                    }
                )
                continue
            if (
                sidecar.get("contentHash")
                and existing.content_hash
                and sidecar.get("contentHash") != existing.content_hash
            ):
                conflicts.append(
                    {
                        "datasetId": dataset_id,
                        "path": item.get("path"),
                        "reason": "content_hash_conflict",
                        "catalogHash": existing.content_hash,
                        "sidecarHash": sidecar.get("contentHash"),
                    }
                )
                continue
            meta = dict(existing.metadata or {})
            meta["sidecarPath"] = item.get("path")
            self.store.update_dataset(existing.dataset_id, metadata=meta)
            updated += 1

        return {
            "scanned": len(found),
            "created": created,
            "updated": updated,
            "skippedTombstone": skipped_tombstone,
            "conflicts": conflicts,
            "restoredDatasetIds": restored_ids,
            "truth": {
                "sidecar_does_not_replace_catalog": True,
                "tombstones_block_auto_restore": True,
                "allowed_roots_only": True,
                "no_invented_names_or_provenance": True,
            },
        }

    @staticmethod
    def _path_under_allowed(path: Path, allowed_root: Path) -> bool:
        try:
            path.resolve().relative_to(Path(allowed_root).resolve())
            return True
        except (OSError, ValueError):
            return False

    def delete_dataset(self, dataset_id: str, *, write_tombstone_file: bool = True) -> bool:
        """Delete catalog row and optionally tombstone the corpus folder."""
        ds = self.get_dataset(dataset_id)
        if write_tombstone_file:
            try:
                write_tombstone(self._sidecar_directory_for(ds), dataset_id=dataset_id, reason="deleted")
            except OSError:
                pass
        return self.store.delete_dataset(dataset_id)

    def retry_index_job(self, job_id: str, *, resume: bool = True) -> DatasetJob:
        """Re-queue a failed/cancelled/interrupted INDEX job with the same config."""
        job = self.get_job(job_id)
        if job.job_type != DatasetJobType.INDEX:
            raise DatasetError("Only index jobs can be retried via this path", code="not_index_job")
        if job.status not in {
            DatasetJobStatus.FAILED,
            DatasetJobStatus.CANCELLED,
            DatasetJobStatus.INTERRUPTED,
        }:
            raise DatasetError(
                f"Job status {job.status.value} is not retryable",
                code="not_retryable",
                http_status=409,
            )
        if not job.dataset_id or not job.version_id:
            raise DatasetError("Job missing dataset/version", code="incomplete_job")
        cfg = dict(job.config or {})
        cfg["resume"] = bool(resume)
        new_job = self._queue_domain_job(
            job_type=DatasetJobType.INDEX,
            dataset_id=job.dataset_id,
            version_id=job.version_id,
            config=cfg,
        )
        if resume and job.checkpoint:
            self.store.update_job(new_job.job_id, checkpoint=dict(job.checkpoint))
            return self.get_job(new_job.job_id)
        return new_job

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
            self.store.update_job(job.job_id, phase="materializing", progress=0.92)
            mat = self._materialize_dataset(job.dataset_id, raw_path=dest, fmt=detection.format)
            self.store.update_job(job.job_id, phase="validating", progress=0.97)
            result["materialized"] = mat
        try:
            self.write_dataset_sidecar(job.dataset_id)
            result["sidecar"] = SIDECAR_FILENAME
        except Exception as exc:  # noqa: BLE001 — sidecar is recovery aid, not critical path
            result["sidecarError"] = redact_secrets(str(exc))
        if self.runner.is_cancel_requested(job.job_id):
            raise DatasetError("cancelled", code="cancelled", http_status=409)
        return result

    def _handle_import_hf(self, job: DatasetJob) -> dict[str, Any]:
        assert job.dataset_id
        try:
            filename = (job.config.get("filename") or "").strip() or None
            if filename:
                return self._handle_import_hf_legacy_file(job, filename=filename)
            return self._handle_import_hf_repository(job)
        except DatasetError as exc:
            if job.dataset_id and exc.code != "cancelled":
                self.store.update_dataset(job.dataset_id, status=DatasetStatus.FAILED)
            raise
        except Exception:
            if job.dataset_id:
                self.store.update_dataset(job.dataset_id, status=DatasetStatus.FAILED)
            raise

    def _hf_token_for_job(self, job: DatasetJob) -> str | None:
        token = self._hf_tokens.pop(job.job_id, None)
        return resolve_hf_token(token)

    def _throttled_job_progress(self, job_id: str) -> Any:
        import time as _time

        state = {"last": 0.0}

        def on_progress(info: dict[str, Any]) -> None:
            now = _time.monotonic()
            phase = str(info.get("phase") or "downloading")
            force = phase in {
                "discovering",
                "planning",
                "download_completed",
                "materializing",
                "validating",
                "finalizing",
                "failed",
                "cancelled",
                "rate_limited",
                "file_completed",
                "hf.download.file_completed",
            }
            if not force and (now - state["last"]) < 0.75:
                return
            state["last"] = now
            bytes_total = info.get("bytesTotal") or info.get("totalBytes")
            bytes_done = info.get("bytesDownloaded")
            progress = None
            if bytes_total and bytes_done is not None:
                progress = min(0.9, float(bytes_done) / max(1, float(bytes_total)))
            elif info.get("filesTotal") and info.get("filesCompleted") is not None:
                progress = min(0.9, float(info["filesCompleted"]) / max(1, float(info["filesTotal"])))
            checkpoint = {
                k: info[k]
                for k in (
                    "filesTotal",
                    "filesCompleted",
                    "filesFailed",
                    "bytesTotal",
                    "bytesDownloaded",
                    "bytesPerSecond",
                    "etaSeconds",
                    "workers",
                    "chunkSize",
                    "rateLimitEvents",
                    "filename",
                    "shardIndex",
                    "shardsTotal",
                    "relativePath",
                )
                if k in info
            }
            if "manifest" in info and isinstance(info["manifest"], dict):
                # Persist compact progress — full manifest is on disk.
                m = info["manifest"]
                checkpoint["manifestSummary"] = {
                    "filesTotal": m.get("filesTotal"),
                    "filesCompleted": m.get("filesCompleted"),
                    "filesFailed": m.get("filesFailed"),
                    "bytesTotal": m.get("bytesTotal"),
                    "bytesDownloaded": m.get("bytesDownloaded"),
                    "phase": m.get("phase"),
                    "resolvedRevision": m.get("resolvedRevision"),
                }
            if "checkpoint" in info and isinstance(info["checkpoint"], dict):
                checkpoint["file"] = info["checkpoint"]
            self.store.update_job(
                job_id,
                checkpoint=checkpoint,
                phase=phase,
                progress=progress,
            )

        return on_progress

    def _handle_import_hf_legacy_file(self, job: DatasetJob, *, filename: str) -> dict[str, Any]:
        """Legacy single-file HF import (backward compatible)."""
        assert job.dataset_id
        repo = str(job.config.get("repositoryId") or "")
        revision = str(job.config.get("revision") or "main")
        token = self._hf_token_for_job(job)
        dirs = self._dataset_dirs(job.dataset_id)
        dest = safe_dest_path(dirs["raw"], filename)
        file_cp = job.checkpoint.get("file") if isinstance(job.checkpoint, dict) else None
        cp = HfDownloadCheckpoint.from_dict(file_cp if isinstance(file_cp, dict) else (job.checkpoint or {}))
        if not cp.repository_id:
            cp = HfDownloadCheckpoint(repository_id=repo, revision=revision, filename=filename)

        def cancel() -> bool:
            return self.runner.is_cancel_requested(job.job_id)

        on_progress = self._throttled_job_progress(job.job_id)
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
        detection = detect_format(downloaded.path)
        digest = downloaded.content_hash
        size = downloaded.byte_size
        self.store.add_file(
            dataset_id=job.dataset_id,
            role="raw",
            path=str(downloaded.path),
            content_hash=digest,
            byte_size=size,
            metadata={
                "repositoryId": repo,
                "revision": revision,
                "filename": filename,
                "url": downloaded.url,
                "detection": detection.public_dict(),
                "mode": "file",
            },
        )
        self.store.update_dataset(
            job.dataset_id,
            status=DatasetStatus.RAW,
            content_hash=digest,
            byte_size=size,
            raw_path=str(downloaded.path),
            detected_format=detection.format,
            format_confidence=detection.confidence,
            original_uri=f"hf://datasets/{repo}@{revision}/{filename}",
            provenance={
                "repositoryId": repo,
                "revision": revision,
                "filename": filename,
                "rateLimitEvents": downloaded.checkpoint.rate_limit_events,
                "mode": "file",
            },
        )
        raw_version = self.store.create_version(
            dataset_id=job.dataset_id,
            version_label="raw-v1",
            kind=VersionKind.RAW,
            status=VersionStatus.READY,
            storage_path=str(downloaded.path),
            schema={"type": "raw", "format": detection.format.value},
        )
        self.store.update_version(raw_version.version_id, content_hash=digest, byte_size=size)
        result: dict[str, Any] = {
            "rawPath": str(downloaded.path),
            "contentHash": digest,
            "byteSize": size,
            "detection": detection.public_dict(),
            "checkpoint": downloaded.checkpoint.to_dict(),
            "rawVersionId": raw_version.version_id,
            "mode": "file",
        }
        if job.config.get("materialize", True):
            self.store.update_job(
                job.job_id,
                phase="materializing",
                progress=0.92,
                checkpoint={"file": downloaded.checkpoint.to_dict()},
            )
            mat = self._materialize_dataset(job.dataset_id, raw_path=downloaded.path, fmt=detection.format)
            self.store.update_job(job.job_id, phase="validating", progress=0.97)
            result["materialized"] = mat
        return result

    def _handle_import_hf_repository(self, job: DatasetJob) -> dict[str, Any]:
        """Full repository Hugging Face import — one DatasetRecord for all shards."""
        assert job.dataset_id
        repo = str(job.config.get("repositoryId") or "")
        revision = str(job.config.get("revision") or "main")
        token = self._hf_token_for_job(job)
        dirs = self._dataset_dirs(job.dataset_id)
        raw_root = dirs["raw"] / "hf"
        ensure_dir(raw_root)
        manifest_path = dirs["manifests"] / "hf_download_manifest.json"
        on_progress = self._throttled_job_progress(job.job_id)

        def cancel() -> bool:
            return self.runner.is_cancel_requested(job.job_id)

        on_progress({"phase": "discovering"})
        plan = discover_hf_repository(repo, revision=revision, token=token)
        if plan.unsupported_files:
            # Expose clearly in job checkpoint; do not silently ignore.
            on_progress(
                {
                    "phase": "planning",
                    "unsupportedFiles": [f.to_dict() for f in plan.unsupported_files],
                }
            )
        if not plan.data_files:
            raise DatasetError(
                "No supported dataset data files found in Hugging Face repository",
                code="hf_no_data_files",
                http_status=400,
            )

        existing = load_repo_manifest(manifest_path)
        on_progress({"phase": "planning", **plan.to_dict()})
        downloaded = download_hf_repository(
            plan=plan,
            raw_root=raw_root,
            token=token,
            manifest=existing,
            manifest_path=manifest_path,
            cancel_check=cancel,
            progress_cb=on_progress,
        )
        manifest = downloaded.manifest

        # Register each raw shard under preserved relative paths
        sources: list[dict[str, Any]] = []
        formats_seen: set[str] = set()
        primary_fmt: DetectedFormat | None = None
        for entry in plan.data_files:
            path = safe_dest_path(raw_root, entry.path)
            state = manifest.files.get(entry.path)
            if state is None or state.status != "complete" or not path.is_file():
                raise DatasetError(
                    f"Missing completed shard after download: {entry.path}",
                    code="hf_download_incomplete",
                    http_status=502,
                )
            detection = detect_format(path)
            formats_seen.add(detection.format.value)
            if primary_fmt is None:
                primary_fmt = detection.format
            digest = state.hash or sha256_file(path)
            self.store.add_file(
                dataset_id=job.dataset_id,
                role="raw",
                path=str(path),
                content_hash=digest,
                byte_size=path.stat().st_size,
                metadata={
                    "repositoryId": repo,
                    "revision": revision,
                    "resolvedRevision": manifest.resolved_revision,
                    "relativePath": entry.path,
                    "detection": detection.public_dict(),
                    "split": infer_split_from_path(entry.path),
                    "config": infer_config_from_path(entry.path),
                },
            )
            sources.append(
                {
                    "path": str(path),
                    "format": detection.format.value,
                    "split": infer_split_from_path(entry.path),
                    "relativePath": entry.path,
                    "sourceName": entry.path,
                    "provenance": {
                        "repositoryId": repo,
                        "revision": revision,
                        "resolvedRevision": manifest.resolved_revision,
                        "relativePath": entry.path,
                        "config": infer_config_from_path(entry.path),
                    },
                }
            )

        total_bytes = sum(Path(s["path"]).stat().st_size for s in sources)
        self.store.update_dataset(
            job.dataset_id,
            status=DatasetStatus.RAW,
            byte_size=total_bytes,
            raw_path=str(raw_root),
            detected_format=primary_fmt,
            format_confidence=1.0 if primary_fmt else None,
            original_uri=f"hf://datasets/{repo}@{revision}",
            original_filename=None,
            provenance={
                "repositoryId": repo,
                "revision": revision,
                "resolvedRevision": manifest.resolved_revision,
                "mode": "repository",
                "filesTotal": manifest.files_total,
                "bytesTotal": manifest.bytes_total,
                "formats": sorted(formats_seen),
                "classification": plan.classification,
                "unsupportedFiles": [f.path for f in plan.unsupported_files],
                "rateLimitEvents": downloaded.manifest.to_dict().get("phase"),
                "bytesPerSecond": downloaded.bytes_per_second,
            },
            metadata={
                "hfManifestPath": str(manifest_path),
                "sourceFileCount": len(sources),
            },
        )
        write_repo_manifest(manifest_path, manifest)
        raw_version = self.store.create_version(
            dataset_id=job.dataset_id,
            version_label="raw-v1",
            kind=VersionKind.RAW,
            status=VersionStatus.READY,
            storage_path=str(raw_root),
            schema={"type": "raw", "formats": sorted(formats_seen), "fileCount": len(sources)},
            metadata={"files": [s["relativePath"] for s in sources]},
        )
        self.store.update_version(raw_version.version_id, byte_size=total_bytes)
        result: dict[str, Any] = {
            "mode": "repository",
            "rawRoot": str(raw_root),
            "byteSize": total_bytes,
            "filesTotal": len(sources),
            "manifestPath": str(manifest_path),
            "plan": plan.to_dict(),
            "bytesPerSecond": downloaded.bytes_per_second,
            "rawVersionId": raw_version.version_id,
            "formats": sorted(formats_seen),
        }
        if job.config.get("materialize", True):
            mat = self._materialize_dataset_sources(
                job.dataset_id,
                sources=sources,
                progress_cb=on_progress,
            )
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
        staging = dirs["materialized"] / "canonical.jsonl.staging"
        outcome = materialize_from_raw(raw_path, staging, fmt=fmt)
        Path(staging).replace(dest)
        outcome["storagePath"] = str(dest)
        return self._publish_materialized_version(dataset_id, dest=dest, outcome=outcome)

    def _materialize_dataset_sources(
        self,
        dataset_id: str,
        *,
        sources: list[dict[str, Any]],
        progress_cb: Any | None = None,
    ) -> dict[str, Any]:
        self.store.update_dataset(dataset_id, status=DatasetStatus.MATERIALIZING)
        dirs = self._dataset_dirs(dataset_id)
        dest = dirs["materialized"] / "canonical.jsonl"
        staging = dirs["materialized"] / "canonical.jsonl.staging"
        if progress_cb:
            progress_cb({"phase": "materializing", "shardsTotal": len(sources), "shardIndex": 0})
        outcome = materialize_from_sources(sources, staging, progress_cb=progress_cb)
        Path(staging).replace(dest)
        outcome["storagePath"] = str(dest)
        if progress_cb:
            progress_cb({"phase": "finalizing", "rowCount": outcome.get("rowCount")})
        return self._publish_materialized_version(dataset_id, dest=dest, outcome=outcome)

    def _publish_materialized_version(
        self,
        dataset_id: str,
        *,
        dest: Path,
        outcome: dict[str, Any],
    ) -> dict[str, Any]:
        dirs = self._dataset_dirs(dataset_id)
        validation = outcome.get("validation") or {"valid": True, "rowCount": outcome.get("rowCount")}
        version = self.store.create_version(
            dataset_id=dataset_id,
            version_label="materialized-v1",
            kind=VersionKind.MATERIALIZED,
            status=VersionStatus.READY if validation.get("valid") else VersionStatus.FAILED,
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
            status=DatasetStatus.READY if validation.get("valid") else DatasetStatus.FAILED,
            row_count=outcome["rowCount"],
            content_hash=outcome["contentHash"],
            byte_size=outcome.get("byteSize"),
        )
        result = {
            "versionId": version.version_id,
            "contentHash": outcome["contentHash"],
            "rowCount": outcome["rowCount"],
            "byteSize": outcome["byteSize"],
            "validation": validation,
            "storagePath": str(dest),
        }
        if validation.get("valid"):
            auto = self._maybe_auto_index_ready_version(dataset_id, version.version_id)
            if auto is not None:
                result["autoIndex"] = auto
        return result

    def _maybe_auto_index_ready_version(
        self,
        dataset_id: str,
        version_id: str,
        *,
        validation: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Enqueue knowledge index when a version becomes READY (best-effort gates).

        Contamination/quality gates are operator-driven and not always attached to
        version metadata; when absent we still auto-index and document that fact.
        """
        if not bool(getattr(self, "datasets_auto_index_ready_to_knowledge", True)):
            return None
        if self.knowledge is None:
            return {
                "enqueued": False,
                "reason": "no_knowledge",
                "truth": {"contamination_quality_gates_best_effort": True},
            }
        try:
            ver = self.get_version(version_id)
        except Exception:  # noqa: BLE001
            return {"enqueued": False, "reason": "version_missing"}
        if ver.status != VersionStatus.READY:
            return {"enqueued": False, "reason": "not_ready"}
        if ver.kind not in _INDEXABLE_VERSION_KINDS:
            return {"enqueued": False, "reason": "kind_not_indexable", "kind": ver.kind.value}
        report = validation if validation is not None else dict(ver.validation or {})
        if report and report.get("valid") is False:
            return {"enqueued": False, "reason": "validation_failed"}
        meta = dict(ver.metadata or {})
        # Soft quarantine / contamination signals when present on the version.
        if meta.get("quarantined") or meta.get("quarantine"):
            return {"enqueued": False, "reason": "quarantined"}
        contamination = meta.get("contamination") or report.get("contamination")
        if isinstance(contamination, dict) and contamination.get("blocked"):
            return {"enqueued": False, "reason": "contamination_blocked"}
        quality = meta.get("quality") or report.get("quality")
        if isinstance(quality, dict) and quality.get("blocked"):
            return {"enqueued": False, "reason": "quality_blocked"}
        # Skip if an index for this version is already READY / INDEXING / PENDING.
        for idx in self.store.list_indexes(dataset_id):
            if idx.version_id == version_id and idx.status in {
                IndexStatus.READY,
                IndexStatus.INDEXING,
                IndexStatus.PENDING,
            }:
                return {
                    "enqueued": False,
                    "reason": "already_indexed",
                    "indexId": idx.index_id,
                    "indexStatus": idx.status.value,
                    "truth": {"contamination_quality_gates_best_effort": True},
                }
        # Also skip when an INDEX job is already queued/running for this version.
        for job in self.store.list_jobs(dataset_id=dataset_id, limit=50):
            if (
                job.version_id == version_id
                and job.job_type == DatasetJobType.INDEX
                and job.status
                in {
                    DatasetJobStatus.QUEUED,
                    DatasetJobStatus.RUNNING,
                }
            ):
                return {
                    "enqueued": False,
                    "reason": "already_indexed",
                    "jobId": job.job_id,
                    "jobStatus": job.status.value,
                    "truth": {"contamination_quality_gates_best_effort": True},
                }
        try:
            job = self.enqueue_index(dataset_id, version_id)
            return {
                "enqueued": True,
                "jobId": job.job_id,
                "versionId": job.version_id,
                "truth": {
                    "contamination_quality_gates_best_effort": True,
                    "auto_index_after_ready": True,
                },
            }
        except Exception as exc:  # noqa: BLE001 — never fail materialize/ready path
            return {
                "enqueued": False,
                "reason": "enqueue_failed",
                "error": redact_secrets(str(exc)),
                "truth": {"contamination_quality_gates_best_effort": True},
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
        ready = self.get_version(version.version_id)
        self._maybe_auto_index_ready_version(
            dataset_id,
            ready.version_id,
            validation=dict(ready.validation or {}),
        )
        return ready

    def _handle_validate(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        ver, records = self._load_version_records(job.version_id)
        report = validate_records(records)
        updates: dict[str, Any] = {"validation": report}
        # Promote to READY when validation passes for indexable versions still building/pending.
        if report.get("valid") and ver.status in {
            VersionStatus.PENDING,
            VersionStatus.BUILDING,
            VersionStatus.READY,
        }:
            if ver.status != VersionStatus.READY and ver.kind in _INDEXABLE_VERSION_KINDS:
                updates["status"] = VersionStatus.READY
        self.store.update_version(ver.version_id, **updates)
        if report.get("valid"):
            auto = self._maybe_auto_index_ready_version(
                job.dataset_id,
                ver.version_id,
                validation=report,
            )
            if auto is not None:
                report = {**report, "autoIndex": auto}
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

    def _cleanup_duplicate_target(self, target_dataset_id: str) -> None:
        """Remove a partially created duplicate (DB + corpus dirs). Never touches the source."""
        try:
            self.store.delete_dataset(target_dataset_id)
        except Exception:  # noqa: BLE001 — best-effort rollback
            pass
        for key in ("raw", "materialized", "processed", "exports", "manifests"):
            root = getattr(self.corpus, f"datasets_{key}", None)
            if root is None:
                continue
            target_dir = Path(root) / target_dataset_id
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)

    def _atomic_copy_file(self, source: Path, dest: Path) -> tuple[str, int]:
        """Copy ``source`` to ``dest`` via temp file, verify hash, return (hash, size)."""
        if not source.is_file():
            raise DatasetError(f"Source storage missing: {source}", code="source_missing", http_status=404)
        ensure_dir(dest.parent)
        digest = sha256_file(source)
        tmp = dest.parent / f".{dest.name}.dup.tmp"
        try:
            shutil.copy2(source, tmp)
            copied = sha256_file(tmp)
            if copied != digest:
                raise DatasetError(
                    "Duplicate copy hash mismatch",
                    code="hash_mismatch",
                    http_status=500,
                )
            tmp.replace(dest)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return digest, dest.stat().st_size

    def _handle_duplicate(self, job: DatasetJob) -> dict[str, Any]:
        target_id = str(job.config.get("targetDatasetId") or job.dataset_id or "")
        source_id = str(job.config.get("sourceDatasetId") or "")
        source_version_id = job.config.get("sourceVersionId")
        empty = bool(job.config.get("empty"))
        if not target_id or not source_id:
            raise DatasetError("Duplicate job missing source/target", code="invalid_config", http_status=400)

        source = self.get_dataset(source_id)
        target = self.get_dataset(target_id)
        try:
            self.store.update_job(job.job_id, phase="copying", progress=0.05)
            if empty or not source_version_id:
                self.store.update_dataset(
                    target_id,
                    status=DatasetStatus.CREATED,
                    provenance={
                        **dict(target.provenance or {}),
                        "duplicatedFromDatasetId": source.dataset_id,
                        "emptyShell": True,
                    },
                )
                self.store.update_job(job.job_id, phase="done", progress=1.0)
                return {
                    "datasetId": target_id,
                    "empty": True,
                    "name": target.name,
                    "sourceDatasetId": source_id,
                }

            source_ver = self.get_version(str(source_version_id))
            if not source_ver.storage_path:
                raise DatasetError("Source version has no storage", code="no_storage", http_status=400)
            source_path = Path(source_ver.storage_path)
            dirs = self._dataset_dirs(target_id)

            # Prefer content-addressed raw copy when source is a plain file under corpus.
            self.store.update_job(job.job_id, phase="copying_storage", progress=0.2)
            if source_ver.kind == VersionKind.RAW or source_path.parent == (self.corpus.datasets_raw / source_id):
                dest, digest, size = copy_immutable_raw(source_path, dirs["raw"])
            elif source_ver.kind in {
                VersionKind.MATERIALIZED,
                VersionKind.TRANSFORMED,
                VersionKind.SPLIT,
            }:
                dest = dirs["materialized"] / "canonical.jsonl"
                digest, size = self._atomic_copy_file(source_path, dest)
            else:
                dest = dirs["processed"] / source_path.name
                digest, size = self._atomic_copy_file(source_path, dest)

            if self.runner.is_cancel_requested(job.job_id):
                raise DatasetError("cancelled", code="cancelled", http_status=409)

            self.store.update_job(job.job_id, phase="registering", progress=0.7)
            self.store.add_file(
                dataset_id=target_id,
                role="duplicate",
                path=str(dest),
                content_hash=digest,
                byte_size=size,
                metadata={
                    "duplicatedFromDatasetId": source_id,
                    "duplicatedFromVersionId": source_ver.version_id,
                },
            )
            new_ver = self.store.create_version(
                dataset_id=target_id,
                version_label=f"dup-{source_ver.version_label}",
                kind=source_ver.kind,
                status=VersionStatus.READY,
                storage_path=str(dest),
                schema=dict(source_ver.schema or {}),
                metadata={
                    **dict(source_ver.metadata or {}),
                    "duplicatedFromVersionId": source_ver.version_id,
                },
                transform_lineage=list(source_ver.transform_lineage or [])
                + [
                    {
                        "name": "duplicate",
                        "params": {
                            "sourceDatasetId": source_id,
                            "sourceVersionId": source_ver.version_id,
                        },
                        "appliedAt": utc_now(),
                    }
                ],
            )
            self.store.update_version(
                new_ver.version_id,
                content_hash=digest,
                byte_size=size,
                row_count=source_ver.row_count,
                split=dict(source_ver.split or {}),
                token_stats=dict(source_ver.token_stats or {}),
                validation=dict(source_ver.validation or {}),
            )
            self.store.update_dataset(
                target_id,
                status=DatasetStatus.READY if source_ver.kind != VersionKind.RAW else DatasetStatus.RAW,
                content_hash=digest,
                byte_size=size,
                row_count=source_ver.row_count,
                raw_path=str(dest) if source_ver.kind == VersionKind.RAW else None,
                detected_format=source.detected_format,
                format_confidence=source.format_confidence,
                provenance={
                    **dict(target.provenance or {}),
                    "duplicatedFromDatasetId": source_id,
                    "duplicatedFromVersionId": source_ver.version_id,
                    "contentHash": digest,
                },
            )
            # Also copy original raw file into independent storage when available and distinct.
            if (
                source.raw_path
                and Path(source.raw_path).is_file()
                and Path(source.raw_path).resolve() != source_path.resolve()
            ):
                try:
                    raw_dest, raw_digest, raw_size = copy_immutable_raw(Path(source.raw_path), dirs["raw"])
                    self.store.add_file(
                        dataset_id=target_id,
                        role="raw",
                        path=str(raw_dest),
                        content_hash=raw_digest,
                        byte_size=raw_size,
                        metadata={"duplicatedFromRaw": source.raw_path},
                    )
                    self.store.update_dataset(target_id, raw_path=str(raw_dest))
                except DatasetError:
                    pass

            if self.runner.is_cancel_requested(job.job_id):
                raise DatasetError("cancelled", code="cancelled", http_status=409)

            self.store.update_job(job.job_id, phase="done", progress=1.0, version_id=new_ver.version_id)
            return {
                "datasetId": target_id,
                "versionId": new_ver.version_id,
                "contentHash": digest,
                "byteSize": size,
                "rowCount": source_ver.row_count,
                "name": target.name,
                "sourceDatasetId": source_id,
                "sourceVersionId": source_ver.version_id,
                "storagePath": str(dest),
            }
        except Exception:
            try:
                self.store.update_dataset(target_id, status=DatasetStatus.FAILED)
            except Exception:  # noqa: BLE001 — target may already be gone
                pass
            self._cleanup_duplicate_target(target_id)
            raise

    def _handle_index(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        if self.knowledge is None:
            raise DatasetError("KnowledgeStore not configured", code="no_knowledge", http_status=500)
        requested_version_id = str(
            job.config.get("requestedVersionId") or job.version_id
        )
        ensure_materialized = bool(job.config.get("ensureMaterialized"))
        self.store.update_job(job.job_id, phase="inspecting", progress=0.02)

        # Re-resolve at execution time — filesystem / version state may have changed.
        try:
            ver = self._resolve_indexable_version(job.dataset_id, requested_version_id)
        except DatasetError as exc:
            if not ensure_materialized or exc.code not in {"no_indexable_version", "storage_not_file"}:
                raise
            self.store.update_job(job.job_id, phase="materializing", progress=0.08)
            ds = self.get_dataset(job.dataset_id)
            raw_path = ds.raw_path
            if not raw_path:
                req = self.get_version(requested_version_id)
                raw_path = req.storage_path
            if not raw_path:
                raise DatasetError(
                    "Cannot materialize: dataset has no raw source path",
                    code="no_raw",
                    http_status=409,
                ) from exc
            raw = Path(raw_path)
            if not raw.exists():
                raise DatasetError(
                    f"Source path missing: {raw}",
                    code="source_missing",
                    http_status=409,
                ) from exc
            fmt = ds.detected_format
            # Avoid enqueuing a second INDEX job from materialize's auto-index hook.
            prev_auto = bool(getattr(self, "datasets_auto_index_ready_to_knowledge", True))
            self.datasets_auto_index_ready_to_knowledge = False
            try:
                if raw.is_file():
                    mat = self._materialize_dataset(job.dataset_id, raw_path=raw, fmt=fmt)
                else:
                    # Directory-backed RAW — materialize from discoverable data files.
                    from .offline import ALLOWED_EXTENSIONS

                    sources: list[dict[str, Any]] = []
                    for child in sorted(raw.rglob("*")):
                        if not child.is_file():
                            continue
                        if child.suffix.lower() not in ALLOWED_EXTENSIONS:
                            continue
                        detection = detect_format(child)
                        sources.append(
                            {
                                "path": str(child),
                                "format": detection.format.value,
                                "relativePath": str(child.relative_to(raw)),
                                "sourceName": child.name,
                                "provenance": {"sourcePath": str(child), "datasetId": job.dataset_id},
                            }
                        )
                    if not sources:
                        raise DatasetError(
                            "Directory source has no supported data files to materialize",
                            code="no_indexable_version",
                            http_status=409,
                        ) from exc
                    dirs = self._dataset_dirs(job.dataset_id)
                    dest = dirs["materialized"] / "learned.jsonl"
                    outcome = materialize_from_sources(sources, dest)
                    version = self.store.create_version(
                        dataset_id=job.dataset_id,
                        version_label="materialized-learned",
                        kind=VersionKind.MATERIALIZED,
                        status=VersionStatus.READY,
                        storage_path=str(dest),
                        schema=canonical_schema_dict(),
                        parent_version_id=requested_version_id,
                        metadata={"learnedMaterialize": True, "sourceCount": len(sources)},
                    )
                    self.store.update_version(
                        version.version_id,
                        row_count=outcome.get("rowCount"),
                        byte_size=outcome.get("byteSize"),
                        content_hash=outcome.get("contentHash"),
                        validation=outcome.get("validation") or {},
                    )
                    self.store.update_dataset(
                        job.dataset_id,
                        status=DatasetStatus.READY,
                        row_count=outcome.get("rowCount"),
                        content_hash=outcome.get("contentHash"),
                        byte_size=outcome.get("byteSize"),
                    )
                    mat = {"versionId": version.version_id, **outcome}
            finally:
                self.datasets_auto_index_ready_to_knowledge = prev_auto
            ver = self.get_version(str(mat["versionId"]))

        if not ver.storage_path:
            raise DatasetError("Version has no storage", code="no_storage", http_status=400)
        storage_path = Path(ver.storage_path)
        if not storage_path.exists():
            raise DatasetError(
                f"Version storage path does not exist: {storage_path}",
                code="storage_missing",
                http_status=400,
            )
        if not storage_path.is_file():
            raise DatasetError(
                f"Version storage path is not a file: {storage_path}",
                code="storage_not_file",
                http_status=400,
            )
        scope = str(job.config.get("scope") or "dataset")
        max_records = job.config.get("maxRecords")
        offline_only = bool(job.config.get("offlineOnly"))
        source_fingerprint = job.config.get("sourceFingerprint")
        embedding_status = None
        embeddings = getattr(self.knowledge, "embedding_provider", None)
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
        # Index row and knowledge docs must reference the resolved source version.
        self.store.update_job(job.job_id, phase="indexing", progress=0.15, version_id=ver.version_id)
        index = self.store.create_index(
            dataset_id=job.dataset_id,
            version_id=ver.version_id,
            knowledge_scope=scope,
            status=IndexStatus.INDEXING,
            provenance={
                "requestedVersionId": requested_version_id,
                "resolvedVersionId": ver.version_id,
                "learnToBrain": bool(job.config.get("learnToBrain")),
            },
        )
        try:

            def _progress(info: dict[str, Any]) -> None:
                processed = int(info.get("processed") or 0)
                # Soft asymptotic progress while streaming unknown-length corpora.
                phase = str(info.get("phase") or "indexing")
                if phase in {"source_check", "parsing"}:
                    ratio = 0.08
                elif phase in {"relations", "verifying"}:
                    ratio = min(0.94, 0.7 + (processed / (processed + 200)) * 0.2)
                else:
                    ratio = min(0.92, 0.15 + (processed / (processed + 200)) * 0.75)
                checkpoint = {
                    "processed": processed,
                    "indexed": info.get("indexed"),
                    "skippedUnchanged": info.get("skippedUnchanged"),
                    "chunkCount": info.get("chunkCount"),
                    "relationsAccepted": info.get("relationsAccepted"),
                    "relationsRejected": info.get("relationsRejected"),
                    "lastRecordId": info.get("lastRecordId"),
                    "embeddingMode": info.get("embeddingMode"),
                    "embeddingsSemantic": info.get("embeddingsSemantic"),
                    "phase": phase,
                }
                self.store.update_job(
                    job.job_id,
                    phase=phase,
                    progress=ratio,
                    checkpoint=checkpoint,
                )

            resume_after = None
            if bool(job.config.get("resume")) and isinstance(job.checkpoint, dict):
                resume_after = job.checkpoint.get("lastRecordId")

            outcome = index_version_file(
                self.knowledge,
                storage_path,
                dataset_id=job.dataset_id,
                version_id=ver.version_id,
                scope=scope,
                max_records=int(max_records) if max_records is not None else None,
                progress_cb=_progress,
                cancel_cb=lambda: self.runner.is_cancel_requested(job.job_id),
                extract_relations=bool(
                    job.config.get("extractRelations", self.extract_relations_on_index)
                ),
                max_relations_per_doc=int(
                    job.config.get("maxRelationsPerDoc") or self.max_relations_per_doc
                ),
                write_batch_size=int(
                    job.config.get("writeBatchSize") or self.index_write_batch_size
                ),
                resume_after_record_id=str(resume_after) if resume_after else None,
            )
            from .offline import build_projection_manifest
            from Data.modules.common.atomic import atomic_write_text

            self.store.update_job(job.job_id, phase="publishing", progress=0.96)
            manifest = build_projection_manifest(
                projection_id=index.index_id,
                dataset_id=job.dataset_id,
                version_id=ver.version_id,
                source_fingerprint=str(source_fingerprint or ver.content_hash or ""),
                job_id=job.job_id,
                outcome=outcome,
                embedding_status=embedding_status,
                offline_only=offline_only,
            )
            manifest["requestedVersionId"] = requested_version_id
            manifest["resolvedVersionId"] = ver.version_id
            manifest["learnToBrain"] = bool(job.config.get("learnToBrain"))
            manifest["embeddingMode"] = outcome.get("embeddingMode")
            manifest["embeddingsSemantic"] = outcome.get("embeddingsSemantic")
            manifest["relationsAccepted"] = outcome.get("relationsAccepted")
            manifest["relationsRejected"] = outcome.get("relationsRejected")
            manifest_path = self.corpus.datasets_manifests / f"brain-{index.index_id}.json"
            ensure_dir(manifest_path.parent)
            atomic_write_text(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            manifest["manifestPath"] = str(manifest_path)
            provenance = {
                **outcome,
                "manifest": manifest,
                "offlineOnly": offline_only,
                "requestedVersionId": requested_version_id,
                "resolvedVersionId": ver.version_id,
                "learnToBrain": bool(job.config.get("learnToBrain")),
                "datasetName": self.get_dataset(job.dataset_id).name,
                "relationsVerified": int(outcome.get("relationsAccepted") or 0) > 0,
            }
            emb_model = None
            emb = outcome.get("embeddings") if isinstance(outcome.get("embeddings"), dict) else {}
            if outcome.get("embeddingsSemantic"):
                emb_model = emb.get("provider_id") or "semantic"
            elif outcome.get("embeddingsAvailable"):
                emb_model = f"non_semantic:{emb.get('provider_id') or 'fallback'}"
            else:
                emb_model = "lexical_only"
            self.store.update_index(
                index.index_id,
                status=IndexStatus.READY,
                chunk_count=outcome["chunkCount"],
                embedding_model=emb_model,
                provenance=provenance,
            )
            superseded: list[str] = []
            if bool(job.config.get("rebuild")):
                for old in self.store.list_indexes(job.dataset_id):
                    if (
                        old.index_id != index.index_id
                        and old.version_id == ver.version_id
                        and old.status == IndexStatus.READY
                    ):
                        self.store.update_index(
                            old.index_id,
                            status=IndexStatus.FAILED,
                            provenance={
                                **dict(old.provenance or {}),
                                "supersededBy": index.index_id,
                                "reason": "rebuild",
                            },
                        )
                        superseded.append(old.index_id)
            try:
                self.write_dataset_sidecar(job.dataset_id)
            except Exception:  # noqa: BLE001
                pass
            self.store.update_job(job.job_id, phase="ready", progress=1.0)
            return {
                "indexId": index.index_id,
                **outcome,
                "manifest": manifest,
                "supersededIndexIds": superseded,
                "rebuild": bool(job.config.get("rebuild")),
                "requestedVersionId": requested_version_id,
                "resolvedVersionId": ver.version_id,
                "learnToBrain": bool(job.config.get("learnToBrain")),
            }
        except Exception as exc:
            self.store.update_index(
                index.index_id,
                status=IndexStatus.FAILED,
                provenance={"error": redact_secrets(str(exc))},
            )
            raise

    def list_hf_files(self, repository_id: str, *, revision: str = "main", token: str | None = None) -> list[dict[str, Any]]:
        # Prefer provider_io when workers are the execution owner. Never silently
        # fall back to Control Plane Hub I/O in production externalized mode.
        from Data.modules.datasets.types import DatasetError
        from Data.modules.provider_io.credentials import store_ephemeral_token
        from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
        from Data.modules.provider_io.facade import ProviderExecutionClient
        from Data.modules.provider_io.readiness import provider_io_workers_ready
        from Data.modules.workers.settings import load_worker_settings

        try:
            wsettings = load_worker_settings()
            externalized = bool(wsettings.enabled and wsettings.externalize_api_runners)
        except Exception:  # noqa: BLE001
            externalized = False

        if not externalized:
            return list_hf_dataset_files(repository_id, revision=revision, token=token)

        if self.jobs is None:
            raise DatasetError(
                "job runtime not bound; refusing Control Plane HF list fallback",
                code=ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
            )
        db_path = getattr(getattr(self.jobs, "store", None), "path", None)
        if not provider_io_workers_ready(db_path):
            raise DatasetError(
                "provider_io workers unavailable; refusing Control Plane HF list fallback",
                code=ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
            )

        credential_ref = "huggingface"
        if token:
            credential_ref = store_ephemeral_token(token, prefix="hf")
        client = ProviderExecutionClient(self.jobs)
        try:
            result = client.submit_and_wait(
                provider="huggingface",
                capability="hf.list",
                payload={
                    "repository_id": repository_id,
                    "revision": revision,
                },
                credential_ref=credential_ref,
                latency_class="interactive",
                requested_by="dataset_service",
                deadline_seconds=60.0,
            )
        except ProviderError as exc:
            raise DatasetError(str(exc), code=exc.code.value) from exc
        if result.status != "succeeded" or not isinstance(result.structured, dict):
            err = (result.error or {}).get("message") or "HF list failed"
            raise DatasetError(
                str(err), code=(result.error or {}).get("code") or "PROVIDER_UNAVAILABLE"
            )
        files = result.structured.get("files") or []
        return list(files) if isinstance(files, list) else []

    # --- Wave 8 industrial data factory ---

    def create_mixture(
        self,
        *,
        name: str,
        components: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        built: list[MixtureComponent] = []
        for raw in components:
            version_id = str(raw.get("version_id") or raw.get("versionId") or "")
            ver = self.get_version(version_id)
            content_hash = str(raw.get("content_hash") or raw.get("contentHash") or ver.content_hash or "")
            if not content_hash:
                raise DatasetError(
                    f"Version {version_id} missing content_hash for mixture",
                    code="mixture_missing_hash",
                )
            built.append(
                MixtureComponent(
                    version_id=version_id,
                    content_hash=content_hash,
                    weight=float(raw.get("weight") or 1.0),
                    domain=str(raw.get("domain") or "general"),
                    quality=float(raw.get("quality") or 1.0),
                    split=str(raw["split"]) if raw.get("split") is not None else None,
                )
            )
        manifest = build_mixture_manifest(name=name, components=built, metadata=metadata)
        return self.store.save_mixture(manifest.public_dict())

    def get_mixture(self, mixture_id: str) -> dict[str, Any]:
        mix = self.store.get_mixture(mixture_id)
        if mix is None:
            raise DatasetError("Mixture not found", code="not_found", http_status=404)
        return mix

    def list_mixtures(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_mixtures(limit=limit)

    def enqueue_shard_ingest(
        self,
        dataset_id: str,
        *,
        sources: list[str],
        interrupt_after: int | None = None,
        resume_from_job_id: str | None = None,
    ) -> DatasetJob:
        self.get_dataset(dataset_id)
        checkpoint: dict[str, Any] = {}
        if resume_from_job_id:
            prior = self.get_job(resume_from_job_id)
            checkpoint = dict(prior.checkpoint or {})
            if prior.config.get("sources") and not sources:
                sources = list(prior.config.get("sources") or [])
        job = self._queue_domain_job(
            job_type=DatasetJobType.SHARD_INGEST,
            dataset_id=dataset_id,
            config={"sources": sources, "interrupt_after": interrupt_after},
        )
        if checkpoint:
            job = self.store.update_job(job.job_id, checkpoint=checkpoint)
        return job

    def enqueue_contamination_scan(
        self,
        dataset_id: str,
        version_id: str,
        *,
        sealed_cases: list[dict[str, Any]] | None = None,
        threshold: float = 0.35,
    ) -> DatasetJob:
        self.get_version(version_id)
        return self._queue_domain_job(
            job_type=DatasetJobType.CONTAMINATION_SCAN,
            dataset_id=dataset_id,
            version_id=version_id,
            config={"sealed_cases": list(sealed_cases or []), "threshold": threshold},
        )

    def packing_simulation(self, version_id: str, *, max_seq_length: int = 512) -> dict[str, Any]:
        _, records = self._load_version_records(version_id)
        return simulate_packing(records, max_seq_length=max_seq_length).public_dict()

    def enqueue_annotation(
        self,
        *,
        dataset_id: str,
        record_id: str,
        label_type: str = "preference",
        version_id: str | None = None,
    ) -> dict[str, Any]:
        self.get_dataset(dataset_id)
        item = self.annotation_queue.enqueue(
            dataset_id=dataset_id,
            record_id=record_id,
            label_type=label_type,
            version_id=version_id,
        )
        return item.public_dict()

    def _handle_shard_ingest(self, job: DatasetJob) -> dict[str, Any]:
        dataset_id = job.dataset_id or ""
        sources = [Path(p) for p in (job.config.get("sources") or [])]
        if not sources:
            raise DatasetError("SHARD_INGEST requires sources", code="invalid_config")
        dest = self._dataset_dirs(dataset_id)["raw"] / "shards"
        plan = build_shard_plan(sources, dest)
        ckpt = ShardIngestCheckpoint.from_dict(job.checkpoint if job.checkpoint else None)
        # Resume must keep the same plan_id as the verified checkpoint cursor.
        if ckpt.plan_id:
            plan.plan_id = ckpt.plan_id
        else:
            ckpt.plan_id = plan.plan_id
        interrupt_after = job.config.get("interrupt_after")

        def cancel() -> bool:
            return self.runner.is_cancel_requested(job.job_id)

        ckpt, outputs = ingest_shards(
            plan,
            checkpoint=ckpt,
            cancel_check=cancel,
            interrupt_after=int(interrupt_after) if interrupt_after is not None else None,
        )
        self.store.update_job(job.job_id, checkpoint=ckpt.to_dict())
        if ckpt.status == "interrupted":
            # Surface as failed/interrupted via runner — raise to mark interrupted path.
            raise DatasetError(
                "Shard ingest interrupted for resume",
                code="shard_interrupted",
                http_status=409,
            )
        if ckpt.status == "cancelled":
            raise DatasetError("Shard ingest cancelled", code="cancelled", http_status=409)
        return {
            "plan": plan.public_dict(),
            "checkpoint": ckpt.to_dict(),
            "shards": outputs,
            "truth": {"resume_uses_verified_shard_hash_state": True},
        }

    def _handle_contamination_scan(self, job: DatasetJob) -> dict[str, Any]:
        version_id = job.version_id or ""
        _, records = self._load_version_records(version_id)
        sealed = list(job.config.get("sealed_cases") or [])
        if not sealed:
            # Fall back to empty sealed set — report passes with honesty note.
            report = scan_contamination(records, [], threshold=float(job.config.get("threshold") or 0.35))
            out = report.public_dict()
            out["note"] = "No sealed cases provided — contamination gate not exercised"
            return out
        report = scan_contamination(
            records,
            sealed,
            threshold=float(job.config.get("threshold") or 0.35),
        )
        return report.public_dict()

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
        checkpoint = dict(data.get("checkpoint") or {})
        for key, value in list(checkpoint.items()):
            if isinstance(value, str):
                checkpoint[key] = redact_secrets(value)
            elif "token" in key.lower() or "secret" in key.lower() or "authorization" in key.lower():
                checkpoint[key] = "[REDACTED]"
        data["checkpoint"] = checkpoint
        # Derived download summary for the activity console (view aid, not a second store).
        data["download"] = self._public_download_summary(job.job_type.value, cfg, checkpoint)
        return data

    @staticmethod
    def _public_download_summary(
        job_type: str,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
    ) -> dict[str, Any] | None:
        file_cp = checkpoint.get("file") if isinstance(checkpoint.get("file"), dict) else {}
        manifest = (
            checkpoint.get("manifestSummary")
            if isinstance(checkpoint.get("manifestSummary"), dict)
            else {}
        )
        has_progress = any(
            k in checkpoint or k in file_cp or k in manifest
            for k in (
                "bytesDownloaded",
                "bytesTotal",
                "totalBytes",
                "filesTotal",
                "filesCompleted",
                "filename",
                "relativePath",
                "repositoryId",
            )
        )
        if not has_progress and job_type != DatasetJobType.IMPORT_HF.value:
            return None
        if job_type != DatasetJobType.IMPORT_HF.value and not has_progress:
            return None

        def _int(value: Any) -> int | None:
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        bytes_downloaded_i = _int(
            checkpoint.get("bytesDownloaded")
            if checkpoint.get("bytesDownloaded") is not None
            else file_cp.get("bytesDownloaded")
            if file_cp.get("bytesDownloaded") is not None
            else manifest.get("bytesDownloaded")
        )
        total_bytes_i = _int(
            checkpoint.get("bytesTotal")
            if checkpoint.get("bytesTotal") is not None
            else checkpoint.get("totalBytes")
            if checkpoint.get("totalBytes") is not None
            else file_cp.get("totalBytes")
            if file_cp.get("totalBytes") is not None
            else manifest.get("bytesTotal")
        )
        files_total_i = _int(
            checkpoint.get("filesTotal")
            if checkpoint.get("filesTotal") is not None
            else manifest.get("filesTotal")
        )
        files_completed_i = _int(
            checkpoint.get("filesCompleted")
            if checkpoint.get("filesCompleted") is not None
            else manifest.get("filesCompleted")
        )
        filename = (
            checkpoint.get("filename")
            or checkpoint.get("relativePath")
            or file_cp.get("filename")
            or config.get("filename")
        )
        if files_total_i is None and filename:
            files_total_i = 1
            if (
                bytes_downloaded_i is not None
                and total_bytes_i is not None
                and total_bytes_i > 0
            ):
                files_completed_i = 1 if bytes_downloaded_i >= total_bytes_i else 0
            else:
                files_completed_i = None

        return {
            "repositoryId": checkpoint.get("repositoryId")
            or file_cp.get("repositoryId")
            or config.get("repositoryId"),
            "revision": checkpoint.get("revision")
            or file_cp.get("revision")
            or config.get("revision"),
            "filename": filename,
            "bytesDownloaded": bytes_downloaded_i,
            "bytesTotal": total_bytes_i,
            "filesTotal": files_total_i,
            "filesCompleted": files_completed_i,
            "attempts": checkpoint.get("attempts")
            if checkpoint.get("attempts") is not None
            else file_cp.get("attempts"),
            "lastHttpStatus": checkpoint.get("lastHttpStatus")
            if checkpoint.get("lastHttpStatus") is not None
            else checkpoint.get("lastStatus")
            if checkpoint.get("lastStatus") is not None
            else file_cp.get("lastStatus"),
            "rateLimitEvents": checkpoint.get("rateLimitEvents")
            if checkpoint.get("rateLimitEvents") is not None
            else file_cp.get("rateLimitEvents"),
            "etag": checkpoint.get("etag") if checkpoint.get("etag") is not None else file_cp.get("etag"),
            "bytesPerSecond": _int(checkpoint.get("bytesPerSecond")),
            "etaSeconds": _int(checkpoint.get("etaSeconds")),
        }
