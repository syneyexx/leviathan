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
from .catalog import (
    CatalogError,
    build_catalog_from_store,
    catalog_path,
    read_catalog,
    read_catalog_status,
    refresh_catalog_entry,
    write_catalog,
)
from .checkpoint import (
    BACKEND_PYTHON_STREAMING,
    BACKEND_RUST_NATIVE,
    DEFAULT_CHECKPOINT_EVERY,
    UNMEASURED as CKPT_UNMEASURED,
    build_checkpoint,
    can_resume,
    compute_input_hash,
    compute_operation_fingerprint,
    invalidate_checkpoint,
    iter_skip_then_count,
    load_checkpoint,
    normalize_backend_label,
    observability_fields,
    resolve_resume_skip,
    save_checkpoint,
    throughput_records_per_sec,
)
from .compute_planner import BackendPlan, ComputeBackend, ComputeBackendPlanner
from .contamination import scan_contamination
from .dedupe import iter_exact_dedupe_external
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
from .knowledge_identity import (
    is_legacy_ambiguous_source,
    knowledge_source_for_version,
    resolve_index_scope,
)
from .materialize import (
    iter_version_records,
    materialize_from_raw,
    materialize_from_sources,
    write_canonical_jsonl,
    write_canonical_jsonl_stream,
    write_manifest,
)
from .memory_policy import resolve_dataset_memory_policy
from .mixtures import MixtureComponent, build_mixture_manifest
from .packing_sim import simulate_packing
from .pii import scan_records_pii
from .publish import prepare_output_path, publish_atomic, reconcile_orphans
from .recovery import DatasetRecoveryAssessment, RecoveryState, default_recovery_truth
from .scratch import ScratchManager
from .semantic_enrichment import (
    build_idempotency_key,
    enrich_from_evidence,
    merge_operator_overrides,
    profile_to_metadata_patch,
)
from .semantic_profiler import BoundedDatasetEvidence, BoundedDatasetProfiler, ProfilerLimits
from .shards import ShardIngestCheckpoint, build_shard_plan, ingest_shards
from .sidecar import (
    SIDECAR_FILENAME,
    TOMBSTONE_FILENAME,
    build_sidecar_payload,
    find_sidecars_under_roots,
    read_sidecar,
    tombstone_path_for,
    write_sidecar,
    write_tombstone,
)
from .splits import iter_deterministic_split
from .store import DatasetStore, utc_now
from .tokenize_stats import compute_token_stats
from .transforms import apply_transforms_streaming
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


def _honest_storage_format(
    *,
    path: Path | str | None = None,
    detected: DetectedFormat | str | None = None,
) -> str | None:
    """Return ``jsonl`` or ``parquet`` when the on-disk format is unambiguous.

    Does not force Parquet for heterogeneous text — JSONL remains the default
    materialized representation.
    """
    if detected is not None:
        value = detected.value if isinstance(detected, DetectedFormat) else str(detected)
        value = value.strip().lower()
        if value == "parquet":
            return "parquet"
        if value in {"jsonl", "ndjson", "canonical_jsonl"}:
            return "jsonl"
    if path is not None:
        suffix = Path(path).suffix.lower()
        if suffix == ".parquet":
            return "parquet"
        if suffix in {".jsonl", ".ndjson"}:
            return "jsonl"
    return None


def _raw_version_schema(
    *,
    detected: DetectedFormat | str | None = None,
    path: Path | str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "raw", **(extra or {})}
    if detected is not None:
        fmt = detected.value if isinstance(detected, DetectedFormat) else str(detected)
        schema.setdefault("format", fmt)
    storage = _honest_storage_format(path=path, detected=detected)
    if storage:
        schema["storageFormat"] = storage
    return schema


