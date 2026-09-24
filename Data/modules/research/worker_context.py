"""Process-safe Research worker context — same Brain / MCP / Datasets / Obs.

Never imports ``Data.backend.main``. Builds the dependencies the API ResearchService
normally receives so external research pool workers participate in one LEVIATHAN
system rather than a stripped-down island.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_research_worker_context(
    *,
    settings: Any | None = None,
    job_runtime: Any | None = None,
) -> dict[str, Any]:
    """Return a fully wired ResearchService plus supporting handles."""
    if settings is None:
        from Data.backend.config import load_settings

        settings = load_settings()

    from Data.modules.datasets.service import DatasetService
    from Data.modules.intelligence.assimilation import KnowledgeAssimilationService
    from Data.modules.knowledge import AtlasStore, KnowledgeStore
    from Data.modules.knowledge.embeddings import build_embedding_provider
    from Data.modules.observability import ObservabilityHub
    from Data.modules.research.service import ResearchService

    db_path = Path(settings.database_path)
    observability = ObservabilityHub(capacity=2000, db_path=db_path)

    provider = build_embedding_provider(
        kind=settings.knowledge.embedding_provider,
        model_name=settings.knowledge.embedding_model,
        hash_dimensions=getattr(settings.knowledge, "hash_dimensions", 256),
    )
    knowledge = KnowledgeStore(
        db_path,
        data_root=Path(settings.knowledge.data_root),
        embedding_provider=provider,
    )
    knowledge.initialize()

    atlas_store = AtlasStore(db_path)
    assimilation_service = KnowledgeAssimilationService(
        database_path=db_path,
        knowledge_store=knowledge,
        atlas_store=atlas_store,
    )
    assimilation_service._emit = observability.emit  # noqa: SLF001

    if job_runtime is None:
        from Data.modules.execution import ExecutionGateway, build_default_catalog
        from Data.modules.jobs.resources import ResourceManager
        from Data.modules.jobs.runtime import JobRuntime
        from Data.modules.jobs.store import JobStore

        job_store = JobStore(db_path)
        job_store.initialize()
        gateway = ExecutionGateway(catalog=build_default_catalog())
        resources = ResourceManager(settings.resources.max_job_concurrency)
        job_runtime = JobRuntime(job_store, gateway, resources)

    dataset_service = DatasetService.from_settings(
        settings,
        knowledge=knowledge,
        job_runtime=job_runtime,
    )

    model_caller = None
    model_client_error: str | None = None
    try:
        from Data.modules.models.worker_client import build_process_safe_model_caller

        model_caller = build_process_safe_model_caller(settings)
    except Exception as exc:  # noqa: BLE001 — surface later; don't block deterministic research
        model_client_error = f"{type(exc).__name__}: {exc}"
        observability.emit(
            "research.model_client_unavailable",
            {
                "error": model_client_error,
                "message": "Research worker model client failed to initialize",
            },
            level="WARNING",
            subsystem="research",
        )

    service = ResearchService.from_settings(
        settings,
        db_path=db_path,
        knowledge=knowledge,
        assimilation_service=assimilation_service,
        atlas_store=atlas_store,
        observability_emit=observability.emit,
        model_caller=model_caller,
        job_runtime=job_runtime,
        dataset_service=dataset_service,
    )

    return {
        "settings": settings,
        "research_service": service,
        "knowledge": knowledge,
        "atlas_store": atlas_store,
        "assimilation_service": assimilation_service,
        "observability": observability,
        "job_runtime": job_runtime,
        "dataset_service": dataset_service,
        "model_caller": model_caller,
        "model_client_error": model_client_error,
    }