def _cap_record_iter(records: Any, *, limit: int) -> tuple[Any, dict[str, bool]]:
    """Yield at most ``limit`` records and record whether more remained."""
    flag = {"hit": False}

    def _gen() -> Any:
        count = 0
        for rec in records:
            if count >= limit:
                flag["hit"] = True
                break
            count += 1
            yield rec

    return _gen(), flag


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
        self.datasets_recovery_auto_reindex = bool(
            getattr(ri, "datasets_recovery_auto_reindex", False)
        )
        self.datasets_recovery_max_auto_jobs = max(
            0,
            int(getattr(ri, "datasets_recovery_max_auto_jobs", None) or 8),
        )
        self.memory_policy = resolve_dataset_memory_policy(settings=self.settings)
        scratch_root = Path(self.corpus.root) / "scratch"
        self.scratch_manager = ScratchManager(
            scratch_root,
            max_scratch_bytes=self.memory_policy.spill_budget_bytes,
        )
        self._compute_planner: ComputeBackendPlanner | None = None
        self._native_runner = None

    def iter_version_records(self, version_id: str):
        """Canonical streaming access to a version's records (no full list)."""
        ver = self.get_version(version_id)
        if not ver.storage_path:
            raise DatasetError("Version has no storage", code="no_storage")
        fmt_hint = None
        if isinstance(ver.schema, dict):
            fmt_hint = ver.schema.get("storageFormat") or ver.schema.get("format")
        meta = ver.metadata if isinstance(ver.metadata, dict) else {}
        fmt_hint = fmt_hint or meta.get("storageFormat") or meta.get("detectedFormat")
        return iter_version_records(
            Path(ver.storage_path),
            max_record_bytes=self.memory_policy.max_record_bytes,
            format_hint=str(fmt_hint) if fmt_hint else None,
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
        from Data.modules.common.database_domains import knowledge_path_from_settings

        path = db_path or knowledge_path_from_settings(settings)
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
        """Create domain dataset_jobs row and link a runnable kernel job when bound.

        Option A (P0-005): when JobRuntime is bound, a QUEUED domain job is only
        accepted if kernel enqueue succeeds. Enqueue failure marks the domain job
        FAILED with a truthful execution-unavailable code and raises — never leave
        an orphan QUEUED domain row without execution authority.
        """
        job = self.store.create_job(**kwargs)
        if job.status != DatasetJobStatus.QUEUED:
            return job
        if self.jobs is None:
            # Legacy/test path: domain drain owns execution; no kernel required.
            return job
        try:
            kernel = enqueue_kernel_for_domain_job(self.jobs, job, raise_on_error=True)
        except Exception as exc:  # noqa: BLE001
            self.store.update_job(
                job.job_id,
                status=DatasetJobStatus.FAILED,
                error=redact_secrets(
                    f"[DATASET_EXECUTION_UNAVAILABLE] JobRuntime enqueue failed: {exc}"
                )[:4000],
                finished_at=utc_now(),
                phase="enqueue_failed",
            )
            raise DatasetError(
                "Dataset job accepted but JobRuntime could not enqueue execution; "
                "refusing false QUEUED success",
                code="DATASET_EXECUTION_UNAVAILABLE",
                http_status=503,
                details={
                    "datasetJobId": job.job_id,
                    "reason": "kernel_enqueue_failed",
                    "error": redact_secrets(str(exc))[:500],
                },
            ) from exc
        if kernel is None:
            self.store.update_job(
                job.job_id,
                status=DatasetJobStatus.FAILED,
                error="[DATASET_EXECUTION_UNAVAILABLE] JobRuntime enqueue returned no kernel job",
                finished_at=utc_now(),
                phase="enqueue_failed",
            )
            raise DatasetError(
                "Dataset job could not obtain a runnable JobKernel lease",
                code="DATASET_EXECUTION_UNAVAILABLE",
                http_status=503,
                details={
                    "datasetJobId": job.job_id,
                    "reason": "kernel_enqueue_returned_none",
                },
            )
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
            DatasetJobType.ENRICH_METADATA.value: self._handle_enrich_metadata,
        }

    # --- Queries ---

    def list_datasets(self, *, limit: int = 100) -> list[DatasetRecord]:
        return self.store.list_datasets(limit=limit)

    def query_datasets(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        q: str | None = None,
        status: str | None = None,
        source_type: str | None = None,
        source_scope: str | None = None,
        indexed: bool | None = None,
        detected_format: str | None = None,
        category: str | None = None,
        tags: str | None = None,
        split: str | None = None,
        sort: str = "created_at_desc",
        updated_after: str | None = None,
        updated_before: str | None = None,
        cursor: str | None = None,
        include_brain: bool = True,
        include_quality: bool = True,
    ) -> dict[str, Any]:
        """Server-side catalog page — same DatasetStore, no parallel registry."""
        from .quality_signals import quality_from_validation

        page = self.store.query_datasets(
            limit=limit,
            offset=offset,
            q=q,
            status=status,
            source_type=source_type,
            source_scope=source_scope,
            indexed=indexed,
            detected_format=detected_format,
            category=category,
            tags=tags,
            split=split,
            sort=sort,
            updated_after=updated_after,
            updated_before=updated_before,
            cursor=cursor,
        )
        items = page["items"]
        quality_map: dict[str, dict[str, Any]] = {}
        if include_quality and items:
            quality_map = self.store.latest_version_validation_map(
                [d.dataset_id for d in items]
            )

        datasets: list[dict[str, Any]] = []
        for ds in items:
            if include_brain:
                entry = self.brain_library_entry(ds)
            else:
                entry = self.public_dataset(ds)
            if include_quality:
                entry["quality"] = quality_from_validation(quality_map.get(ds.dataset_id))
            datasets.append(entry)

        next_offset = page["offset"] + len(datasets)
        return {
            "datasets": datasets,
            "total": page["total"],
            "limit": page["limit"],
            "offset": page["offset"],
            "sort": page["sort"],
            "nextOffset": next_offset if next_offset < page["total"] else None,
            "nextCursor": page.get("nextCursor"),
            "hasMore": (
                bool(page.get("nextCursor"))
                if page.get("cursor") is not None
                else next_offset < page["total"]
            ),
            "truth": {
                "totalIsFilteredCatalogCount": True,
                "pageSizeDoesNotDefineTotals": True,
                "qualityRequiresValidationEvidence": True,
                "keysetWhenCursorAndUpdatedAtDesc": True,
            },
        }

    def dataset_overview(self) -> dict[str, Any]:
        """Bounded aggregate truth for Dataset Management KPIs / storage / tags / services."""
        import shutil

        from .quality_signals import quality_from_validation

        stats = self.store.aggregate_catalog_stats()
        tags = self.store.aggregate_tag_counts(limit=24)

        # Catalog / sync semantics — derived catalog reconcile, not "page refresh".
        cat = self.catalog_status()
        catalog_valid = bool(cat.get("valid"))
        catalog_doc = cat.get("catalog") if isinstance(cat.get("catalog"), dict) else {}
        last_reconcile = catalog_doc.get("generatedAt") if catalog_valid else None
        if catalog_valid:
            catalog_label = "Gezond"
            catalog_state = "healthy"
        elif cat.get("code") == "catalog_missing" or not Path(str(cat.get("path") or "")).exists():
            catalog_label = "Geen catalogus"
            catalog_state = "missing"
        else:
            catalog_label = "Corrupt / ongeldig"
            catalog_state = "invalid"

        # Storage: prefer measured corpus version bytes + capacity from corpus root disk.
        known_bytes = int(stats["totalKnownBytes"])
        by_kind = dict(stats.get("bytesByVersionKind") or {})
        version_bytes_total = sum(int(v) for v in by_kind.values())
        # Prefer version rollup when present (includes exports/indexes materializations).
        attributable = version_bytes_total if version_bytes_total > 0 else known_bytes

        capacity_bytes: int | None = None
        free_bytes: int | None = None
        measurement_status = "partial" if stats["bytesUnmeasuredDatasets"] else "complete"
        try:
            usage = shutil.disk_usage(Path(self.corpus.root))
            capacity_bytes = int(usage.total)
            free_bytes = int(usage.free)
        except OSError:
            measurement_status = "unmeasured_capacity"
            capacity_bytes = None
            free_bytes = None

        datasets_bytes = int(by_kind.get("raw", 0)) + int(by_kind.get("materialized", 0)) + int(
            by_kind.get("transformed", 0)
        ) + int(by_kind.get("split", 0))
        export_bytes = int(by_kind.get("export", 0))
        # Indexes are tracked via dataset_indexes storage paths when present — use file size rollup if available.
        index_bytes = self._sum_index_storage_bytes()
        other_bytes = max(0, attributable - datasets_bytes - export_bytes - index_bytes)

        storage_breakdown = [
            {"id": "datasets", "label": "Datasets", "bytes": datasets_bytes},
            {"id": "indexes", "label": "Indexen", "bytes": index_bytes},
            {"id": "exports", "label": "Exports", "bytes": export_bytes},
            {"id": "other", "label": "Overig", "bytes": other_bytes},
        ]
        # Drop empty categories except datasets anchor.
        storage_breakdown = [
            row
            for row in storage_breakdown
            if row["bytes"] > 0 or row["id"] == "datasets"
        ]
        for row in storage_breakdown:
            row["pct"] = (
                round(100.0 * row["bytes"] / attributable, 1) if attributable > 0 else 0.0
            )

        services = self.dataset_services_status()

        return {
            "totalDatasets": stats["totalDatasets"],
            "totalSamples": stats["totalSamples"],
            "samplesMeasuredDatasets": stats["samplesMeasuredDatasets"],
            "samplesUnmeasuredDatasets": stats["samplesUnmeasuredDatasets"],
            "totalKnownBytes": known_bytes,
            "attributableBytes": attributable,
            "bytesMeasuredDatasets": stats["bytesMeasuredDatasets"],
            "bytesUnmeasuredDatasets": stats["bytesUnmeasuredDatasets"],
            "capacityBytes": capacity_bytes,
            "freeBytes": free_bytes,
            "usedBytes": (capacity_bytes - free_bytes) if capacity_bytes is not None and free_bytes is not None else None,
            "measurementStatus": measurement_status,
            "activeImports": stats["activeImports"],
            "runningImports": stats["runningImports"],
            "queuedImports": stats["queuedImports"],
            "validationIssues": stats["validationIssues"],
            "criticalValidationIssues": stats["criticalValidationIssues"],
            "warningValidationIssues": stats["warningValidationIssues"],
            "versionsWithValidation": stats["versionsWithValidation"],
            "datasetsWithValidation": stats.get("datasetsWithValidation", stats["versionsWithValidation"]),
            "datasetsWithoutValidation": stats.get("datasetsWithoutValidation", 0),
            "readyDatasets": stats.get("readyDatasets", 0),
            "exportVersionCount": stats["exportVersionCount"],
            "byStatus": stats["byStatus"],
            "bySourceType": stats["bySourceType"],
            "localDatasets": stats.get("localDatasets", 0),
            "externalDatasets": stats.get("externalDatasets", 0),
            "indexedDatasets": stats.get("indexedDatasets", 0),
            "notIndexedDatasets": stats.get("notIndexedDatasets", 0),
            "tagCounts": tags,
            "storageBreakdown": storage_breakdown,
            "catalogStatus": {
                "state": catalog_state,
                "label": catalog_label,
                "valid": catalog_valid,
                "lastCatalogReconcileAt": last_reconcile,
                "entryCount": catalog_doc.get("entryCount") if catalog_valid else None,
                "path": cat.get("path"),
                "truth": {
                    "catalogIsDerived": True,
                    "datasetStoreIsCanonical": True,
                    "notRemoteSyncOnline": True,
                    "lastReconcileIsNotPageRefresh": True,
                },
            },
            "services": services,
            "qualityModel": quality_from_validation(None)["truth"],
            "truth": {
                "nullRowCountIsUnmeasuredNotZero": True,
                "pageSizeDoesNotDefineTotals": True,
                "storageFromCorpusAndVersions": True,
                "capacityFromDiskUsage": capacity_bytes is not None,
                "validationIssuesFromPersistedReports": True,
            },
        }

    def _sum_index_storage_bytes(self) -> int:
        total = 0
        try:
            with self.store.connect() as conn:
                rows = conn.execute(
                    "SELECT storage_path FROM dataset_indexes WHERE storage_path IS NOT NULL"
                ).fetchall()
            for row in rows:
                path = row["storage_path"]
                if not path:
                    continue
                try:
                    p = Path(path)
                    if p.is_file():
                        total += p.stat().st_size
                    elif p.is_dir():
                        for child in p.rglob("*"):
                            if child.is_file():
                                total += child.stat().st_size
                except OSError:
                    continue
        except Exception:  # noqa: BLE001
            return 0
        return int(total)

    def dataset_services_status(self) -> list[dict[str, Any]]:
        """Project Dataset Services panel from existing architecture — no new daemons."""
        services: list[dict[str, Any]] = []

        def _pool_status(pool_id: str) -> dict[str, Any]:
            try:
                from Data.modules.workers.registry import WorkerRegistry
                from Data.modules.workers.settings import load_worker_settings

                registry = WorkerRegistry(self.store.db_path)
                registry.initialize()
                regs = registry.list(pool_id=pool_id)
                wsettings = load_worker_settings()
                desired = wsettings.desired_count(pool_id)
                ready = sum(1 for r in regs if getattr(r.state, "value", str(r.state)) == "READY")
                busy = sum(1 for r in regs if getattr(r.state, "value", str(r.state)) == "BUSY")
                if busy > 0:
                    return {
                        "state": "busy",
                        "label": "Busy",
                        "detail": f"{busy} busy / {ready} ready (desired {desired})",
                        "measured": True,
                    }
                if ready > 0:
                    return {
                        "state": "running",
                        "label": "Running",
                        "detail": f"{ready} ready (desired {desired})",
                        "measured": True,
                    }
                if desired <= 0:
                    return {
                        "state": "unavailable",
                        "label": "Unavailable",
                        "detail": "desired_count=0",
                        "measured": True,
                    }
                return {
                    "state": "offline",
                    "label": "Offline",
                    "detail": f"no live workers (desired {desired})",
                    "measured": True,
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "state": "unmeasured",
                    "label": "Unmeasured",
                    "detail": redact_secrets(str(exc))[:160],
                    "measured": False,
                }

        # Embedding Pipeline → embedding worker / knowledge embedding provider
        emb = _pool_status("embedding")
        if self.knowledge is not None:
            try:
                provider = getattr(self.knowledge, "embedding_provider", None)
                if provider is not None and hasattr(provider, "status"):
                    st = provider.status()
                    mode = (st or {}).get("mode") if isinstance(st, dict) else None
                    if mode in {"unavailable", "error", "disabled"}:
                        emb = {
                            "state": "unavailable",
                            "label": "Unavailable",
                            "detail": f"embedding provider mode={mode}",
                            "measured": True,
                        }
                    elif emb["state"] in {"offline", "unmeasured"} and mode:
                        emb = {
                            "state": "ready",
                            "label": "Ready",
                            "detail": f"provider mode={mode}",
                            "measured": True,
                        }
            except Exception:  # noqa: BLE001
                pass
        services.append(
            {
                "id": "embedding_pipeline",
                "name": "Embedding Pipeline",
                "source": "embedding worker / Knowledge embedding provider",
                **emb,
            }
        )

        # Indexing Service → dataset worker (INDEX jobs) + knowledge
        idx = _pool_status("dataset")
        services.append(
            {
                "id": "indexing_service",
                "name": "Indexing Service",
                "source": "dataset worker (INDEX) + KnowledgeStore",
                **idx,
            }
        )

        # Validation Engine → dataset worker validate capability
        services.append(
            {
                "id": "validation_engine",
                "name": "Validation Engine",
                "source": "dataset worker validate",
                **_pool_status("dataset"),
            }
        )

        # Semantic Enrichment → enrich_metadata on dataset worker
        services.append(
            {
                "id": "semantic_enrichment",
                "name": "Semantic Enrichment",
                "source": "dataset worker enrich_metadata / semantic profiler",
                **_pool_status("dataset"),
            }
        )

        # Training Connector → training control plane presence
        training_state = {
            "state": "unmeasured",
            "label": "Unmeasured",
            "detail": "training module not probed",
            "measured": False,
        }
        try:
            from Data.modules.training import store as training_store_mod  # noqa: F401

            training_state = {
                "state": "ready",
                "label": "Ready",
                "detail": "Training module importable; consumes immutable dataset versions",
                "measured": True,
            }
        except Exception as exc:  # noqa: BLE001
            training_state = {
                "state": "unavailable",
                "label": "Unavailable",
                "detail": redact_secrets(str(exc))[:160],
                "measured": True,
            }
        services.append(
            {
                "id": "training_connector",
                "name": "Training Connector",
                "source": "Training control plane / dataset version refs",
                **training_state,
            }
        )

        # Brain Sync → Knowledge/Brain availability
        brain_state = {
            "state": "unmeasured",
            "label": "Unmeasured",
            "detail": "knowledge not wired",
            "measured": False,
        }
        if self.knowledge is None:
            brain_state = {
                "state": "unavailable",
                "label": "Unavailable",
                "detail": "KnowledgeStore not attached to DatasetService",
                "measured": True,
            }
        else:
            brain_state = {
                "state": "ready",
                "label": "Ready",
                "detail": "KnowledgeStore attached; learn/index via dataset worker",
                "measured": True,
            }
        services.append(
            {
                "id": "brain_sync",
                "name": "Brain Sync",
                "source": "Brain/Knowledge dataset index integration",
                **brain_state,
            }
        )

        return services

    def get_dataset(self, dataset_id: str) -> DatasetRecord:
        ds = self.store.get_dataset(dataset_id)
        if ds is None:
            raise DatasetError("Dataset not found", code="not_found", http_status=404)
        return ds

    def public_dataset(self, dataset_id: str | DatasetRecord) -> dict[str, Any]:
        """Dataset public dict with displayName / semantic summary (backwards compatible)."""
        ds = dataset_id if isinstance(dataset_id, DatasetRecord) else self.get_dataset(dataset_id)
        return self._enrich_dataset_public(ds.public_dict(), ds)

    @staticmethod
    def _enrich_dataset_public(entry: dict[str, Any], ds: DatasetRecord | None = None) -> dict[str, Any]:
        meta = dict(entry.get("metadata") or {})
        if ds is not None and isinstance(ds.metadata, dict):
            meta = {**meta, **dict(ds.metadata)}
        semantic = meta.get("semanticProfile") if isinstance(meta.get("semanticProfile"), dict) else {}
        display_name = (
            meta.get("displayName")
            or semantic.get("displayName")
            or entry.get("name")
            or (ds.name if ds is not None else None)
        )
        entry["displayName"] = display_name
        entry["displayNameSource"] = meta.get("displayNameSource") or semantic.get("displayNameSource")
        entry["primaryCategory"] = meta.get("primaryCategory") or semantic.get("primaryCategory")
        entry["secondaryCategory"] = meta.get("secondaryCategory") or semantic.get("secondaryCategory")
        entry["semanticTags"] = list(
            semantic.get("tags") or meta.get("semanticTags") or meta.get("tags") or []
        )
        entry["semanticReviewRequired"] = bool(
            semantic.get("reviewRequired")
            if semantic.get("reviewRequired") is not None
            else meta.get("semanticReviewRequired", False)
        )
        if semantic:
            entry["semanticProfile"] = {
                "displayName": semantic.get("displayName") or display_name,
                "displayNameSource": semantic.get("displayNameSource") or entry.get("displayNameSource"),
                "primaryCategory": semantic.get("primaryCategory") or entry.get("primaryCategory"),
                "secondaryCategory": semantic.get("secondaryCategory") or entry.get("secondaryCategory"),
                "categoryPath": list(semantic.get("categoryPath") or []),
                "tags": list(semantic.get("tags") or []),
                "summary": semantic.get("summary"),
                "confidence": semantic.get("confidence"),
                "reviewRequired": bool(semantic.get("reviewRequired", False)),
                "classificationMethod": semantic.get("classificationMethod"),
            }
        return entry

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
        # Never persist raw token in config, JobStore arguments, or results.
        # A request-supplied token is stored as an ephemeral credential ref
        # that the dataset worker resolves inside its own process.
        credential_ref = "huggingface"
        if token:
            from Data.modules.provider_io.credentials import store_ephemeral_token

            credential_ref = store_ephemeral_token(token, prefix="hf")
        safe_config: dict[str, Any] = {
            "repositoryId": repo,
            "revision": revision,
            "materialize": materialize,
            "hasToken": bool(token) or bool(resolve_hf_token(None)),
            "credential_ref": credential_ref,
            "mode": "file" if legacy_file else "repository",
        }
        if legacy_file:
            safe_config["filename"] = legacy_file
        job = self._queue_domain_job(
            job_type=DatasetJobType.IMPORT_HF,
            dataset_id=ds.dataset_id,
            config=safe_config,
        )
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

    def bulk_enqueue_index(
        self,
        dataset_ids: list[str],
        *,
        rebuild: bool = False,
        max_items: int = 25,
    ) -> dict[str, Any]:
        """Bounded multi-dataset index enqueue with per-id partial failure reporting."""
        ids = [str(x).strip() for x in (dataset_ids or []) if str(x).strip()]
        if len(ids) > max_items:
            raise DatasetError(
                f"Bulk index limited to {max_items} datasets per request",
                code="bulk_limit_exceeded",
                http_status=400,
            )
        results: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        for dataset_id in ids:
            try:
                versions = self.store.list_versions(dataset_id)
                version = next(
                    (
                        v
                        for v in versions
                        if getattr(v.status, "value", str(v.status)).lower() == "ready"
                    ),
                    None,
                )
                if version is None and versions:
                    version = versions[0]
                if version is None:
                    raise DatasetError(
                        "No version available to index",
                        code="no_usable_version",
                        http_status=404,
                    )
                job = self.enqueue_index(dataset_id, version.version_id, rebuild=rebuild)
                results.append(
                    {
                        "datasetId": dataset_id,
                        "ok": True,
                        "jobId": job.job_id,
                        "job": job.public_dict(),
                    }
                )
                succeeded += 1
            except DatasetError as exc:
                failed += 1
                results.append(
                    {
                        "datasetId": dataset_id,
                        "ok": False,
                        "error": exc.public_dict(),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                results.append(
                    {
                        "datasetId": dataset_id,
                        "ok": False,
                        "error": {
                            "code": "bulk_index_failed",
                            "message": redact_secrets(str(exc))[:240],
                        },
                    }
                )
        return {
            "action": "index",
            "requested": len(ids),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
            "truth": {
                "partialFailureReported": True,
                "boundedBulk": True,
                "maxItems": max_items,
            },
        }

    def bulk_enqueue_materialize(
        self,
        dataset_ids: list[str],
        *,
        max_items: int = 25,
    ) -> dict[str, Any]:
        """Bounded multi-dataset materialize enqueue with per-id partial failure reporting."""
        ids = [str(x).strip() for x in (dataset_ids or []) if str(x).strip()]
        if len(ids) > max_items:
            raise DatasetError(
                f"Bulk materialize limited to {max_items} datasets per request",
                code="bulk_limit_exceeded",
                http_status=400,
            )
        results: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        for dataset_id in ids:
            try:
                job = self.enqueue_materialize(dataset_id)
                results.append(
                    {
                        "datasetId": dataset_id,
                        "ok": True,
                        "jobId": job.job_id,
                        "job": job.public_dict(),
                    }
                )
                succeeded += 1
            except DatasetError as exc:
                failed += 1
                results.append(
                    {
                        "datasetId": dataset_id,
                        "ok": False,
                        "error": exc.public_dict(),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                results.append(
                    {
                        "datasetId": dataset_id,
                        "ok": False,
                        "error": {
                            "code": "bulk_materialize_failed",
                            "message": redact_secrets(str(exc))[:240],
                        },
                    }
                )
        return {
            "action": "materialize",
            "requested": len(ids),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
            "truth": {
                "partialFailureReported": True,
                "boundedBulk": True,
                "maxItems": max_items,
            },
        }

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
                    schema=_raw_version_schema(
                        detected=fmt or DetectedFormat.UNKNOWN,
                        path=path_str,
                        extra={"discovered": True},
                    ),
                    metadata={
                        "pathKey": path_key,
                        "noCopy": True,
                        **(
                            {"storageFormat": sf}
                            if (sf := _honest_storage_format(path=path_str, detected=fmt))
                            else {}
                        ),
                    },
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
                schema=_raw_version_schema(
                    detected=fmt or DetectedFormat.UNKNOWN,
                    path=path_str,
                    extra={"discovered": True},
                ),
                metadata={
                    "pathKey": path_key,
                    "noCopy": True,
                    **(
                        {"storageFormat": sf}
                        if (sf := _honest_storage_format(path=path_str, detected=fmt))
                        else {}
                    ),
                },
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

    def learning_state_for_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Canonical DatasetLearningState — single Brain-readiness truth for all surfaces."""
        from .learning_state import compute_dataset_learning_state

        ds = self.get_dataset(dataset_id)
        state = compute_dataset_learning_state(
            dataset=ds,
            versions=self.store.list_versions(dataset_id),
            indexes=self.store.list_indexes(dataset_id),
            jobs=self.store.list_jobs(dataset_id=dataset_id, limit=80),
            learning_ladder=self.learning_ladder_for_dataset(dataset_id),
        )
        return state.public_dict()

    def migrate_legacy_knowledge_sources(
        self,
        *,
        dataset_id: str | None = None,
        limit: int = 5_000,
    ) -> dict[str, Any]:
        """Remap legacy ``dataset:dataset`` Knowledge rows to canonical sources.

        Uses each document's ``trust_metadata.datasetId`` / ``versionId``.
        Documents lacking that provenance are skipped — never remapped blindly
        across datasets. Safe to re-run (idempotent once sources are canonical).
        """
        from Data.modules.knowledge.store import utc_now as knowledge_utc_now

        if self.knowledge is None:
            return {
                "migrated": 0,
                "skipped": 0,
                "reason": "knowledge_unavailable",
            }
        migrated = 0
        skipped = 0
        remapped_ids: list[str] = []
        for legacy in ("dataset:dataset", "dataset"):
            docs = self.knowledge.list_documents_by_source(legacy, limit=limit)
            for doc in docs:
                trust = dict(doc.trust_metadata or {})
                did = str(trust.get("datasetId") or trust.get("dataset_id") or "")
                vid = str(trust.get("versionId") or trust.get("version_id") or "")
                if dataset_id and did and did != dataset_id:
                    skipped += 1
                    continue
                if not did or not vid:
                    skipped += 1
                    continue
                target = knowledge_source_for_version(did, vid)
                with self.knowledge.connect() as conn:
                    self.knowledge._ensure_schema(conn)
                    conn.execute(
                        "UPDATE knowledge_documents SET source = ?, updated_at = ? WHERE id = ?",
                        (target, knowledge_utc_now(), doc.document_id),
                    )
                    conn.commit()
                migrated += 1
                if len(remapped_ids) < 20:
                    remapped_ids.append(doc.document_id)
                for idx in self.store.list_indexes(did):
                    if idx.version_id == vid and (
                        not idx.knowledge_scope
                        or is_legacy_ambiguous_source(idx.knowledge_scope)
                        or idx.knowledge_scope == "dataset"
                    ):
                        self.store.update_index(idx.index_id, knowledge_scope=target)
        return {
            "migrated": migrated,
            "skipped": skipped,
            "documentIdsSample": remapped_ids,
            "truth": {
                "canonical_source": "dataset:<dataset_id>:<version_id>",
                "legacy_dataset_dataset_remapped_via_trust_metadata": True,
            },
        }

    def brain_status_for_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Map existing index/job state into Brain-ingestion truth for the UI.

        Delegates to ``learning_state_for_dataset`` so Dataset Manager, Offline
        Datasets, Agents, and Research share one canonical owner.
        """
        from .learning_state import compute_dataset_learning_state

        ds = self.get_dataset(dataset_id)
        state = compute_dataset_learning_state(
            dataset=ds,
            versions=self.store.list_versions(dataset_id),
            indexes=self.store.list_indexes(dataset_id),
            jobs=self.store.list_jobs(dataset_id=dataset_id, limit=80),
            learning_ladder=self.learning_ladder_for_dataset(dataset_id),
        )
        return state.brain_projection()

    def reconcile_stale_learning_jobs(self, *, dataset_id: str | None = None) -> list[DatasetJob]:
        """Cancel/interrupt non-rebuild INDEX jobs that are stale against a READY index.

        READY Brain index dominates: a leftover queued auto-index must not keep
        surfaces stuck on INDEXING after a successful learn.

        Traverses the full catalog in bounded pages — no permanent first-500 starvation.
        """
        from .learning_state import stale_index_jobs_to_reconcile
        from .store import utc_now

        updated: list[DatasetJob] = []
        if dataset_id:
            dataset_ids = [dataset_id]
        else:
            dataset_ids = []
            page = 200
            offset = 0
            while True:
                result = self.store.query_datasets(limit=page, offset=offset)
                items = list(result.get("items") or [])
                for d in items:
                    dataset_ids.append(d.dataset_id)
                if len(items) < page:
                    break
                offset += page
                if offset > 100_000:
                    break
        for ds_id in dataset_ids:
            indexes = self.store.list_indexes(ds_id)
            jobs = self.store.list_jobs(dataset_id=ds_id, limit=80)
            for job in stale_index_jobs_to_reconcile(indexes=indexes, jobs=jobs):
                if job.status == DatasetJobStatus.QUEUED:
                    cancelled = self.store.update_job(
                        job.job_id,
                        status=DatasetJobStatus.CANCELLED,
                        cancel_requested=True,
                        error="Reconciled: READY Brain index dominates stale non-rebuild job",
                        finished_at=utc_now(),
                        phase="stale_reconciled",
                    )
                    updated.append(cancelled)
                    continue
                # RUNNING without rebuild — interrupt so dead/stale leases cannot fake RUNNING.
                updated.append(
                    self.store.update_job(
                        job.job_id,
                        status=DatasetJobStatus.INTERRUPTED,
                        cancel_requested=True,
                        error="Reconciled: READY Brain index dominates stale non-rebuild job",
                        finished_at=utc_now(),
                        worker_pid=None,
                        phase="stale_reconciled",
                    )
                )
        return updated

    def brain_library_entry(self, ds: DatasetRecord) -> dict[str, Any]:
        entry = self._enrich_dataset_public(ds.public_dict(), ds)
        from .learning_state import compute_dataset_learning_state

        state = compute_dataset_learning_state(
            dataset=ds,
            versions=self.store.list_versions(ds.dataset_id),
            indexes=self.store.list_indexes(ds.dataset_id),
            jobs=self.store.list_jobs(dataset_id=ds.dataset_id, limit=80),
            learning_ladder=self.learning_ladder_for_dataset(ds.dataset_id),
        )
        learning = state.public_dict()
        brain = state.brain_projection()
        entry["brain"] = brain
        entry["brainStatus"] = brain["brainStatus"]
        entry["learned"] = brain["learned"]
        entry["sourceMissing"] = brain["sourceMissing"]
        entry["learningState"] = learning
        entry["canonicalState"] = learning.get("canonicalState")
        try:
            classification = self.get_dataset_classification(ds.dataset_id)
            if classification is not None:
                entry["classification"] = classification.public_dict()
        except Exception:  # noqa: BLE001
            pass
        return entry

    def get_dataset_classification(
        self, dataset_id: str, *, version_id: str | None = None
    ):
        """Return persisted trading/semantic classification if present."""
        from .trading_classification import DatasetClassification

        ds = self.get_dataset(dataset_id)
        ver = None
        if version_id:
            ver = self.get_version(version_id)
        else:
            ver = self.pick_usable_version(dataset_id)
        for blob in (
            (ver.metadata or {}).get("classification") if ver is not None else None,
            (ds.metadata or {}).get("classification"),
            (ds.provenance or {}).get("classification"),
        ):
            parsed = DatasetClassification.from_dict(blob if isinstance(blob, dict) else None)
            if parsed is not None:
                return parsed
        return None

    def ensure_dataset_classification(
        self,
        dataset_id: str,
        *,
        version_id: str | None = None,
        force: bool = False,
        model_advisory: dict[str, Any] | None = None,
    ):
        """Classify and persist if missing (or force recompute unless operator override)."""
        from .store import utc_now
        from .trading_classification import classify_trading_dataset

        existing = self.get_dataset_classification(dataset_id, version_id=version_id)
        if existing is not None and existing.operator_override and not force:
            return existing
        if existing is not None and not force and model_advisory is None:
            return existing

        ds = self.get_dataset(dataset_id)
        ver = self.get_version(version_id) if version_id else self.pick_usable_version(dataset_id)
        columns: list[str] = []
        source_path = None
        if ver is not None and ver.storage_path:
            source_path = ver.storage_path
            schema = ver.schema or {}
            if isinstance(schema.get("columns"), list):
                columns = [str(c) for c in schema["columns"]]
        if not source_path:
            source_path = ds.raw_path or ds.original_uri

        classification = classify_trading_dataset(
            name=ds.name,
            filename=ds.original_filename,
            format_name=ds.detected_format.value if ds.detected_format else None,
            columns=columns,
            metadata=dict(ds.metadata or {}),
            provenance=dict(ds.provenance or {}),
            source_path=source_path,
            source_hash=ds.content_hash or (ver.content_hash if ver else None),
            license=ds.license,
            model_advisory=model_advisory,
            classified_at=utc_now(),
        )
        self._persist_classification(dataset_id, classification, version_id=ver.version_id if ver else None)
        return classification

    def override_dataset_classification(
        self,
        dataset_id: str,
        *,
        domain: str,
        trading_kind: str | None = None,
        reason: str = "",
        version_id: str | None = None,
    ):
        """Operator override — authoritative for routing until cleared."""
        from .store import utc_now
        from .trading_classification import (
            DatasetDomain,
            TradingDatasetKind,
            apply_operator_override,
        )

        try:
            domain_e = DatasetDomain(str(domain).upper())
        except ValueError as exc:
            raise DatasetError(
                f"Invalid domain: {domain}",
                code="invalid_classification_domain",
                http_status=400,
            ) from exc
        kind_e = None
        if trading_kind:
            try:
                kind_e = TradingDatasetKind(str(trading_kind).upper())
            except ValueError as exc:
                raise DatasetError(
                    f"Invalid trading kind: {trading_kind}",
                    code="invalid_trading_kind",
                    http_status=400,
                ) from exc
        current = self.get_dataset_classification(dataset_id, version_id=version_id)
        classification = apply_operator_override(
            current,
            domain=domain_e,
            trading_kind=kind_e,
            reason=reason,
            classified_at=utc_now(),
        )
        ver = self.get_version(version_id) if version_id else self.pick_usable_version(dataset_id)
        self._persist_classification(
            dataset_id, classification, version_id=ver.version_id if ver else None
        )
        return classification

    def _persist_classification(
        self,
        dataset_id: str,
        classification,
        *,
        version_id: str | None = None,
    ) -> None:
        payload = classification.public_dict()
        ds = self.get_dataset(dataset_id)
        meta = dict(ds.metadata or {})
        meta["classification"] = payload
        prov = dict(ds.provenance or {})
        prov["classification"] = {
            "domain": payload["domain"],
            "tradingKind": payload["tradingKind"],
            "route": payload["route"],
            "method": payload["method"],
            "confidence": payload["confidence"],
            "classifiedAt": payload["classifiedAt"],
        }
        self.store.update_dataset(dataset_id, metadata=meta, provenance=prov)
        if version_id:
            ver = self.get_version(version_id)
            vmeta = dict(ver.metadata or {})
            vmeta["classification"] = payload
            self.store.update_version(version_id, metadata=vmeta)

    def classification_routing_plan(self, dataset_id: str, *, version_id: str | None = None) -> dict[str, Any]:
        """Explicit routing receipt — what pipeline owns this dataset version."""
        from .trading_classification import allows_knowledge_auto_index

        classification = self.ensure_dataset_classification(dataset_id, version_id=version_id)
        pub = classification.public_dict()
        return {
            "datasetId": dataset_id,
            "versionId": version_id,
            "classification": pub,
            "knowledgeAutoIndexAllowed": allows_knowledge_auto_index(classification),
            "marketSimIngestRecommended": pub["route"] == "MARKET_SIM_INGEST",
            "structuredPitRecommended": pub["route"] == "STRUCTURED_PIT",
            "holdForOperator": pub["route"] == "HOLD_OPERATOR",
            "truth": pub.get("truth") or {},
        }

    def list_library_datasets(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return [self.brain_library_entry(d) for d in self.store.query_datasets(limit=limit, offset=offset)["items"]]

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

    def learning_fleet_projection(self, *, limit: int = 200) -> dict[str, Any]:
        """Learned datasets + active INDEX/learn jobs with embedded dataset summary.

        Avoids frontend N+1 ``getDataset`` calls for the learning fleet panel.
        """
        safe_limit = max(1, min(int(limit), 500))
        learned = self.list_learned_datasets(limit=safe_limit)

        # Batch active INDEX jobs once, then attach dataset summaries.
        active_jobs: list[DatasetJob] = []
        for st in (DatasetJobStatus.QUEUED, DatasetJobStatus.RUNNING):
            active_jobs.extend(
                self.store.list_jobs(
                    job_type=DatasetJobType.INDEX,
                    status=st,
                    limit=250,
                )
            )
        active_jobs.sort(key=lambda j: j.created_at or "", reverse=True)

        dataset_cache: dict[str, DatasetRecord] = {}
        for job in active_jobs:
            if job.dataset_id and job.dataset_id not in dataset_cache:
                try:
                    dataset_cache[job.dataset_id] = self.get_dataset(job.dataset_id)
                except DatasetError:
                    continue

        active_out: list[dict[str, Any]] = []
        for job in active_jobs[:safe_limit]:
            payload = self.public_job(job)
            ds = dataset_cache.get(job.dataset_id or "")
            summary: dict[str, Any] | None = None
            learning_summary: dict[str, Any] | None = None
            index_stats: dict[str, Any] | None = None
            if ds is not None:
                summary = {
                    "datasetId": ds.dataset_id,
                    "name": ds.name,
                    "status": ds.status.value if hasattr(ds.status, "value") else str(ds.status),
                    "sourceType": ds.source_type.value
                    if hasattr(ds.source_type, "value")
                    else str(ds.source_type),
                    "rowCount": ds.row_count,
                    "byteSize": ds.byte_size,
                    "updatedAt": ds.updated_at,
                }
                try:
                    learning_summary = self.learning_ladder_for_dataset(ds.dataset_id)
                except DatasetError:
                    learning_summary = None
                ready_indexes = [
                    i for i in self.store.list_indexes(ds.dataset_id) if i.status == IndexStatus.READY
                ]
                index_stats = {
                    "readyCount": len(ready_indexes),
                    "chunkCount": sum(int(i.chunk_count or 0) for i in ready_indexes),
                    "indexes": [i.public_dict() for i in ready_indexes[:3]],
                }
            payload["dataset"] = summary
            payload["datasetId"] = job.dataset_id
            payload["name"] = (summary or {}).get("name")
            payload["learningState"] = learning_summary
            payload["indexStats"] = index_stats
            active_out.append(payload)

        # Embed activeJob onto learned rows when matching.
        active_by_ds: dict[str, dict[str, Any]] = {}
        for row in active_out:
            ds_id = row.get("datasetId")
            if ds_id and ds_id not in active_by_ds:
                active_by_ds[str(ds_id)] = row

        fleet_rows: list[dict[str, Any]] = []
        for entry in learned:
            ds_id = str(entry.get("datasetId") or "")
            indexes = entry.get("indexes") or []
            chunk_count = sum(int(i.get("chunkCount") or 0) for i in indexes if isinstance(i, dict))
            fleet_rows.append(
                {
                    "datasetId": ds_id,
                    "name": entry.get("name") or entry.get("displayName"),
                    "learningState": entry.get("learningState") or entry.get("brain"),
                    "activeJob": active_by_ds.get(ds_id),
                    "indexStats": {
                        "readyCount": len(indexes),
                        "chunkCount": chunk_count,
                        "indexes": indexes[:3],
                    },
                    "dataset": {
                        "datasetId": ds_id,
                        "name": entry.get("name"),
                        "status": entry.get("status"),
                        "sourceType": entry.get("sourceType"),
                        "rowCount": entry.get("rowCount"),
                        "byteSize": entry.get("byteSize"),
                        "updatedAt": entry.get("updatedAt"),
                    },
                }
            )

        # Active jobs for datasets not yet in learned list (still indexing).
        learned_ids = {r["datasetId"] for r in fleet_rows}
        for row in active_out:
            ds_id = str(row.get("datasetId") or "")
            if not ds_id or ds_id in learned_ids:
                continue
            fleet_rows.append(
                {
                    "datasetId": ds_id,
                    "name": row.get("name"),
                    "learningState": row.get("learningState"),
                    "activeJob": row,
                    "indexStats": row.get("indexStats"),
                    "dataset": row.get("dataset"),
                }
            )
            if len(fleet_rows) >= safe_limit:
                break

        return {
            "datasets": fleet_rows[:safe_limit],
            "learned": learned,
            "activeJobs": active_out,
            "total": len(fleet_rows[:safe_limit]),
            "limit": safe_limit,
            "truth": {
                "embedsDatasetSummaryToAvoidNPlusOne": True,
                "learnedMeansReadyBrainIndex": True,
                "activeJobsAreIndexQueuedOrRunning": True,
            },
        }

    def query_jobs(
        self,
        *,
        dataset_id: str | None = None,
        status: str | None = None,
        job_type: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        page = self.store.query_jobs(
            dataset_id=dataset_id,
            status=status,
            job_type=job_type,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
            offset=offset,
        )
        jobs = [self.public_job(j) for j in page["items"]]
        next_offset = page["offset"] + len(jobs)
        return {
            "jobs": jobs,
            "total": page["total"],
            "limit": page["limit"],
            "offset": page["offset"],
            "nextOffset": next_offset if next_offset < page["total"] else None,
            "hasMore": next_offset < page["total"],
        }

    def offline_brain_preflight(
        self,
        dataset_id: str,
        version_id: str,
        *,
        offline_only: bool = True,
    ) -> dict[str, Any]:
        from .offline import offline_index_preflight
        from .trading_classification import allows_knowledge_auto_index

        ds = self.get_dataset(dataset_id)
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
        # Keep preflight aligned with enqueue_learn_to_brain classification gate.
        classification = self.ensure_dataset_classification(
            dataset_id, version_id=ver.version_id
        )
        forced = bool((ds.metadata or {}).get("forceKnowledgeIndex"))
        if not allows_knowledge_auto_index(classification) and not forced:
            pf.ok = False
            pf.blockers.append(
                "CLASSIFICATION_ROUTE_BLOCKS_KNOWLEDGE "
                f"route={classification.route.value} domain={classification.domain.value}"
            )
            pf.details["classification"] = classification.public_dict()
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
        # Fail closed: market/structured trading data must not silently enter text RAG.
        classification = self.ensure_dataset_classification(dataset_id, version_id=ver.version_id)
        from .trading_classification import allows_knowledge_auto_index

        if not allows_knowledge_auto_index(classification) and not bool(
            (ds.metadata or {}).get("forceKnowledgeIndex")
        ):
            raise DatasetError(
                "Dataset classification routes away from Knowledge indexing; "
                "override with metadata.forceKnowledgeIndex or reclassify",
                code="classification_route_blocks_knowledge",
                http_status=409,
                details={
                    "route": classification.route.value,
                    "domain": classification.domain.value,
                    "tradingKind": classification.trading_kind.value
                    if classification.trading_kind
                    else None,
                },
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
            except Exception as exc:  # noqa: BLE001
                # Domain cancel is durable; record the kernel sync failure honestly
                # rather than pretending bidirectional cancel succeeded.
                cancelled = self.store.update_job(
                    job_id,
                    error=redact_secrets(
                        f"domain cancelled; kernel cancel sync failed: {exc}"
                    )[:4000],
                    phase="cancel_kernel_sync_failed",
                )
        return cancelled

    def reconcile_orphan_queued_jobs(self, *, limit: int = 100) -> list[DatasetJob]:
        """Recover QUEUED domain jobs that lack a runnable kernel lease.

        When JobRuntime is bound, every accepted QUEUED domain job must have a
        kernel job. Orphans (crash between domain insert and enqueue, or legacy
        rows) are either re-linked exactly once or marked FAILED truthfully.

        Also reconciles cancel split-brain: kernel CANCELLED/CANCEL_REQUESTED
        while domain remains non-terminal → domain CANCELLED.
        """
        if self.jobs is None:
            return []
        from Data.modules.jobs.states import JobState, TERMINAL_JOB_STATES

        recovered: list[DatasetJob] = []
        for job in self.store.list_jobs(status=DatasetJobStatus.QUEUED, limit=limit):
            kernel = self._kernel_for_domain(job.job_id)
            if kernel is not None:
                if kernel.state == JobState.CANCELLED:
                    cancelled = self.store.update_job(
                        job.job_id,
                        status=DatasetJobStatus.CANCELLED,
                        cancel_requested=True,
                        finished_at=utc_now(),
                        error="reconciled: linked kernel job CANCELLED",
                        phase="cancelled",
                        worker_pid=None,
                    )
                    recovered.append(cancelled)
                    continue
                if kernel.state == JobState.CANCEL_REQUESTED:
                    cancelled = self.store.update_job(
                        job.job_id,
                        status=DatasetJobStatus.CANCELLED,
                        cancel_requested=True,
                        finished_at=utc_now(),
                        error="reconciled: linked kernel job CANCEL_REQUESTED",
                        phase="cancelled",
                        worker_pid=None,
                    )
                    recovered.append(cancelled)
                    continue
                if kernel.state in TERMINAL_JOB_STATES and kernel.state != JobState.CANCELLED:
                    # COMPLETED/FAILED kernel with QUEUED domain is also split-brain
                    failed = self.store.update_job(
                        job.job_id,
                        status=DatasetJobStatus.FAILED
                        if kernel.state == JobState.FAILED
                        else DatasetJobStatus.COMPLETED,
                        finished_at=utc_now(),
                        error=f"reconciled: linked kernel already {kernel.state.value}",
                        phase="reconciled_terminal",
                        worker_pid=None,
                    )
                    recovered.append(failed)
                    continue
                continue
            try:
                linked = enqueue_kernel_for_domain_job(self.jobs, job, raise_on_error=True)
            except Exception as exc:  # noqa: BLE001
                failed = self.store.update_job(
                    job.job_id,
                    status=DatasetJobStatus.FAILED,
                    error=redact_secrets(
                        f"[DATASET_EXECUTION_UNAVAILABLE] orphan reconcile enqueue failed: {exc}"
                    )[:4000],
                    finished_at=utc_now(),
                    phase="orphan_enqueue_failed",
                )
                recovered.append(failed)
                continue
            if linked is None:
                failed = self.store.update_job(
                    job.job_id,
                    status=DatasetJobStatus.FAILED,
                    error="[DATASET_EXECUTION_UNAVAILABLE] orphan reconcile returned no kernel",
                    finished_at=utc_now(),
                    phase="orphan_enqueue_failed",
                )
                recovered.append(failed)
            else:
                recovered.append(job)
        return recovered

    def production_dataset_inline_forbidden(self) -> bool:
        """True when this service must not execute dataset handlers in-process.

        Isolated unit tests construct ``DatasetService`` without JobRuntime and
        may drain locally. A kernel-backed control plane (production FastAPI)
        enqueues ``dataset.process`` and refuses to run the handler itself,
        including when the dataset worker is down.
        Explicit ``LEVIATHAN_DATASET_JOBS_RUNNER=inprocess_test`` opts back in.
        """
        from Data.modules.datasets.worker import resolve_runner_mode

        if resolve_runner_mode() == "inprocess_test":
            return False
        return self.jobs is not None

    def process_jobs(self, *, max_jobs: int = 50) -> list[DatasetJob]:
        if self.production_dataset_inline_forbidden():
            raise DatasetError(
                "Dataset execution is owned by the dataset worker; refusing in-process drain",
                code="DATASET_EXECUTION_UNAVAILABLE",
                http_status=503,
                details={"owner": "dataset", "capability": "dataset.process"},
            )
        return self.runner.drain(max_jobs=max_jobs)

    def process_kernel_job(self, kernel_job_id: str) -> DatasetJob | None:
        """Execute a specific kernel job already claimed by a pool worker."""
        if self.jobs is None:
            return None
        kernel = self.jobs.store.get(kernel_job_id)
        if kernel is None:
            return None
        return self.runner.process_kernel_job(kernel)

    def reconcile(self, *, include_heavy: bool = True) -> list[DatasetJob]:
        """Reconcile job ownership. Filesystem sweeps are optional.

        Interrupted-job metadata always runs (control plane safe). Sidecar
        catalog walks and orphan prepared-file scans are heavy and belong on
        the dataset worker (``include_heavy=True``). FastAPI startup passes
        ``include_heavy=False``.
        """
        updated = self.runner.reconcile_interrupted()
        try:
            updated.extend(self.reconcile_stale_learning_jobs())
        except Exception:  # noqa: BLE001 — stale learning reconcile must not block
            pass
        try:
            updated.extend(self.reconcile_orphan_queued_jobs())
        except Exception:  # noqa: BLE001 — orphan reconcile must not block
            pass
        if not include_heavy:
            return updated
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
        try:
            self.reconcile_data_plane_orphans()
        except Exception:  # noqa: BLE001 — orphan sweep must not block job reconcile
            pass
        return updated

    def reconcile_data_plane_orphans(
        self,
        *,
        grace_seconds: int | None = None,
        max_scan: int = 10_000,
    ) -> dict[str, Any]:
        """Delete unreferenced ``.*.prepared.tmp`` (and similar) under corpus roots."""
        import os

        if grace_seconds is None:
            raw = (os.getenv("LEVIATHAN_DATASET_ORPHAN_GRACE_SECONDS") or "").strip()
            try:
                grace_seconds = int(raw) if raw else 3600
            except ValueError:
                grace_seconds = 3600
        referenced: set[str] = set()
        try:
            for ds in self.store.list_datasets(limit=5_000):
                for ver in self.store.list_versions(ds.dataset_id):
                    if ver.storage_path:
                        referenced.add(str(ver.storage_path))
        except Exception:  # noqa: BLE001
            pass
        roots = [
            Path(self.corpus.datasets_processed),
            Path(self.corpus.datasets_exports),
            Path(self.corpus.datasets_materialized),
        ]
        return reconcile_orphans(
            roots,
            referenced_paths=referenced,
            grace_seconds=max(0, int(grace_seconds)),
            max_scan=max_scan,
        )

    # --- Synchronous helpers for tests / API ---

    def import_local_sync(
        self,
        path: str,
        *,
        name: str | None = None,
        materialize: bool = True,
    ) -> dict[str, Any]:
        """Test helper. Production control plane must enqueue and return QUEUED."""
        if self.production_dataset_inline_forbidden():
            raise DatasetError(
                "Refusing synchronous dataset import in the control plane",
                code="DATASET_EXECUTION_UNAVAILABLE",
                http_status=503,
                details={"owner": "dataset"},
            )
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
        # Control-plane PII inspection is a bounded sample. A full corpus scan
        # belongs on a dataset job; this path must not claim EXACT coverage
        # once the record cap is hit.
        return scan_records_pii(
            self.iter_version_records(version_id),
            max_findings=self.memory_policy.max_findings,
            max_records=2_000,
        )

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
        meta = ds.metadata if isinstance(ds.metadata, dict) else {}
        semantic = meta.get("semanticProfile") if isinstance(meta.get("semanticProfile"), dict) else None
        display_name = meta.get("displayName") or (semantic or {}).get("displayName") or ds.name
        display_source = meta.get("displayNameSource") or (semantic or {}).get("displayNameSource")
        versions_summary = [
            {
                "versionId": v.version_id,
                "versionLabel": v.version_label,
                "status": v.status.value if hasattr(v.status, "value") else str(v.status),
                "kind": v.kind.value if hasattr(v.kind, "value") else str(v.kind),
                "contentHash": v.content_hash,
                "rowCount": v.row_count,
                "byteSize": v.byte_size,
            }
            for v in versions[:20]
        ]
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
            display_name=str(display_name) if display_name else ds.name,
            display_name_source=str(display_source) if display_source else None,
            semantic_profile=semantic,
            versions=versions_summary,
        )
        return write_sidecar(directory, payload)

    def build_bounded_profile(
        self,
        dataset_id: str,
        version_id: str,
        *,
        limits: ProfilerLimits | None = None,
    ) -> BoundedDatasetEvidence:
        """Collect bounded streaming evidence for semantic enrichment."""
        ds = self.get_dataset(dataset_id)
        ver = self.get_version(version_id)
        if ver.dataset_id != dataset_id:
            raise DatasetError(
                "Version does not belong to dataset",
                code="version_dataset_mismatch",
                http_status=400,
            )
        classification = None
        try:
            existing = self.get_dataset_classification(dataset_id, version_id=version_id)
            if existing is not None:
                classification = existing.public_dict()
        except Exception:  # noqa: BLE001
            classification = None
        files = [f.public_dict() for f in self.store.list_files(dataset_id)]
        profiler = BoundedDatasetProfiler(limits or ProfilerLimits())
        return profiler.profile(
            dataset=ds,
            version=ver,
            record_iter=self.iter_version_records(version_id) if ver.storage_path else None,
            trading_classification=classification,
            files=files,
            max_record_bytes=self.memory_policy.max_record_bytes,
        )

    def enrich_semantic_deterministic(
        self,
        dataset_id: str,
        version_id: str,
        *,
        sync_artifacts: bool = False,
    ) -> dict[str, Any]:
        """Deterministic semantic enrichment — persists profile into dataset metadata."""
        evidence = self.build_bounded_profile(dataset_id, version_id)
        profile = enrich_from_evidence(evidence, model=None, prefer_model=False)
        patch = profile_to_metadata_patch(profile)
        ds = self.get_dataset(dataset_id)
        meta = dict(ds.metadata or {})
        meta.update(patch)
        self.store.update_dataset(dataset_id, metadata=meta)
        ver = self.get_version(version_id)
        vmeta = dict(ver.metadata or {})
        vmeta["semanticProfile"] = profile.public_dict()
        self.store.update_version(version_id, metadata=vmeta)
        result = {
            "datasetId": dataset_id,
            "versionId": version_id,
            "semanticProfile": profile.public_dict(),
            "idempotencyKey": build_idempotency_key(
                dataset_id,
                version_id,
                evidence.content_hash or ds.content_hash,
            ),
        }
        if sync_artifacts:
            result["recovery"] = self.sync_recovery_artifacts(dataset_id)
        return result

    def sync_recovery_artifacts(self, dataset_id: str) -> dict[str, Any]:
        """Write sidecar + refresh derived global catalog entry/snapshot."""
        ds = self.get_dataset(dataset_id)
        sidecar_path = self.write_dataset_sidecar(dataset_id)
        versions = [v.public_dict() for v in self.store.list_versions(dataset_id)]
        try:
            catalog_doc = refresh_catalog_entry(
                self.corpus,
                ds.public_dict(),
                versions=versions,
                store=self.store,
            )
            catalog_ok = True
            catalog_error = None
        except Exception as exc:  # noqa: BLE001 — catalog is derived; never corrupt DB
            catalog_doc = None
            catalog_ok = False
            catalog_error = redact_secrets(str(exc))
        return {
            "datasetId": dataset_id,
            "sidecarPath": str(sidecar_path) if sidecar_path else None,
            "catalogPath": str(catalog_path(self.corpus)),
            "catalogOk": catalog_ok,
            "catalogError": catalog_error,
            "catalogEntryCount": (catalog_doc or {}).get("entryCount"),
            "truth": {
                "catalogIsDerived": True,
                "datasetStoreIsCanonical": True,
                "sidecarsAreRecoveryEvidence": True,
            },
        }

    def enqueue_enrich_metadata(
        self,
        dataset_id: str,
        version_id: str,
        *,
        sync_artifacts: bool = True,
    ) -> DatasetJob:
        """Queue deterministic semantic enrichment for a dataset version."""
        self.get_dataset(dataset_id)
        ver = self.get_version(version_id)
        if ver.dataset_id != dataset_id:
            raise DatasetError(
                "Version does not belong to dataset",
                code="version_dataset_mismatch",
                http_status=400,
            )
        return self._queue_domain_job(
            job_type=DatasetJobType.ENRICH_METADATA,
            dataset_id=dataset_id,
            version_id=version_id,
            config={"sync_artifacts": bool(sync_artifacts)},
        )

    def apply_semantic_override(
        self,
        dataset_id: str,
        overrides: dict[str, Any],
        *,
        version_id: str | None = None,
        sync_artifacts: bool = True,
    ) -> dict[str, Any]:
        """Operator PATCH for displayName / category / tags — precedence over model/heuristic."""
        ds = self.get_dataset(dataset_id)
        meta = dict(ds.metadata or {})
        existing = meta.get("semanticProfile") if isinstance(meta.get("semanticProfile"), dict) else {}
        if existing:
            profile = merge_operator_overrides(existing, overrides)
        else:
            from .semantic_types import DatasetCategory, DatasetSemanticProfile, DisplayNameSource

            base = DatasetSemanticProfile(
                display_name=str(overrides.get("displayName") or ds.name)[:160],
                display_name_source=DisplayNameSource.OPERATOR,
                primary_category=DatasetCategory.GENERAL,
                secondary_category=None,
                category_path=[DatasetCategory.GENERAL.value],
                tags=[],
                subjects=[],
                summary="",
                confidence=1.0,
                review_required=False,
                classification_method="OPERATOR",
                model_status="NOT_REQUESTED",
                model_provenance={},
                operator_overrides={},
                truth={"operatorOverridesWin": True},
                source_dataset_id=dataset_id,
                source_version_id=version_id,
                source_content_hash=ds.content_hash,
            )
            profile = merge_operator_overrides(base, overrides)
        patch = profile_to_metadata_patch(profile)
        meta.update(patch)
        self.store.update_dataset(dataset_id, metadata=meta)
        ver = None
        if version_id:
            ver = self.get_version(version_id)
        else:
            ver = self.pick_usable_version(dataset_id)
        if ver is not None:
            vmeta = dict(ver.metadata or {})
            vmeta["semanticProfile"] = profile.public_dict()
            self.store.update_version(ver.version_id, metadata=vmeta)
        result = {
            "datasetId": dataset_id,
            "versionId": ver.version_id if ver else None,
            "semanticProfile": profile.public_dict(),
            "dataset": self.public_dataset(dataset_id),
            "truth": {"operatorOverridesWin": True},
        }
        if sync_artifacts:
            result["recovery"] = self.sync_recovery_artifacts(dataset_id)
        return result

    def catalog_status(self) -> dict[str, Any]:
        """Soft-read derived global catalog status (never mutates DB)."""
        path = catalog_path(self.corpus)
        status = read_catalog_status(path)
        status["truth"] = {
            **default_recovery_truth(),
            **dict(status.get("truth") or {}),
        }
        return status

    def reconcile_catalog(self, *, rebuild: bool = False) -> dict[str, Any]:
        """Refresh derived catalog from DatasetStore (optional full rebuild)."""
        if rebuild:
            return self.rebuild_dataset_catalog()
        document = build_catalog_from_store(self.store, self.corpus)
        path = write_catalog(catalog_path(self.corpus), document)
        return {
            "path": str(path),
            "entryCount": document.get("entryCount"),
            "schemaVersion": document.get("schemaVersion"),
            "truth": document.get("truth"),
        }

    def assess_dataset_recovery(self, dataset_id: str) -> dict[str, Any]:
        """Typed recovery assessment. Brain state from DatasetLearningState only."""
        assessment = self._assess_dataset_recovery(dataset_id)
        return assessment.public_dict()

    def _assess_dataset_recovery(self, dataset_id: str) -> DatasetRecoveryAssessment:
        ds = self.store.get_dataset(dataset_id)
        sidecar_dir = self._dataset_dirs(dataset_id)["raw"]
        tomb = tombstone_path_for(sidecar_dir)
        if tomb.is_file() and ds is None:
            return DatasetRecoveryAssessment(
                dataset_id=dataset_id,
                state=RecoveryState.UNSUPPORTED,
                evidence_source="tombstone",
                tombstoned=True,
                detail="Tombstone present; resurrection blocked",
                truth=default_recovery_truth(),
            )

        catalog_entry = None
        catalog_ok = False
        try:
            cat = read_catalog(catalog_path(self.corpus))
            catalog_ok = True
            for entry in cat.get("entries") or []:
                if str(entry.get("datasetId") or "") == dataset_id:
                    catalog_entry = entry
                    break
        except CatalogError:
            catalog_ok = False
            catalog_entry = None

        sidecar = read_sidecar(sidecar_dir / SIDECAR_FILENAME)
        if sidecar is None and ds is not None and ds.raw_path:
            try:
                raw = Path(ds.raw_path)
                parent = raw if raw.is_dir() else raw.parent
                sidecar = read_sidecar(parent / SIDECAR_FILENAME)
            except OSError:
                sidecar = None

        # Precedence: DB → sidecar → catalog → filesystem
        evidence_source = None
        if ds is not None:
            evidence_source = "db"
        elif sidecar is not None:
            evidence_source = "sidecar"
        elif catalog_entry is not None:
            evidence_source = "catalog"
        else:
            evidence_source = "filesystem"

        display_name = None
        content_hash = None
        raw_path = None
        if ds is not None:
            meta = ds.metadata if isinstance(ds.metadata, dict) else {}
            semantic = meta.get("semanticProfile") if isinstance(meta.get("semanticProfile"), dict) else {}
            display_name = meta.get("displayName") or semantic.get("displayName") or ds.name
            content_hash = ds.content_hash
            raw_path = ds.raw_path
        if display_name is None and sidecar:
            display_name = sidecar.get("displayName") or sidecar.get("name")
            content_hash = content_hash or sidecar.get("contentHash")
            raw_path = raw_path or sidecar.get("rawPath")
        if display_name is None and catalog_entry:
            display_name = catalog_entry.get("displayName") or catalog_entry.get("name")
            content_hash = content_hash or catalog_entry.get("contentHash")
            raw_path = raw_path or catalog_entry.get("rawPath")

        source_present = False
        if raw_path:
            try:
                source_present = Path(raw_path).exists()
            except OSError:
                source_present = False
        if not source_present and ds is not None:
            files = self.store.list_files(dataset_id)
            source_present = any(Path(f.path).exists() for f in files if f.path)

        hash_ok: bool | None = None
        conflicts: list[dict[str, Any]] = []
        hashes = []
        if ds is not None and ds.content_hash:
            hashes.append(("db", ds.content_hash))
        if sidecar and sidecar.get("contentHash"):
            hashes.append(("sidecar", str(sidecar["contentHash"])))
        if catalog_entry and catalog_entry.get("contentHash"):
            hashes.append(("catalog", str(catalog_entry["contentHash"])))
        if len(hashes) >= 2:
            unique = {h for _, h in hashes}
            if len(unique) > 1:
                hash_ok = False
                conflicts.append(
                    {
                        "reason": "content_hash_conflict",
                        "hashes": {src: h for src, h in hashes},
                    }
                )
            else:
                hash_ok = True

        if tomb.is_file():
            return DatasetRecoveryAssessment(
                dataset_id=dataset_id,
                state=RecoveryState.UNSUPPORTED,
                evidence_source=evidence_source,
                source_present=source_present,
                tombstoned=True,
                conflicts=conflicts,
                display_name=display_name,
                detail="Tombstone present; dataset was deleted",
                truth=default_recovery_truth(),
            )

        if ds is None and sidecar is None and catalog_entry is None:
            return DatasetRecoveryAssessment(
                dataset_id=dataset_id,
                state=RecoveryState.UNSUPPORTED,
                evidence_source=evidence_source,
                source_present=source_present,
                detail="No DB, sidecar, or catalog evidence",
                truth={**default_recovery_truth(), "catalogReadable": catalog_ok},
            )

        if hash_ok is False:
            return DatasetRecoveryAssessment(
                dataset_id=dataset_id,
                state=RecoveryState.HASH_MISMATCH,
                evidence_source=evidence_source,
                source_present=source_present,
                content_hash_ok=False,
                conflicts=conflicts,
                display_name=display_name,
                detail="Content hash conflict across recovery evidence",
                truth=default_recovery_truth(),
            )

        if ds is not None and not source_present:
            learning = self.learning_state_for_dataset(dataset_id)
            return DatasetRecoveryAssessment(
                dataset_id=dataset_id,
                state=RecoveryState.SOURCE_MISSING,
                evidence_source="db",
                source_present=False,
                content_hash_ok=hash_ok,
                brain_learned=bool(learning.get("learned")),
                reindex_required=False,
                display_name=display_name,
                learning_canonical_state=learning.get("canonicalState"),
                detail="Catalog/DB row present but source files missing",
                truth=default_recovery_truth(),
            )

        # Brain state MUST come from DatasetLearningState — never catalog.
        brain_learned = False
        learning_canonical = None
        reindex_required = False
        if ds is not None:
            learning = self.learning_state_for_dataset(dataset_id)
            brain_learned = bool(learning.get("learned"))
            learning_canonical = learning.get("canonicalState")
            indexes = self.store.list_indexes(dataset_id)
            ready_indexes = [i for i in indexes if i.status == IndexStatus.READY]
            if not ready_indexes and not brain_learned:
                reindex_required = True
            elif not ready_indexes:
                reindex_required = True
                brain_learned = False

        metadata_restored = bool(
            (ds is not None)
            and (
                (ds.provenance or {}).get("restoredFromSidecar")
                or (ds.metadata or {}).get("restoredFromSidecar")
                or (ds.metadata or {}).get("restoredFromCatalog")
                or (ds.provenance or {}).get("restoredFromCatalog")
            )
        )

        if ds is None:
            # Evidence exists but not yet in DB — caller should reconcile.
            return DatasetRecoveryAssessment(
                dataset_id=dataset_id,
                state=RecoveryState.UNSUPPORTED,
                evidence_source=evidence_source,
                source_present=source_present,
                content_hash_ok=hash_ok,
                display_name=display_name,
                detail="Evidence present off-DB; run catalog/sidecar reconcile to restore",
                truth={
                    **default_recovery_truth(),
                    "needsReconcile": True,
                    "catalogReadable": catalog_ok,
                },
            )

        if reindex_required:
            return DatasetRecoveryAssessment(
                dataset_id=dataset_id,
                state=RecoveryState.REINDEX_REQUIRED,
                evidence_source=evidence_source,
                source_present=source_present,
                metadata_restored=metadata_restored,
                content_hash_ok=hash_ok if hash_ok is not None else True,
                brain_learned=False,
                reindex_required=True,
                display_name=display_name,
                learning_canonical_state=learning_canonical,
                detail="Metadata present; Brain index missing — REINDEX_REQUIRED ≠ LEARNED",
                truth=default_recovery_truth(),
            )

        if metadata_restored:
            return DatasetRecoveryAssessment(
                dataset_id=dataset_id,
                state=RecoveryState.METADATA_RESTORED,
                evidence_source=evidence_source,
                source_present=source_present,
                metadata_restored=True,
                content_hash_ok=hash_ok if hash_ok is not None else True,
                brain_learned=brain_learned,
                reindex_required=False,
                display_name=display_name,
                learning_canonical_state=learning_canonical,
                detail="Restored from sidecar/catalog evidence",
                truth=default_recovery_truth(),
            )

        return DatasetRecoveryAssessment(
            dataset_id=dataset_id,
            state=RecoveryState.READY,
            evidence_source="db",
            source_present=source_present,
            metadata_restored=False,
            content_hash_ok=hash_ok if hash_ok is not None else True,
            brain_learned=brain_learned,
            reindex_required=False,
            display_name=display_name,
            learning_canonical_state=learning_canonical,
            detail="Dataset present in DatasetStore with source available",
            truth=default_recovery_truth(),
        )

    def enqueue_missing_semantic_profiles(self, *, limit: int = 25) -> dict[str, Any]:
        """Bounded backfill: enqueue enrich_metadata for datasets lacking semanticProfile.

        P2-002: paginate DatasetStore via query_datasets cursor pages instead of
        ``list_datasets(limit=10_000)``.
        """
        limit = max(1, min(int(limit), 200))
        enqueued: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        page_size = 100
        cursor: str | None = None
        pages = 0
        scanned = 0
        while len(enqueued) < limit:
            page = self.store.query_datasets(
                limit=page_size,
                cursor=cursor,
                sort="updated_at_desc",
            )
            items = list(page.get("items") or [])
            pages += 1
            if not items:
                break
            for ds in items:
                scanned += 1
                if len(enqueued) >= limit:
                    break
                meta = ds.metadata if isinstance(ds.metadata, dict) else {}
                semantic = meta.get("semanticProfile")
                if isinstance(semantic, dict) and semantic.get("displayName") and semantic.get("primaryCategory"):
                    skipped.append({"datasetId": ds.dataset_id, "reason": "already_enriched"})
                    continue
                ver = self.pick_usable_version(ds.dataset_id)
                if ver is None or not ver.storage_path:
                    skipped.append({"datasetId": ds.dataset_id, "reason": "no_usable_version"})
                    continue
                job = self.enqueue_enrich_metadata(ds.dataset_id, ver.version_id, sync_artifacts=True)
                enqueued.append(
                    {
                        "datasetId": ds.dataset_id,
                        "versionId": ver.version_id,
                        "jobId": job.job_id,
                    }
                )
            cursor = page.get("nextCursor")
            if not cursor:
                break
            # Hard safety against pathological catalogs.
            if pages >= 10_000:
                break
        return {
            "enqueued": enqueued,
            "enqueuedCount": len(enqueued),
            "skippedCount": len(skipped),
            "skipped": skipped[:50],
            "limit": limit,
            "scanned": scanned,
            "pages": pages,
            "truth": {
                "boundedBackfill": True,
                "deterministicEnrichment": True,
                "catalogPaginated": True,
            },
        }

    def rebuild_dataset_catalog(self) -> dict[str, Any]:
        """Full derived catalog rebuild from DatasetStore (never writes to DB)."""
        document = build_catalog_from_store(self.store, self.corpus)
        path = write_catalog(catalog_path(self.corpus), document)
        return {
            "path": str(path),
            "entryCount": document.get("entryCount"),
            "schemaVersion": document.get("schemaVersion"),
            "truth": document.get("truth"),
        }

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
        """Restore catalog rows from validated sidecars + derived catalog under allowed roots.

        Precedence: existing DB wins; sidecars restore missing rows; catalog fills gaps;
        tombstones still block resurrection. Brain state is never taken from catalog.
        """
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
        catalog_restored = 0
        assessments: list[dict[str, Any]] = []
        auto_reindex_jobs: list[str] = []

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
                    if p.is_file() and p.name not in {SIDECAR_FILENAME, TOMBSTONE_FILENAME}
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
                semantic = sidecar.get("semanticProfile") if isinstance(sidecar.get("semanticProfile"), dict) else None
                meta: dict[str, Any] = {
                    "restoredFromSidecar": True,
                    "pathKey": normalize_path_key(raw_path),
                    "sourcePath": raw_path,
                }
                if sidecar.get("displayName"):
                    meta["displayName"] = sidecar["displayName"]
                if sidecar.get("displayNameSource"):
                    meta["displayNameSource"] = sidecar["displayNameSource"]
                if semantic:
                    meta["semanticProfile"] = semantic
                    meta["primaryCategory"] = semantic.get("primaryCategory")
                    meta["semanticTags"] = list(semantic.get("tags") or [])
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
                    metadata=meta,
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
                        metadata={"restoredFromSidecar": True, "semanticProfile": semantic},
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
            # Fill missing semantic fields from sidecar without clobbering operator locks.
            if sidecar.get("displayName") and not meta.get("displayName"):
                meta["displayName"] = sidecar["displayName"]
            if isinstance(sidecar.get("semanticProfile"), dict) and not meta.get("semanticProfile"):
                meta["semanticProfile"] = sidecar["semanticProfile"]
                meta.setdefault("primaryCategory", sidecar["semanticProfile"].get("primaryCategory"))
            self.store.update_dataset(existing.dataset_id, metadata=meta)
            updated += 1

        # Catalog gap-fill: restore entries missing from DB when source/sidecar evidence exists.
        try:
            cat_status = read_catalog_status(catalog_path(self.corpus))
            if cat_status.get("valid"):
                for entry in cat_status["catalog"].get("entries") or []:
                    ds_id = str(entry.get("datasetId") or "").strip()
                    if not ds_id or self.store.get_dataset(ds_id) is not None:
                        continue
                    raw_rel = entry.get("rawPath")
                    raw_candidate = None
                    if raw_rel:
                        cand = Path(self.corpus.root) / str(raw_rel)
                        if not cand.exists():
                            cand = Path(str(raw_rel))
                        raw_candidate = cand if cand.exists() else None
                    # Prefer sidecar under datasets_raw/{id}
                    raw_dir = self.corpus.datasets_raw / ds_id
                    if tombstone_path_for(raw_dir).is_file():
                        skipped_tombstone += 1
                        continue
                    sc = read_sidecar(raw_dir / SIDECAR_FILENAME)
                    if sc is None and raw_candidate is not None:
                        parent = raw_candidate if raw_candidate.is_dir() else raw_candidate.parent
                        if tombstone_path_for(parent).is_file():
                            skipped_tombstone += 1
                            continue
                        sc = read_sidecar(parent / SIDECAR_FILENAME)
                    if sc is None and raw_candidate is None:
                        conflicts.append(
                            {
                                "datasetId": ds_id,
                                "reason": "catalog_entry_source_missing",
                                "rawPath": raw_rel,
                            }
                        )
                        continue
                    name = str((sc or {}).get("name") or entry.get("name") or ds_id)
                    raw_path = str(
                        (sc or {}).get("rawPath")
                        or (raw_candidate if raw_candidate else raw_dir)
                    )
                    source_type_raw = (sc or {}).get("sourceType") or entry.get("sourceType") or "local"
                    try:
                        source_type = SourceType(str(source_type_raw))
                    except ValueError:
                        source_type = SourceType.LOCAL
                    semantic = None
                    if sc and isinstance(sc.get("semanticProfile"), dict):
                        semantic = sc["semanticProfile"]
                    meta = {
                        "restoredFromCatalog": True,
                        "restoredFromSidecar": bool(sc),
                        "pathKey": normalize_path_key(raw_path),
                        "sourcePath": raw_path,
                        "displayName": (sc or {}).get("displayName") or entry.get("displayName") or name,
                        "displayNameSource": (sc or {}).get("displayNameSource")
                        or entry.get("displayNameSource"),
                        "primaryCategory": entry.get("primaryCategory"),
                        "semanticTags": list(entry.get("tags") or []),
                    }
                    if semantic:
                        meta["semanticProfile"] = semantic
                    self.store.create_dataset(
                        name=name,
                        source_type=source_type,
                        description="Restored from derived catalog + recovery evidence",
                        original_filename=(sc or {}).get("originalFilename")
                        or entry.get("originalFilename"),
                        original_uri=(sc or {}).get("originalUri"),
                        provenance={
                            "restoredFromCatalog": True,
                            "restoredFromSidecar": bool(sc),
                        },
                        metadata=meta,
                        status=DatasetStatus.RAW,
                        dataset_id=ds_id,
                    )
                    self.store.update_dataset(
                        ds_id,
                        raw_path=raw_path,
                        content_hash=(sc or {}).get("contentHash") or entry.get("contentHash"),
                        byte_size=(sc or {}).get("byteSize") or entry.get("byteSize"),
                        row_count=(sc or {}).get("rowCount") or entry.get("rowCount"),
                    )
                    if Path(raw_path).exists():
                        self.store.create_version(
                            dataset_id=ds_id,
                            version_label=str((sc or {}).get("versionLabel") or "catalog-restored"),
                            kind=VersionKind.RAW,
                            status=VersionStatus.READY,
                            storage_path=raw_path,
                            schema={"type": "raw", "restoredFromCatalog": True},
                            metadata={"restoredFromCatalog": True, "semanticProfile": semantic},
                        )
                    created += 1
                    catalog_restored += 1
                    restored_ids.append(ds_id)
            elif cat_status.get("valid") is False:
                conflicts.append(
                    {
                        "reason": "corrupt_catalog",
                        "code": cat_status.get("code"),
                        "error": cat_status.get("error"),
                        "path": cat_status.get("path"),
                    }
                )
        except Exception as exc:  # noqa: BLE001 — catalog is derived; never corrupt DB
            conflicts.append({"reason": "catalog_reconcile_error", "error": redact_secrets(str(exc))})

        # Assess restored / known datasets; optionally enqueue reindex (default off).
        for ds_id in restored_ids[:50]:
            try:
                assessment = self.assess_dataset_recovery(ds_id)
                assessments.append(assessment)
                if (
                    self.datasets_recovery_auto_reindex
                    and assessment.get("reindexRequired")
                    and len(auto_reindex_jobs) < self.datasets_recovery_max_auto_jobs
                ):
                    ver = self.pick_usable_version(ds_id)
                    if ver is not None:
                        job = self.enqueue_index(ds_id, ver.version_id)
                        auto_reindex_jobs.append(job.job_id)
            except DatasetError:
                continue

        return {
            "scanned": len(found),
            "created": created,
            "updated": updated,
            "skippedTombstone": skipped_tombstone,
            "catalogRestored": catalog_restored,
            "conflicts": conflicts,
            "restoredDatasetIds": restored_ids,
            "assessments": assessments,
            "autoReindexJobIds": auto_reindex_jobs,
            "truth": {
                "sidecar_does_not_replace_catalog": True,
                "tombstones_block_auto_restore": True,
                "allowed_roots_only": True,
                "no_invented_names_or_provenance": True,
                "recoveryPrecedence": ["db", "sidecar", "catalog", "filesystem"],
                "brainStateNotFromCatalog": True,
                "catalogIsDerived": True,
                "autoReindexDefaultOff": not self.datasets_recovery_auto_reindex,
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
            schema=_raw_version_schema(detected=detection.format, path=dest),
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
        """Resolve HF credentials inside the execution process.

        Job config may carry ``credential_ref`` (including ``ephemeral:``)
        but never the raw token. Environment/settings remain the durable source.
        """
        ref = str((job.config or {}).get("credential_ref") or "").strip()
        if ref.startswith("ephemeral:"):
            from Data.modules.provider_io.credentials import resolve_credential

            resolved = resolve_credential(ref)
            if resolved.api_key:
                return resolved.api_key
        legacy = self._hf_tokens.pop(job.job_id, None)
        if legacy:
            return resolve_hf_token(legacy)
        return resolve_hf_token(None)

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
            schema=_raw_version_schema(detected=detection.format, path=downloaded.path),
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
        repo_extra: dict[str, Any] = {
            "formats": sorted(formats_seen),
            "fileCount": len(sources),
        }
        # Honest storageFormat only when the repository is unambiguously one plane.
        if formats_seen == {"parquet"}:
            repo_extra["storageFormat"] = "parquet"
        elif formats_seen and formats_seen <= {"jsonl", "ndjson"}:
            repo_extra["storageFormat"] = "jsonl"
        raw_version = self.store.create_version(
            dataset_id=job.dataset_id,
            version_label="raw-v1",
            kind=VersionKind.RAW,
            status=VersionStatus.READY,
            storage_path=str(raw_root),
            schema={"type": "raw", **repo_extra},
            metadata={
                "files": [s["relativePath"] for s in sources],
                **({"storageFormat": repo_extra["storageFormat"]} if "storageFormat" in repo_extra else {}),
            },
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
            # Materialize always publishes canonical JSONL (never force Parquet).
            schema={**canonical_schema_dict(), "storageFormat": "jsonl"},
            metadata={"storageFormat": "jsonl"},
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
        # Classify after materialize so schema/path signals are available.
        try:
            classification = self.ensure_dataset_classification(
                dataset_id, version_id=version.version_id, force=False
            )
            result["classification"] = classification.public_dict()
        except Exception as exc:  # noqa: BLE001 — classification must not fail materialize
            result["classificationError"] = str(exc)[:300]
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
        # Trading classification routing — do not silently RAG market/structured data.
        try:
            classification = self.ensure_dataset_classification(dataset_id, version_id=version_id)
        except Exception:  # noqa: BLE001
            classification = self.get_dataset_classification(dataset_id, version_id=version_id)
        from .trading_classification import allows_knowledge_auto_index

        if classification is not None and not allows_knowledge_auto_index(classification):
            return {
                "enqueued": False,
                "reason": "routed_away_from_knowledge",
                "route": classification.route.value,
                "domain": classification.domain.value,
                "tradingKind": classification.trading_kind.value if classification.trading_kind else None,
                "truth": {
                    "contamination_quality_gates_best_effort": True,
                    "classification_blocks_wrong_pipeline": True,
                },
            }
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

    def _write_derived_version_stream(
        self,
        *,
        dataset_id: str,
        parent: DatasetVersion,
        label: str,
        kind: VersionKind,
        records,
        lineage_extra: list[dict[str, Any]] | None = None,
        split: dict[str, Any] | None = None,
        token_stats: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DatasetVersion:
        """Stream-write a derived version from an iterable (no full corpus list required)."""
        dirs = self._dataset_dirs(dataset_id)
        dest = dirs["processed"] / f"{label}.jsonl"
        outcome = write_canonical_jsonl_stream(records, dest, validate=False)
        content_hash = outcome["contentHash"]
        byte_size = outcome["byteSize"]
        row_count = outcome["rowCount"]
        lineage = list(parent.transform_lineage) + list(lineage_extra or [])
        version = self.store.create_version(
            dataset_id=dataset_id,
            version_label=label,
            kind=kind,
            parent_version_id=parent.version_id,
            status=VersionStatus.READY,
            storage_path=str(dest),
            schema={**canonical_schema_dict(), "storageFormat": "jsonl"},
            transform_lineage=lineage,
            metadata=metadata,
        )
        val_report = validation
        if val_report is None:
            val_report = validate_records(
                iter_version_records(
                    dest,
                    max_record_bytes=self.memory_policy.max_record_bytes,
                )
            )
        self.store.update_version(
            version.version_id,
            content_hash=content_hash,
            byte_size=byte_size,
            row_count=row_count,
            split=split or {},
            token_stats=token_stats or {},
            validation=val_report,
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
        return self._write_derived_version_stream(
            dataset_id=dataset_id,
            parent=parent,
            label=label,
            kind=kind,
            records=records,
            lineage_extra=lineage_extra,
            split=split,
            token_stats=token_stats,
            validation=validation,
            metadata=metadata,
        )

    def _compute_backend_planner(self) -> ComputeBackendPlanner:
        if self._compute_planner is None:
            self._compute_planner = ComputeBackendPlanner(
                policy=self.memory_policy,
                settings=self.settings,
            )
        return self._compute_planner

    def _native_compute_runner(self):
        from Data.modules.workers.native_compute import NativeComputeRunner

        if self._native_runner is None:
            self._native_runner = NativeComputeRunner()
        return self._native_runner

    def _scratch_root_for_job(self, job: DatasetJob) -> Path | None:
        try:
            return self.scratch_manager.open_session(job.job_id).root
        except Exception:  # noqa: BLE001
            return None

    def _begin_streaming_checkpoint(
        self,
        job: DatasetJob,
        *,
        operation: str,
        input_path: Path,
        options: dict[str, Any] | None = None,
        input_hash: str | None = None,
        backend: str = BACKEND_PYTHON_STREAMING,
    ) -> tuple[Any, Path | None, int, bool]:
        digest = input_hash or compute_input_hash(input_path)
        fingerprint = compute_operation_fingerprint(
            input_hash=digest, operation=operation, options=options
        )
        root = self._scratch_root_for_job(job)
        existing = load_checkpoint(root) if root is not None else None
        if existing is not None and existing.input_hash and existing.input_hash != digest:
            if root is not None:
                invalidate_checkpoint(root)
            existing = None
        skip, resumed = resolve_resume_skip(
            existing, fingerprint=fingerprint, input_hash=digest
        )
        if existing is not None and not can_resume(
            existing, fingerprint=fingerprint, input_hash=digest
        ):
            if root is not None:
                invalidate_checkpoint(root)
            skip, resumed = 0, False
        ckpt = build_checkpoint(
            input_hash=digest,
            operation=operation,
            options=options,
            phase="streaming",
            records_processed=skip if resumed else 0,
            backend=backend,
            memory_budget=self.memory_policy.memory_budget_bytes,
            spill_bytes=CKPT_UNMEASURED,
            peak_memory=CKPT_UNMEASURED,
            throughput=CKPT_UNMEASURED,
            resumed=resumed,
        )
        if root is not None:
            save_checkpoint(root, ckpt)
        self.store.update_job(
            job.job_id,
            phase=ckpt.phase,
            checkpoint={**(job.checkpoint or {}), "streaming": ckpt.to_dict()},
            progress=0.05 if not resumed else min(0.95, 0.05 + skip * 1e-6),
        )
        return ckpt, root, skip, resumed

    def _persist_streaming_progress(
        self,
        job: DatasetJob,
        ckpt: Any,
        root: Path | None,
        *,
        records_processed: int,
        phase: str | None = None,
        started_at: float | None = None,
    ) -> None:
        import time as _time

        ckpt.records_processed = int(records_processed)
        if phase:
            ckpt.phase = phase
        if started_at is not None:
            elapsed_ms = max(0.0, (_time.monotonic() - started_at) * 1000.0)
            ckpt.duration_ms = elapsed_ms
            ckpt.throughput = throughput_records_per_sec(records_processed, elapsed_ms)
        if root is not None:
            save_checkpoint(root, ckpt)
        progress = min(0.95, 0.05 + (records_processed / max(records_processed + 1, 1)) * 0.9)
        self.store.update_job(
            job.job_id,
            phase=ckpt.phase,
            progress=progress,
            checkpoint={**(job.checkpoint or {}), "streaming": ckpt.to_dict()},
        )

    def _finish_streaming_checkpoint(
        self,
        job: DatasetJob,
        ckpt: Any,
        root: Path | None,
        *,
        records_processed: int,
        phase: str = "done",
        started_at: float | None = None,
        peak_memory: int | str | None = None,
        spill_bytes: int | str | None = None,
    ) -> dict[str, Any]:
        import time as _time

        ckpt.records_processed = int(records_processed)
        ckpt.phase = phase
        if started_at is not None:
            elapsed_ms = max(0.0, (_time.monotonic() - started_at) * 1000.0)
            ckpt.duration_ms = elapsed_ms
            ckpt.throughput = throughput_records_per_sec(records_processed, elapsed_ms)
        if peak_memory is not None:
            ckpt.peak_memory = peak_memory
        if spill_bytes is not None:
            ckpt.spill_bytes = spill_bytes
        if root is not None:
            save_checkpoint(root, ckpt)
        obs = observability_fields(
            backend=ckpt.backend,
            phase=ckpt.phase,
            records_processed=ckpt.records_processed,
            peak_memory=ckpt.peak_memory,
            memory_budget=ckpt.memory_budget,
            spill_bytes=ckpt.spill_bytes,
            throughput=ckpt.throughput,
            duration_ms=ckpt.duration_ms,
            resumed=ckpt.resumed,
        )
        self.store.update_job(
            job.job_id,
            phase=phase,
            checkpoint={**(job.checkpoint or {}), "streaming": ckpt.to_dict()},
        )
        return obs

    @staticmethod
    def _observability_from_native(
        *,
        plan: BackendPlan,
        native_info: dict[str, Any] | None,
        fallback_reason: str | None,
        phase: str,
    ) -> dict[str, Any]:
        receipt = {}
        if native_info and isinstance(native_info.get("receipt"), dict):
            receipt = native_info["receipt"]
        backend = (
            BACKEND_RUST_NATIVE
            if native_info
            else normalize_backend_label(plan.backend.value) or BACKEND_PYTHON_STREAMING
        )
        records = receipt.get("recordsOut")
        if records is None:
            records = receipt.get("recordsIn")
        peak = receipt.get("peakRssBytes")
        spill = receipt.get("spillBytes")
        duration = receipt.get("durationMs")
        return observability_fields(
            backend=backend,
            phase=phase,
            records_processed=int(records) if records is not None else None,
            peak_memory=peak if peak is not None else CKPT_UNMEASURED,
            memory_budget=CKPT_UNMEASURED,
            spill_bytes=spill if spill is not None else CKPT_UNMEASURED,
            throughput=throughput_records_per_sec(
                int(records or 0),
                float(duration) if duration is not None else None,
            )
            if records is not None and duration is not None
            else CKPT_UNMEASURED,
            duration_ms=duration if duration is not None else CKPT_UNMEASURED,
            fallback_reason=fallback_reason,
        )

    def _plan_compute_backend(
        self,
        operation: str,
        *,
        input_path: str | Path | None = None,
        input_bytes: int | None = None,
        force_backend: str | None = None,
    ) -> BackendPlan:
        return self._compute_backend_planner().plan(
            operation,
            input_path=input_path,
            input_bytes=input_bytes,
            force_backend=force_backend,
        )

    def _semantic_metadata_for_derived(
        self,
        parent: DatasetVersion,
        *,
        content_preserving: bool,
        op_name: str,
    ) -> dict[str, Any]:
        """Copy parent semantic profile for content-preserving ops; else mark enrichment."""
        parent_meta = dict(parent.metadata or {})
        parent_semantic = parent_meta.get("semanticProfile")
        if not isinstance(parent_semantic, dict):
            ds = self.store.get_dataset(parent.dataset_id)
            if ds is not None:
                ds_meta = ds.metadata if isinstance(ds.metadata, dict) else {}
                parent_semantic = ds_meta.get("semanticProfile")
        out: dict[str, Any] = {
            "parentVersionId": parent.version_id,
            "derivedOperation": op_name,
        }
        if content_preserving and isinstance(parent_semantic, dict):
            out["semanticProfile"] = dict(parent_semantic)
            out["semanticCopiedFromParent"] = True
            out["enrichmentEligible"] = False
        else:
            out["enrichmentEligible"] = True
            out["semanticNeedsEnrichment"] = True
            if isinstance(parent_semantic, dict):
                # Keep display hints but flag for re-analysis.
                out["semanticProfileInherited"] = {
                    "displayName": parent_semantic.get("displayName"),
                    "primaryCategory": parent_semantic.get("primaryCategory"),
                    "tags": list(parent_semantic.get("tags") or [])[:8],
                }
        return out

    def _try_native_operation(
        self,
        *,
        job: DatasetJob,
        operation: str,
        input_path: Path,
        dest: Path,
        options: dict[str, Any] | None = None,
        force_backend: str | None = None,
    ) -> tuple[dict[str, Any] | None, BackendPlan]:
        """Attempt Rust native path. Returns (publish_info|None, plan).

        On success: temporary output verified + atomically published to dest.
        On failure/unavailable: returns (None, plan) with fallbackReason set.
        """
        plan = self._plan_compute_backend(
            operation,
            input_path=input_path,
            force_backend=force_backend or (job.config or {}).get("forceBackend"),
        )
        if plan.backend != ComputeBackend.RUST_NATIVE:
            return None, plan

        runner = self._native_compute_runner()
        if not runner.available:
            return None, BackendPlan(
                backend=ComputeBackend.PYTHON_STREAMING,
                operation=operation,
                native_mode=plan.native_mode,
                input_bytes=plan.input_bytes,
                rust_threshold_bytes=plan.rust_threshold_bytes,
                native_status=plan.native_status,
                fallback_reason=plan.fallback_reason or "native_unavailable",
                detail=runner.capabilities().detail,
            )

        tmp = prepare_output_path(dest)
        allowed = [
            str(Path(self.corpus.root).resolve()),
            str(Path(input_path).resolve().parent),
            str(Path(dest).resolve().parent),
        ]
        limits = {
            "memoryBytes": self.memory_policy.memory_budget_bytes,
            "batchRows": self.memory_policy.batch_rows,
            "maxRecordBytes": self.memory_policy.max_record_bytes,
            "threads": self.memory_policy.thread_limit,
            "spillBytes": self.memory_policy.spill_budget_bytes,
        }
        work_dir = None
        try:
            session = self.scratch_manager.open_session(job.job_id)
            work_dir = session.root / "native"
            ensure_dir(work_dir)
        except Exception:  # noqa: BLE001
            work_dir = None

        # W169: poll domain cancel into cancel_event so NativeComputeRunner kills the Rust child.
        import threading

        cancel_event = threading.Event()

        def _watch_cancel() -> None:
            while not cancel_event.wait(0.05):
                try:
                    if self.runner.is_cancel_requested(job.job_id):
                        cancel_event.set()
                        return
                except Exception:  # noqa: BLE001
                    return

        watcher = threading.Thread(
            target=_watch_cancel,
            name=f"native-cancel-{job.job_id[:8]}",
            daemon=True,
        )
        watcher.start()
        try:
            result = runner.run(
                task_id=f"{job.job_id}:{operation}",
                operation=operation,
                input_path=input_path,
                temporary_path=tmp,
                limits=limits,
                options=options or {},
                content_hash=None,
                allowed_roots=allowed,
                work_dir=work_dir,
                cancel_event=cancel_event,
            )
        except Exception as exc:  # noqa: BLE001
            cancel_event.set()
            tmp.unlink(missing_ok=True)
            return None, BackendPlan(
                backend=ComputeBackend.PYTHON_STREAMING,
                operation=operation,
                native_mode=plan.native_mode,
                input_bytes=plan.input_bytes,
                rust_threshold_bytes=plan.rust_threshold_bytes,
                native_status=plan.native_status,
                fallback_reason=f"native_exception:{type(exc).__name__}",
                detail=redact_secrets(str(exc))[:500],
            )
        finally:
            cancel_event.set()

        if result.error_code == "NATIVE_CANCELLED" or self.runner.is_cancel_requested(job.job_id):
            tmp.unlink(missing_ok=True)
            raise DatasetError("cancelled", code="cancelled", http_status=409)

        verified = runner.verify_output(result, temporary_path=tmp)
        if not verified.get("ok"):
            tmp.unlink(missing_ok=True)
            return None, BackendPlan(
                backend=ComputeBackend.PYTHON_STREAMING,
                operation=operation,
                native_mode=plan.native_mode,
                input_bytes=plan.input_bytes,
                rust_threshold_bytes=plan.rust_threshold_bytes,
                native_status=plan.native_status,
                fallback_reason=str(verified.get("errorCode") or result.error_code or "native_verify_failed"),
                detail=str(verified.get("errorMessage") or result.error_message or "")[:500],
            )

        try:
            published = publish_atomic(
                tmp,
                dest,
                expected_hash=str(verified["contentHash"]),
            )
        except DatasetError as exc:
            tmp.unlink(missing_ok=True)
            return None, BackendPlan(
                backend=ComputeBackend.PYTHON_STREAMING,
                operation=operation,
                native_mode=plan.native_mode,
                input_bytes=plan.input_bytes,
                rust_threshold_bytes=plan.rust_threshold_bytes,
                native_status=plan.native_status,
                fallback_reason=exc.code or "native_publish_failed",
                detail=exc.message[:500] if hasattr(exc, "message") else str(exc)[:500],
            )

        info = {
            **published,
            "recordsOut": verified.get("recordsOut"),
            "receipt": verified.get("receipt"),
            "backend": ComputeBackend.RUST_NATIVE.value,
            "backendPlan": plan.public_dict(),
            "memoryEnforcement": getattr(result, "memory_enforcement", None)
            or (verified.get("receipt") or {}).get("memoryEnforcement")
            or self.memory_policy.enforcement,
        }
        return info, plan

    def _commit_derived_version_from_file(
        self,
        *,
        dataset_id: str,
        parent: DatasetVersion,
        label: str,
        kind: VersionKind,
        dest: Path,
        content_hash: str,
        byte_size: int,
        row_count: int | None,
        lineage_extra: list[dict[str, Any]] | None = None,
        split: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        backend_info: dict[str, Any] | None = None,
    ) -> DatasetVersion:
        """Create BUILDING version, commit metadata, then mark READY (never READY early)."""
        lineage = list(parent.transform_lineage) + list(lineage_extra or [])
        meta = dict(metadata or {})
        if backend_info:
            meta["computeBackend"] = backend_info.get("backend")
            meta["backendPlan"] = backend_info.get("backendPlan")
            meta["nativeReceipt"] = {
                k: backend_info.get("receipt", {}).get(k)
                for k in (
                    "protocolVersion",
                    "taskId",
                    "operation",
                    "status",
                    "recordsIn",
                    "recordsOut",
                    "durationMs",
                    "contentHash",
                )
                if isinstance(backend_info.get("receipt"), dict)
            }
        version = self.store.create_version(
            dataset_id=dataset_id,
            version_label=label,
            kind=kind,
            parent_version_id=parent.version_id,
            status=VersionStatus.BUILDING,
            storage_path=str(dest),
            schema={**canonical_schema_dict(), "storageFormat": "jsonl"},
            transform_lineage=lineage,
            metadata=meta,
        )
        val_report = validate_records(
            iter_version_records(
                dest,
                max_record_bytes=self.memory_policy.max_record_bytes,
            )
        )
        # Metadata commit BEFORE READY.
        self.store.update_version(
            version.version_id,
            content_hash=content_hash,
            byte_size=byte_size,
            row_count=row_count if row_count is not None else val_report.get("rowCount"),
            split=split or {},
            validation=val_report,
            transform_lineage=lineage,
            metadata=meta,
        )
        self.store.add_file(
            dataset_id=dataset_id,
            version_id=version.version_id,
            role="processed",
            path=str(dest),
            content_hash=content_hash,
            byte_size=byte_size,
        )
        ready = self.store.update_version(version.version_id, status=VersionStatus.READY)
        self._maybe_auto_index_ready_version(
            dataset_id,
            ready.version_id,
            validation=dict(ready.validation or {}),
        )
        return ready

    def _handle_validate(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        ver = self.get_version(job.version_id)
        if not ver.storage_path:
            raise DatasetError("Version has no storage", code="no_storage")
        input_path = Path(ver.storage_path)
        force_backend = (job.config or {}).get("forceBackend")
        plan = self._plan_compute_backend(
            "dataset.validate",
            input_path=input_path,
            force_backend=force_backend,
        )
        native_info = None
        fallback_reason = plan.fallback_reason
        if plan.backend == ComputeBackend.RUST_NATIVE:
            # Validate does not publish a new artifact; run against a scratch temp.
            try:
                session = self.scratch_manager.open_session(job.job_id)
                dest = session.root / "validate.out.jsonl"
            except Exception:  # noqa: BLE001
                dest = input_path.parent / f".validate-{job.job_id}.tmp"
            ensure_dir(dest.parent)
            native_info, plan = self._try_native_operation(
                job=job,
                operation="dataset.validate",
                input_path=input_path,
                dest=dest,
                force_backend=force_backend,
            )
            fallback_reason = plan.fallback_reason
            if native_info and dest.exists() and dest != input_path:
                dest.unlink(missing_ok=True)

        if native_info and isinstance(native_info.get("receipt"), dict):
            receipt = native_info["receipt"]
            obs = self._observability_from_native(
                plan=plan, native_info=native_info, fallback_reason=None, phase="done"
            )
            report = {
                "valid": str(receipt.get("status")) == "ok",
                "rowCount": receipt.get("recordsIn") or receipt.get("recordsOut"),
                "errorCount": 0 if str(receipt.get("status")) == "ok" else 1,
                "warningCount": 0,
                "emptyContentCount": 0,
                "issues": [],
                "backend": ComputeBackend.RUST_NATIVE.value,
                "backendPlan": plan.public_dict(),
                "fallbackReason": None,
                **obs,
            }
        else:
            import time as _time

            started = _time.monotonic()
            ckpt, root, skip, resumed = self._begin_streaming_checkpoint(
                job,
                operation="dataset.validate",
                input_path=input_path,
                options={},
                input_hash=ver.content_hash or compute_input_hash(input_path),
                backend=BACKEND_PYTHON_STREAMING,
            )

            def _on_progress(n: int) -> None:
                self._persist_streaming_progress(
                    job, ckpt, root, records_processed=n, phase="validating", started_at=started
                )

            records = iter_skip_then_count(
                self.iter_version_records(job.version_id),
                skip=skip,
                on_progress=_on_progress,
                every=DEFAULT_CHECKPOINT_EVERY,
            )
            report = validate_records(records)
            if resumed and skip:
                report["rowCount"] = int(report.get("rowCount") or 0) + int(skip)
                report["resumedFrom"] = skip
            obs = self._finish_streaming_checkpoint(
                job,
                ckpt,
                root,
                records_processed=int(report.get("rowCount") or ckpt.records_processed or 0),
                phase="done",
                started_at=started,
            )
            report = {
                **report,
                "backend": ComputeBackend.PYTHON_STREAMING.value,
                "backendPlan": plan.public_dict(),
                "fallbackReason": fallback_reason,
                **obs,
            }

        updates: dict[str, Any] = {"validation": report}
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
        parent = self.get_version(job.version_id)
        if not parent.storage_path:
            raise DatasetError("Version has no storage", code="no_storage")
        input_path = Path(parent.storage_path)
        dirs = self._dataset_dirs(job.dataset_id)
        label = f"deduped-from-{parent.version_label}"
        dest = dirs["processed"] / f"{label}.jsonl"
        semantic_meta = self._semantic_metadata_for_derived(
            parent, content_preserving=False, op_name="exact_dedupe"
        )

        native_info, plan = self._try_native_operation(
            job=job,
            operation="dataset.dedupe",
            input_path=input_path,
            dest=dest,
        )
        if native_info:
            stats = {
                "backend": ComputeBackend.RUST_NATIVE.value,
                "recordsOut": native_info.get("recordsOut"),
                "receipt": native_info.get("receipt"),
            }
            version = self._commit_derived_version_from_file(
                dataset_id=job.dataset_id,
                parent=parent,
                label=label,
                kind=VersionKind.TRANSFORMED,
                dest=dest,
                content_hash=str(native_info["contentHash"]),
                byte_size=int(native_info["byteSize"]),
                row_count=native_info.get("recordsOut"),
                lineage_extra=[
                    {
                        "name": "exact_dedupe",
                        "params": {},
                        "stats": stats,
                        "appliedAt": utc_now(),
                        "backend": ComputeBackend.RUST_NATIVE.value,
                    }
                ],
                metadata={**semantic_meta, "dedupe": stats},
                backend_info=native_info,
            )
            return {
                "versionId": version.version_id,
                "dedupe": stats,
                "backend": ComputeBackend.RUST_NATIVE.value,
                "backendPlan": plan.public_dict(),
                "fallbackReason": None,
            }

        it, stats = iter_exact_dedupe_external(
            self.iter_version_records(job.version_id),
            scratch_manager=self.scratch_manager,
            job_id=job.job_id,
        )
        version = self._write_derived_version_stream(
            dataset_id=job.dataset_id,
            parent=parent,
            label=label,
            kind=VersionKind.TRANSFORMED,
            records=it,
            lineage_extra=[{"name": "exact_dedupe", "params": {}, "stats": stats, "appliedAt": utc_now()}],
            metadata={**semantic_meta, "dedupe": stats, "computeBackend": ComputeBackend.PYTHON_STREAMING.value},
        )
        return {
            "versionId": version.version_id,
            "dedupe": stats,
            "backend": ComputeBackend.PYTHON_STREAMING.value,
            "backendPlan": plan.public_dict(),
            "fallbackReason": plan.fallback_reason,
        }

    def _handle_transform(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        parent = self.get_version(job.version_id)
        if not parent.storage_path:
            raise DatasetError("Version has no storage", code="no_storage")
        transforms = list(job.config.get("transforms") or [])
        input_path = Path(parent.storage_path)
        dirs = self._dataset_dirs(job.dataset_id)
        label = f"xform-{parent.version_label}"
        dest = dirs["processed"] / f"{label}.jsonl"
        semantic_meta = self._semantic_metadata_for_derived(
            parent, content_preserving=False, op_name="transform"
        )

        native_info, plan = self._try_native_operation(
            job=job,
            operation="dataset.transform",
            input_path=input_path,
            dest=dest,
            options={"transforms": transforms},
        )
        if native_info:
            lineage = [{"name": t.get("name"), "params": t.get("params") or {}, "appliedAt": utc_now(), "backend": ComputeBackend.RUST_NATIVE.value} for t in transforms]
            version = self._commit_derived_version_from_file(
                dataset_id=job.dataset_id,
                parent=parent,
                label=label,
                kind=VersionKind.TRANSFORMED,
                dest=dest,
                content_hash=str(native_info["contentHash"]),
                byte_size=int(native_info["byteSize"]),
                row_count=native_info.get("recordsOut"),
                lineage_extra=lineage,
                metadata=semantic_meta,
                backend_info=native_info,
            )
            full_lineage = list(parent.transform_lineage) + lineage
            self.store.update_version(version.version_id, transform_lineage=full_lineage)
            version = self.get_version(version.version_id)
            obs = self._observability_from_native(
                plan=plan, native_info=native_info, fallback_reason=None, phase="done"
            )
            return {
                "versionId": version.version_id,
                "lineage": lineage,
                "rowCount": version.row_count,
                "backend": ComputeBackend.RUST_NATIVE.value,
                "backendPlan": plan.public_dict(),
                "fallbackReason": None,
                **obs,
            }

        import time as _time

        started = _time.monotonic()
        options = {"transforms": transforms}
        ckpt, root, _skip, _resumed = self._begin_streaming_checkpoint(
            job,
            operation="dataset.transform",
            input_path=input_path,
            options=options,
            input_hash=parent.content_hash or compute_input_hash(input_path),
            backend=BACKEND_PYTHON_STREAMING,
        )
        # Full rewrite is the safe path (no partial-output append yet).
        ckpt.resumed = False
        ckpt.records_processed = 0

        def _on_progress(n: int) -> None:
            self._persist_streaming_progress(
                job, ckpt, root, records_processed=n, phase="transforming", started_at=started
            )

        source = iter_skip_then_count(
            self.iter_version_records(job.version_id),
            skip=0,
            on_progress=_on_progress,
            every=DEFAULT_CHECKPOINT_EVERY,
        )
        stream, lineage_fn = apply_transforms_streaming(source, transforms)
        version = self._write_derived_version_stream(
            dataset_id=job.dataset_id,
            parent=parent,
            label=label,
            kind=VersionKind.TRANSFORMED,
            records=stream,
            lineage_extra=[],
            metadata={**semantic_meta, "computeBackend": ComputeBackend.PYTHON_STREAMING.value},
        )
        lineage = lineage_fn()
        full_lineage = list(parent.transform_lineage) + lineage
        self.store.update_version(version.version_id, transform_lineage=full_lineage)
        version = self.get_version(version.version_id)
        obs = self._finish_streaming_checkpoint(
            job,
            ckpt,
            root,
            records_processed=int(version.row_count or ckpt.records_processed or 0),
            phase="done",
            started_at=started,
        )
        return {
            "versionId": version.version_id,
            "lineage": lineage,
            "rowCount": version.row_count,
            "backend": ComputeBackend.PYTHON_STREAMING.value,
            "backendPlan": plan.public_dict(),
            "fallbackReason": plan.fallback_reason,
            **obs,
        }

    def _handle_split(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        parent = self.get_version(job.version_id)
        if not parent.storage_path:
            raise DatasetError("Version has no storage", code="no_storage")
        seed = int(job.config.get("seed", 42))
        train_ratio = float(job.config.get("trainRatio", 0.8))
        val_ratio = float(job.config.get("valRatio", 0.1))
        test_ratio = float(job.config.get("testRatio", 0.1))
        input_path = Path(parent.storage_path)
        dirs = self._dataset_dirs(job.dataset_id)
        label = f"split-{parent.version_label}"
        dest = dirs["processed"] / f"{label}.jsonl"
        semantic_meta = self._semantic_metadata_for_derived(
            parent, content_preserving=True, op_name="deterministic_split"
        )
        options = {
            "seed": seed,
            "trainRatio": train_ratio,
            "valRatio": val_ratio,
            "testRatio": test_ratio,
        }

        native_info, plan = self._try_native_operation(
            job=job,
            operation="dataset.split",
            input_path=input_path,
            dest=dest,
            options=options,
        )
        if native_info:
            summary = {
                **options,
                "rowCount": native_info.get("recordsOut"),
                "backend": ComputeBackend.RUST_NATIVE.value,
            }
            # Prefer receipt split counts when present.
            receipt = native_info.get("receipt") if isinstance(native_info.get("receipt"), dict) else {}
            if isinstance(receipt.get("split"), dict):
                summary.update(receipt["split"])
            version = self._commit_derived_version_from_file(
                dataset_id=job.dataset_id,
                parent=parent,
                label=label,
                kind=VersionKind.SPLIT,
                dest=dest,
                content_hash=str(native_info["contentHash"]),
                byte_size=int(native_info["byteSize"]),
                row_count=native_info.get("recordsOut"),
                split=summary,
                lineage_extra=[
                    {
                        "name": "deterministic_split",
                        "params": summary,
                        "appliedAt": utc_now(),
                        "backend": ComputeBackend.RUST_NATIVE.value,
                    }
                ],
                metadata=semantic_meta,
                backend_info=native_info,
            )
            return {
                "versionId": version.version_id,
                "split": summary,
                "backend": ComputeBackend.RUST_NATIVE.value,
                "backendPlan": plan.public_dict(),
                "fallbackReason": None,
            }

        stream, summary = iter_deterministic_split(
            self.iter_version_records(job.version_id),
            seed=seed,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            test_ratio=test_ratio,
        )
        version = self._write_derived_version_stream(
            dataset_id=job.dataset_id,
            parent=parent,
            label=label,
            kind=VersionKind.SPLIT,
            records=stream,
            split=summary,
            lineage_extra=[{"name": "deterministic_split", "params": summary, "appliedAt": utc_now()}],
            metadata={**semantic_meta, "computeBackend": ComputeBackend.PYTHON_STREAMING.value},
        )
        return {
            "versionId": version.version_id,
            "split": summary,
            "backend": ComputeBackend.PYTHON_STREAMING.value,
            "backendPlan": plan.public_dict(),
            "fallbackReason": plan.fallback_reason,
        }

    def _handle_tokenize_stats(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id
        ver = self.get_version(job.version_id)
        if not ver.storage_path:
            raise DatasetError("Version has no storage", code="no_storage")
        stats = compute_token_stats(self.iter_version_records(job.version_id))
        self.store.update_version(ver.version_id, token_stats=stats)
        return stats

    def _handle_export(self, job: DatasetJob) -> dict[str, Any]:
        assert job.version_id and job.dataset_id
        ver = self.get_version(job.version_id)
        if not ver.storage_path:
            raise DatasetError("Version has no storage", code="no_storage")
        split = job.config.get("split")
        dirs = self._dataset_dirs(job.dataset_id)
        name = f"export-{ver.version_id}" + (f"-{split}" if split else "") + ".jsonl"
        dest = dirs["exports"] / name
        input_path = Path(ver.storage_path)
        semantic_meta = self._semantic_metadata_for_derived(
            ver, content_preserving=True, op_name="export"
        )

        native_info, plan = self._try_native_operation(
            job=job,
            operation="dataset.export",
            input_path=input_path,
            dest=dest,
            options={"split": split} if split else {},
        )
        if native_info:
            # Create BUILDING then READY after metadata commit.
            export_version = self.store.create_version(
                dataset_id=job.dataset_id,
                version_label=f"export-{ver.version_label}",
                kind=VersionKind.EXPORT,
                parent_version_id=ver.version_id,
                status=VersionStatus.BUILDING,
                storage_path=str(dest),
                schema={**canonical_schema_dict(), "storageFormat": "jsonl"},
                metadata={**semantic_meta, "computeBackend": ComputeBackend.RUST_NATIVE.value},
            )
            self.store.update_version(
                export_version.version_id,
                content_hash=str(native_info["contentHash"]),
                byte_size=int(native_info["byteSize"]),
                row_count=native_info.get("recordsOut"),
                metadata={**semantic_meta, "computeBackend": ComputeBackend.RUST_NATIVE.value},
            )
            self.store.update_version(export_version.version_id, status=VersionStatus.READY)
            obs = self._observability_from_native(
                plan=plan, native_info=native_info, fallback_reason=None, phase="done"
            )
            return {
                "versionId": export_version.version_id,
                "contentHash": native_info["contentHash"],
                "byteSize": native_info["byteSize"],
                "rowCount": native_info.get("recordsOut"),
                "path": str(dest),
                "backend": ComputeBackend.RUST_NATIVE.value,
                "backendPlan": plan.public_dict(),
                "fallbackReason": None,
                **obs,
            }

        import time as _time

        started = _time.monotonic()
        options = {"split": split} if split else {}
        ckpt, root, _skip, _resumed = self._begin_streaming_checkpoint(
            job,
            operation="dataset.export",
            input_path=input_path,
            options=options,
            input_hash=ver.content_hash or compute_input_hash(input_path),
            backend=BACKEND_PYTHON_STREAMING,
        )
        ckpt.resumed = False
        ckpt.records_processed = 0

        def _on_progress(n: int) -> None:
            self._persist_streaming_progress(
                job, ckpt, root, records_processed=n, phase="exporting", started_at=started
            )

        source = iter_skip_then_count(
            self.iter_version_records(job.version_id),
            skip=0,
            on_progress=_on_progress,
            every=DEFAULT_CHECKPOINT_EVERY,
        )
        result = export_jsonl(source, dest, split=split)
        export_version = self.store.create_version(
            dataset_id=job.dataset_id,
            version_label=f"export-{ver.version_label}",
            kind=VersionKind.EXPORT,
            parent_version_id=ver.version_id,
            status=VersionStatus.BUILDING,
            storage_path=str(dest),
            schema={**canonical_schema_dict(), "storageFormat": "jsonl"},
            metadata={**semantic_meta, "computeBackend": ComputeBackend.PYTHON_STREAMING.value},
        )
        self.store.update_version(
            export_version.version_id,
            content_hash=result["contentHash"],
            byte_size=result["byteSize"],
            row_count=result["rowCount"],
        )
        self.store.update_version(export_version.version_id, status=VersionStatus.READY)
        obs = self._finish_streaming_checkpoint(
            job,
            ckpt,
            root,
            records_processed=int(result.get("rowCount") or 0),
            phase="done",
            started_at=started,
        )
        result["versionId"] = export_version.version_id
        result["backend"] = ComputeBackend.PYTHON_STREAMING.value
        result["backendPlan"] = plan.public_dict()
        result["fallbackReason"] = plan.fallback_reason
        result.update(obs)
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
        scope = resolve_index_scope(
            dataset_id=job.dataset_id,
            version_id=ver.version_id,
            requested_scope=str(job.config.get("scope") or "") or None,
        )
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
                "canonicalKnowledgeSource": scope,
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

            # P1-001: durable integrity receipt must PASS before IndexStatus.READY.
            from .indexing import verify_index_integrity

            self.store.update_job(job.job_id, phase="verifying", progress=0.97)
            integrity_receipt = verify_index_integrity(
                self.knowledge,
                dataset_id=job.dataset_id,
                version_id=ver.version_id,
                source_fingerprint=str(source_fingerprint or ver.content_hash or ""),
                index_id=index.index_id,
                outcome=outcome,
                manifest=manifest,
                expected_records=int(ver.row_count)
                if ver.row_count is not None
                else int(outcome.get("processedCount") or 0),
                scope=scope,
            )
            receipt_path = (
                self.corpus.datasets_manifests / f"index-integrity-{index.index_id}.json"
            )
            atomic_write_text(
                receipt_path,
                json.dumps(integrity_receipt, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
            )
            integrity_receipt["receiptPath"] = str(receipt_path)
            if integrity_receipt.get("verificationStatus") != "PASS":
                raise DatasetError(
                    "Index integrity verification failed: "
                    + "; ".join(integrity_receipt.get("verificationErrors") or ["unknown"]),
                    code="index_integrity_failed",
                    http_status=409,
                    details={
                        "indexId": index.index_id,
                        "verificationStatus": integrity_receipt.get("verificationStatus"),
                        "evidenceClass": integrity_receipt.get("evidenceClass"),
                        "receiptPath": str(receipt_path),
                    },
                )

            provenance = {
                **outcome,
                "manifest": manifest,
                "integrityReceipt": integrity_receipt,
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
                "integrityReceipt": integrity_receipt,
                "supersededIndexIds": superseded,
                "rebuild": bool(job.config.get("rebuild")),
                "requestedVersionId": requested_version_id,
                "resolvedVersionId": ver.version_id,
                "learnToBrain": bool(job.config.get("learnToBrain")),
            }
        except Exception as exc:
            failed_prov: dict[str, Any] = {"error": redact_secrets(str(exc))}
            if isinstance(exc, DatasetError) and getattr(exc, "code", None) == "index_integrity_failed":
                details = dict(getattr(exc, "details", None) or {})
                failed_prov["integrityVerification"] = "FAIL"
                failed_prov["integrityDetails"] = details
            self.store.update_index(
                index.index_id,
                status=IndexStatus.FAILED,
                provenance=failed_prov,
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

        # Control plane never calls Hugging Face itself. Listing is
        # provider.hf.list on provider_io. Bulk transfer stays on the dataset
        # worker (IMPORT_HF). list_hf_dataset_files is only reached from
        # dataset-worker handlers and the provider_io adapter.
        if self.jobs is None:
            raise DatasetError(
                "job runtime not bound; refusing Control Plane HF list fallback",
                code=ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
                http_status=503,
            )
        db_path = getattr(getattr(self.jobs, "store", None), "path", None)
        if not provider_io_workers_ready(db_path):
            raise DatasetError(
                "provider_io workers unavailable; refusing Control Plane HF list fallback",
                code=ProviderErrorCode.PROVIDER_EXECUTION_UNAVAILABLE.value,
                http_status=503,
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
            raise DatasetError(str(exc), code=exc.code.value, http_status=503) from exc
        if result.status != "succeeded" or not isinstance(result.structured, dict):
            err = (result.error or {}).get("message") or "HF list failed"
            raise DatasetError(
                str(err),
                code=(result.error or {}).get("code") or "PROVIDER_UNAVAILABLE",
                http_status=503,
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
        self.get_version(version_id)
        capped, truncated = _cap_record_iter(self.iter_version_records(version_id), limit=5_000)
        report = simulate_packing(capped, max_seq_length=max_seq_length).public_dict()
        report["evidenceClass"] = "SAMPLED" if truncated["hit"] else "EXACT"
        report["recordCap"] = 5_000
        report["truth"] = {
            **dict(report.get("truth") or {}),
            "controlPlaneBounded": True,
            "fullPackingScanIsDatasetWorker": True,
        }
        return report

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
        records = self.iter_version_records(version_id)
        sealed = list(job.config.get("sealed_cases") or [])
        threshold = float(job.config.get("threshold") or 0.35)
        max_retained = int(job.config.get("max_retained_hits") or job.config.get("maxRetainedHits") or 200)

        def cancel() -> bool:
            return self.runner.is_cancel_requested(job.job_id)

        on_progress = self._throttled_job_progress(job.job_id)
        if not sealed:
            # No reference corpus. The report is UNMEASURED and must not pass as clean.
            report = scan_contamination(
                records,
                [],
                threshold=threshold,
                max_retained_hits=max_retained,
                cancel_check=cancel,
                progress_cb=on_progress,
            )
            out = report.public_dict()
            out["note"] = "No sealed cases provided — contamination gate not exercised"
            return out
        report = scan_contamination(
            records,
            sealed,
            threshold=threshold,
            max_retained_hits=max_retained,
            cancel_check=cancel,
            progress_cb=on_progress,
        )
        return report.public_dict()

    def _handle_enrich_metadata(self, job: DatasetJob) -> dict[str, Any]:
        dataset_id = job.dataset_id or ""
        version_id = job.version_id or ""
        if not dataset_id or not version_id:
            raise DatasetError(
                "enrich_metadata requires dataset_id and version_id",
                code="enrich_missing_ids",
                http_status=400,
            )
        sync_artifacts = bool((job.config or {}).get("sync_artifacts", True))
        result = self.enrich_semantic_deterministic(
            dataset_id,
            version_id,
            sync_artifacts=sync_artifacts,
        )
        return result

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
        data.update(self._public_compute_summary(data.get("result") or {}, checkpoint, phase=job.phase))
        data["compute"] = {
            k: data.get(k)
            for k in (
                "backend",
                "phase",
                "recordsProcessed",
                "peakMemory",
                "memoryBudget",
                "spillBytes",
                "throughput",
                "durationMs",
                "fallbackReason",
                "resumed",
            )
            if k in data
        }
        return data

    @staticmethod
    def _public_compute_summary(
        result: dict[str, Any],
        checkpoint: dict[str, Any],
        *,
        phase: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(result, dict):
            result = {}
        if not isinstance(checkpoint, dict):
            checkpoint = {}
        streaming = checkpoint.get("streaming") if isinstance(checkpoint.get("streaming"), dict) else {}
        receipt = result.get("receipt") if isinstance(result.get("receipt"), dict) else {}
        plan = result.get("backendPlan") if isinstance(result.get("backendPlan"), dict) else {}

        def _metric(*candidates: Any) -> Any:
            for value in candidates:
                if value is None or value == "":
                    continue
                if isinstance(value, str) and value.upper() == CKPT_UNMEASURED:
                    return CKPT_UNMEASURED
                if isinstance(value, bool):
                    continue
                try:
                    return float(value) if isinstance(value, float) else int(value)
                except (TypeError, ValueError):
                    if isinstance(value, str):
                        return value
            return CKPT_UNMEASURED

        backend = normalize_backend_label(
            result.get("backend")
            or plan.get("backend")
            or streaming.get("backend")
            or checkpoint.get("backend")
        )
        fallback = result.get("fallbackReason")
        if fallback is None and "fallbackReason" in plan:
            fallback = plan.get("fallbackReason")
        records = (
            result.get("recordsProcessed")
            if result.get("recordsProcessed") is not None
            else streaming.get("recordsProcessed")
            if streaming.get("recordsProcessed") is not None
            else result.get("rowCount")
            if result.get("rowCount") is not None
            else result.get("recordsOut")
            if result.get("recordsOut") is not None
            else receipt.get("recordsOut")
        )
        peak = _metric(
            result.get("peakMemory"),
            result.get("peakRssBytes"),
            streaming.get("peakMemory"),
            receipt.get("peakRssBytes"),
        )
        spill = _metric(result.get("spillBytes"), streaming.get("spillBytes"), receipt.get("spillBytes"))
        return {
            "backend": backend,
            "phase": result.get("phase") or streaming.get("phase") or phase,
            "recordsProcessed": int(records) if records is not None else None,
            "peakMemory": peak,
            "memoryBudget": _metric(
                result.get("memoryBudget"), result.get("memoryBudgetBytes"), streaming.get("memoryBudget")
            ),
            "spillBytes": spill,
            "throughput": _metric(result.get("throughput"), streaming.get("throughput")),
            "durationMs": _metric(
                result.get("durationMs"), streaming.get("durationMs"), receipt.get("durationMs")
            ),
            "fallbackReason": fallback,
            "resumed": bool(result.get("resumed") or streaming.get("resumed")),
            "peakRssBytes": None if peak == CKPT_UNMEASURED else peak,
            "recordsIn": None
            if _metric(result.get("recordsIn"), receipt.get("recordsIn")) == CKPT_UNMEASURED
            else _metric(result.get("recordsIn"), receipt.get("recordsIn")),
            "recordsOut": None
            if _metric(result.get("recordsOut"), receipt.get("recordsOut")) == CKPT_UNMEASURED
            else _metric(result.get("recordsOut"), receipt.get("recordsOut")),
            "memoryEnforcement": result.get("memoryEnforcement") or receipt.get("memoryEnforcement"),
        }

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
