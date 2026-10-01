"""ResearchService — public façade for API and runners."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, BinaryIO, Callable

from Data.modules.common.corpus import CorpusLayout, build_corpus_layout
from Data.modules.knowledge import KnowledgeStore

from .brain_sync import ResearchBrainSync
from .budgets import (
    budget_catalog,
    budget_for_depth,
    list_presets,
    merge_budget_overrides,
    resolve_execution_budget,
)
from .evidence import EvidenceLedger
from .execution_gate import (
    WorkerMeasuredState,
    allow_inprocess_research_execution,
    probe_research_worker_availability,
    refuse_inline_research,
    require_job_runtime_for_external,
    runners_externalized,
)
from .local_retrieval import LocalResearchRetriever, build_default_local_retriever
from .planner import apply_plan_edits, build_plan
from .reports import ReportBuilder
from .runner import ResearchRunner
from .ssrf import validate_url_for_fetch
from .store import ResearchStore, utc_now
from .types import (
    ACTIVE_STATUSES,
    AnalysisMode,
    KnowledgePromotionStatus,
    ResearchDepth,
    ResearchError,
    ResearchExecutionMode,
    ResearchPhase,
    ResearchProject,
    ResearchStatus,
    TERMINAL_STATUSES,
)
from .uploads import UploadIngestor
from .web import UnconfiguredWebProvider, WebResearchProvider, build_web_provider, web_unavailable_reason

ObservabilityEmit = Callable[..., Any]


class ResearchService:
    def __init__(
        self,
        store: ResearchStore,
        *,
        knowledge: KnowledgeStore | None = None,
        local: LocalResearchRetriever | None = None,
        web: WebResearchProvider | None = None,
        allow_outbound: bool = False,
        snapshots_root: Path | None = None,
        reports_root: Path | None = None,
        sources_root: Path | None = None,
        corpus: CorpusLayout | None = None,
        assimilation_service: Any | None = None,
        atlas_store: Any | None = None,
        observability_emit: ObservabilityEmit | None = None,
        auto_promote_verified_knowledge: bool = True,
        model_caller: Callable[..., dict[str, Any]] | None = None,
        job_runtime: Any | None = None,
        dataset_service: Any | None = None,
        knowledge_database_path: Path | None = None,
    ) -> None:
        self.store = store
        self.knowledge = knowledge
        self.allow_outbound = bool(allow_outbound)
        self.assimilation_service = assimilation_service
        self.atlas_store = atlas_store
        self._emit = observability_emit
        self.auto_promote_verified_knowledge = bool(auto_promote_verified_knowledge)
        self.model_caller = model_caller
        self.job_runtime = job_runtime
        self.dataset_service = dataset_service
        self._knowledge_database_path = (
            Path(knowledge_database_path) if knowledge_database_path is not None else None
        )
        if corpus is not None:
            self.snapshots_root = corpus.research_snapshots
            self.reports_root = corpus.research_reports
            self.exports_root = corpus.research_exports
            self.sources_root = corpus.research_sources
            self._corpus = corpus
        else:
            self.snapshots_root = Path(snapshots_root or store.db_path.parent / "research_snapshots")
            self.reports_root = Path(reports_root or store.db_path.parent / "research_reports")
            self.exports_root = self.reports_root.parent / "research_exports"
            self.sources_root = Path(sources_root or store.db_path.parent / "research_sources")
            self._corpus = None
        self.local = local or build_default_local_retriever(knowledge)
        self.web = web or (
            build_web_provider(allow_outbound=allow_outbound)
            if allow_outbound
            else UnconfiguredWebProvider()
        )
        self._web_search_endpoint = getattr(self.web, "search_endpoint", None)
        self._web_search_api_key_configured = False
        self._web_search_mode = getattr(self.web, "search_mode", "auto") or "auto"
        self.brain = ResearchBrainSync(store, knowledge)
        self.uploads = UploadIngestor(
            store,
            sources_root=self.sources_root,
            snapshots_root=self.snapshots_root,
        )
        self.source_ingestion = None
        self.source_ingestion_status: dict[str, Any] = {
            "state": "NOT_INITIALIZED",
            "reason": None,
            "error_class": None,
        }
        try:
            from Data.modules.source_ingestion.service import SourceIngestionService
            from Data.modules.source_ingestion.settings import load_source_ingestion_settings
            from Data.modules.common.corpus import CorpusLayout

            layout = self._corpus
            if layout is None:
                layout = CorpusLayout(
                    root=self.sources_root.parent,
                    datasets=self.sources_root.parent / "datasets",
                    datasets_raw=self.sources_root.parent / "datasets" / "raw",
                    datasets_materialized=self.sources_root.parent / "datasets" / "materialized",
                    datasets_processed=self.sources_root.parent / "datasets" / "processed",
                    datasets_exports=self.sources_root.parent / "datasets" / "exports",
                    datasets_manifests=self.sources_root.parent / "datasets" / "manifests",
                    training=self.sources_root.parent / "training",
                    training_jobs=self.sources_root.parent / "training" / "jobs",
                    training_runs=self.sources_root.parent / "training" / "runs",
                    training_checkpoints=self.sources_root.parent / "training" / "checkpoints",
                    training_adapters=self.sources_root.parent / "training" / "adapters",
                    training_exports=self.sources_root.parent / "training" / "exports",
                    training_logs=self.sources_root.parent / "training" / "logs",
                    research=self.sources_root.parent,
                    research_projects=self.sources_root.parent / "projects",
                    research_sources=self.sources_root,
                    research_snapshots=self.snapshots_root,
                    research_reports=self.reports_root,
                    research_exports=self.exports_root,
                    models_artifacts=self.sources_root.parent / "models" / "artifacts",
                    models_cache=self.sources_root.parent / "models" / "cache",
                    hf_cache=self.sources_root.parent / "hf_cache",
                )
            ingestion_db: Path | None = self._knowledge_database_path
            if ingestion_db is None and knowledge is not None:
                raw = getattr(knowledge, "db_path", None) or getattr(knowledge, "path", None)
                if raw is not None:
                    ingestion_db = Path(raw)
            if ingestion_db is None:
                raise RuntimeError(
                    "SourceIngestion requires knowledge_database_path or a KnowledgeStore"
                )
            self.source_ingestion = SourceIngestionService.from_corpus(
                research_store=store,
                corpus=layout,
                database_path=ingestion_db,
                knowledge=knowledge,
                job_runtime=job_runtime,
                dataset_service=dataset_service,
                settings=load_source_ingestion_settings(),
            )
            self.source_ingestion_status = {
                "state": "READY",
                "reason": None,
                "error_class": None,
            }
        except Exception as exc:  # noqa: BLE001 — keep Research usable if SI init fails
            # TRUTH-001: record cause — silent None alone is forbidden.
            self.source_ingestion = None
            err_cls = type(exc).__name__
            msg = str(exc)[:400]
            if "knowledge_database_path" in msg or "KnowledgeStore" in msg:
                reason = "configuration_error"
            elif "OperationalError" in err_cls or "schema" in msg.lower():
                reason = "db_schema_error"
            elif err_cls in {"ImportError", "ModuleNotFoundError"}:
                reason = "dependency_absent"
            else:
                reason = "runtime_initialization_failure"
            self.source_ingestion_status = {
                "state": "UNAVAILABLE",
                "reason": reason,
                "error_class": err_cls,
                "error": msg,
                "truth": {
                    "silent_none_forbidden": True,
                    "feature_not_intentionally_disabled": True,
                },
            }
        self.runner = ResearchRunner(
            store,
            local=self.local,
            web=self.web,
            allow_outbound=self.allow_outbound,
            snapshots_root=self.snapshots_root,
            reports_root=self.reports_root,
            brain_sync=self._sync_report,
        )
        self.ledger = EvidenceLedger(store)
        self.reports = ReportBuilder(
            store, reports_root=self.reports_root, model_caller=model_caller
        )
        self.runner.reports.set_model_caller(model_caller)
        self._bg_lock = threading.Lock()
        self._bg_threads: dict[str, threading.Thread] = {}
        self._dispatcher_stop = threading.Event()
        self._dispatcher_thread: threading.Thread | None = None

    def _sync_report(self, project: ResearchProject, report: Any) -> None:
        self.brain.sync_report(project, report)

    @classmethod
    def from_settings(
        cls,
        settings,
        *,
        db_path: Path,
        knowledge: KnowledgeStore | None = None,
        web: WebResearchProvider | None = None,
        search_endpoint: str | None = None,
        search_api_key: str | None = None,
        assimilation_service: Any | None = None,
        atlas_store: Any | None = None,
        observability_emit: ObservabilityEmit | None = None,
        model_caller: Callable[..., dict[str, Any]] | None = None,
        job_runtime: Any | None = None,
        dataset_service: Any | None = None,
    ) -> "ResearchService":
        corpus = build_corpus_layout(settings)
        store = ResearchStore(db_path)
        store.initialize()
        allow_outbound = bool(settings.network.allow_outbound)
        endpoint = search_endpoint
        api_key = search_api_key
        auto_promote = True
        search_provider = None
        search_mode = "auto"
        if hasattr(settings, "research_integration"):
            endpoint = endpoint or settings.research_integration.web_search_endpoint
            api_key = api_key if api_key is not None else settings.research_integration.web_search_api_key
            auto_promote = bool(
                getattr(
                    settings.research_integration,
                    "auto_promote_verified_knowledge",
                    True,
                )
            )
            search_provider = getattr(
                settings.research_integration, "web_search_provider", None
            )
            search_mode = getattr(
                settings.research_integration, "web_search_mode", "auto"
            ) or "auto"
            # Historical: PROVIDER=auto means chain mode auto (not an HTTP adapter name).
            if str(search_provider or "").strip().lower() == "auto" and not endpoint:
                search_provider = None
                search_mode = search_mode or "auto"
        provider = web or build_web_provider(
            allow_outbound=allow_outbound,
            search_endpoint=endpoint,
            api_key=api_key,
            search_provider=search_provider,
            search_mode=search_mode,
        )
        knowledge_db = None
        if hasattr(settings, "knowledge_database_path"):
            knowledge_db = Path(settings.knowledge_database_path)
        elif knowledge is not None:
            knowledge_db = Path(knowledge.db_path)
        svc = cls(
            store,
            knowledge=knowledge,
            web=provider,
            allow_outbound=allow_outbound,
            corpus=corpus,
            assimilation_service=assimilation_service,
            atlas_store=atlas_store,
            observability_emit=observability_emit,
            auto_promote_verified_knowledge=auto_promote,
            model_caller=model_caller,
            job_runtime=job_runtime,
            dataset_service=dataset_service,
            knowledge_database_path=knowledge_db,
        )
        svc._web_search_endpoint = endpoint
        svc._web_search_api_key_configured = bool((api_key or "").strip())
        svc._web_search_mode = search_mode
        return svc

    def reconfigure_web(
        self,
        *,
        allow_outbound: bool,
        search_endpoint: str | None = None,
        api_key: str | None = None,
        search_provider: str | None = None,
        search_mode: str | None = None,
    ) -> None:
        """Hot-apply outbound / search provider settings from the Settings Control Plane."""
        from Data.modules.research.web import build_web_provider
        from Data.modules.research.web_capabilities import bind_web_provider

        mode = search_mode
        if mode is None:
            mode = getattr(self, "_web_search_mode", "auto")
        provider_name = search_provider
        if str(provider_name or "").strip().lower() == "auto" and not search_endpoint:
            provider_name = None
        self.allow_outbound = bool(allow_outbound)
        self._web_search_endpoint = search_endpoint
        self._web_search_api_key_configured = bool((api_key or "").strip())
        self._web_search_mode = mode or "auto"
        self.web = build_web_provider(
            allow_outbound=self.allow_outbound,
            search_endpoint=search_endpoint,
            api_key=api_key,
            search_provider=provider_name,
            search_mode=self._web_search_mode,
        )
        bind_web_provider(
            self.web,
            allow_outbound=self.allow_outbound,
            allow_web=True,
        )
        if hasattr(self, "runner") and self.runner is not None:
            self.runner.allow_outbound = self.allow_outbound
            self.runner.web = self.web
            if hasattr(self.runner, "coordinator"):
                self.runner.coordinator.allow_outbound = self.allow_outbound
                self.runner.coordinator.web = self.web

    def web_readiness(self) -> dict[str, Any]:
        from .web_readiness import build_web_readiness

        return build_web_readiness(
            allow_outbound=self.allow_outbound,
            provider=self.web,
            search_endpoint=getattr(self, "_web_search_endpoint", None),
            api_key_configured=bool(
                getattr(self, "_web_search_api_key_configured", False)
            ),
            search_mode=str(getattr(self, "_web_search_mode", "auto") or "auto"),
        ).public_dict()

    def probe_web_research(
        self, *, query: str = "SQLite WAL mode", limit: int = 3
    ) -> dict[str, Any]:
        from .web_readiness import probe_web_research

        return probe_web_research(
            self.web,
            allow_outbound=self.allow_outbound,
            query=query,
            limit=limit,
        )

    def set_model_caller(self, caller: Callable[..., dict[str, Any]] | None) -> None:
        self.model_caller = caller
        # Keep report builder on the same shared MCP caller (research role injected at call site).
        if hasattr(self, "reports") and self.reports is not None:
            self.reports.set_model_caller(caller)
        if hasattr(self, "runner") and self.runner is not None and hasattr(self.runner, "reports"):
            self.runner.reports.set_model_caller(caller)

    def start_background(self, *, poll_seconds: float = 0.5) -> None:
        """Background dispatcher for queued research runs.

        When workers are externalized (``LEVIATHAN_WORKERS_EXTERNALIZE_API`` or
        domain runner=external), enqueue durable ``research.advance`` jobs instead
        of spawning API-owned dispatcher/project threads. ``recover()`` remains
        separate and must still run at API startup.
        """
        if self._runners_externalized():
            # Never start source-ingestion or research threads in-process.
            if self.job_runtime is not None:
                self.enqueue_queued_projects()
            return

        # Inprocess dispatcher only under mechanical allow gate.
        if not allow_inprocess_research_execution():
            return

        # Even when externalize flag is off, SI background threads require the
        # mechanical inprocess_test allow gate (no silent reactivation).
        if self.source_ingestion is not None:
            try:
                from Data.modules.source_ingestion.execution_gate import allow_inprocess_execution

                if allow_inprocess_execution(self.source_ingestion.settings):
                    self.source_ingestion.start_background()
            except Exception:  # noqa: BLE001
                pass
        if self._dispatcher_thread and self._dispatcher_thread.is_alive():
            return

        def _loop() -> None:
            while not self._dispatcher_stop.wait(poll_seconds):
                try:
                    self._dispatch_queued()
                except Exception:  # noqa: BLE001 — never kill dispatcher
                    continue

        self._dispatcher_stop.clear()
        self._dispatcher_thread = threading.Thread(
            target=_loop, name="research-dispatcher", daemon=True
        )
        self._dispatcher_thread.start()

    @staticmethod
    def _runners_externalized() -> bool:
        """True when API must not own heavy research execution (fail-closed)."""
        return runners_externalized()

    def _require_external_runtime(self, *, capability: str) -> None:
        require_job_runtime_for_external(
            self.job_runtime,
            capability=capability,
            reason="job_runtime_unbound",
        )
    def enqueue_advance(
        self,
        project_id: str,
        *,
        action: str = "advance",
        deepen: bool = False,
        extra_rounds: int = 0,
        resume: bool = False,
        parent_job_id: str | None = None,
        root_job_id: str | None = None,
        generation: str | None = None,
    ) -> Any:
        """Create a durable child-friendly research.advance job for external workers."""
        if self.job_runtime is None:
            raise RuntimeError("job_runtime not bound; cannot enqueue research.advance")
        project = self.get_project(project_id)
        gen = generation or project.active_run_id or (
            f"{int(project.current_round)}:{project.updated_at or project.created_at}"
        )
        idem = f"research:advance:{project_id}:{gen}"
        return self.job_runtime.enqueue(
            capability_id="research.advance",
            arguments={
                "project_id": project_id,
                "action": action,
                "deepen": bool(deepen),
                "extra_rounds": int(extra_rounds),
                "resume": bool(resume),
            },
            requested_by="research_service",
            idempotency_key=idem,
            domain="research",
            domain_entity_type="research_project",
            domain_entity_id=project_id,
            worker_pool="research",
            parent_job_id=parent_job_id,
            root_job_id=root_job_id or parent_job_id,
            latency_class="background",
            metadata={"project_id": project_id, "generation": gen},
        )

    def enqueue_queued_projects(self) -> list[str]:
        """Enqueue advance jobs for all QUEUED projects (idempotent keys).

        Uses bounded page traversal so projects beyond the first page are not starved.
        """
        job_ids: list[str] = []
        if self.job_runtime is None:
            return job_ids
        page_size = 100
        offset = 0
        seen: set[str] = set()
        while True:
            batch = self.store.list_projects(limit=page_size, offset=offset)
            if not batch:
                break
            for project in batch:
                if project.project_id in seen:
                    continue
                seen.add(project.project_id)
                if project.status != ResearchStatus.QUEUED:
                    continue
                try:
                    job = self.enqueue_advance(project.project_id)
                    job_ids.append(job.job_id)
                except Exception:  # noqa: BLE001
                    continue
            if len(batch) < page_size:
                break
            offset += page_size
            # Safety ceiling: avoid infinite loops if catalog mutates rapidly.
            if offset > 100_000:
                break
        return job_ids

    def stop_background(self) -> None:
        self._dispatcher_stop.set()

    def _dispatch_queued(self) -> None:
        if self._runners_externalized():
            if self.job_runtime is None:
                return
            self.enqueue_queued_projects()
            return
        if not allow_inprocess_research_execution():
            return
        page_size = 100
        offset = 0
        while True:
            batch = self.store.list_projects(limit=page_size, offset=offset)
            if not batch:
                break
            for project in batch:
                if project.status != ResearchStatus.QUEUED:
                    continue
                with self._bg_lock:
                    t = self._bg_threads.get(project.project_id)
                    if t and t.is_alive():
                        continue
                self._spawn_run(project.project_id, deepen=False, extra_rounds=0, resume=False)
            if len(batch) < page_size:
                break
            offset += page_size
            if offset > 100_000:
                break

    def recover(self) -> list[str]:
        recovered = self.runner.recover_interrupted()
        recovered.extend(self.reconcile_queued_projects())
        return list(dict.fromkeys(recovered))

    def reconcile_queued_projects(self) -> list[str]:
        """Repair stuck QUEUED / falsely-completed kernel job states.

        A. QUEUED + valid QUEUED/RUNNING kernel job → leave for normal claim.
        B. QUEUED + no kernel job → enqueue idempotently.
        C. QUEUED + COMPLETED kernel job but no ResearchRun started → re-enqueue.
        D. RESEARCHING + dead worker handled by recover_interrupted.
        E. Terminal projects → never restart.
        """
        fixed: list[str] = []
        if self.job_runtime is None:
            return fixed
        store = getattr(self.job_runtime, "store", None)
        if store is None:
            return fixed

        from Data.modules.jobs.states import JobState

        page_size = 100
        offset = 0
        while True:
            batch = self.store.list_projects(limit=page_size, offset=offset)
            if not batch:
                break
            for project in batch:
                if project.status in TERMINAL_STATUSES:
                    continue
                if project.status != ResearchStatus.QUEUED:
                    continue

                job = None
                if project.kernel_job_id and hasattr(store, "get"):
                    try:
                        job = store.get(project.kernel_job_id)
                    except Exception:  # noqa: BLE001
                        job = None
                if job is None and hasattr(store, "list"):
                    try:
                        from Data.modules.jobs.states import TERMINAL_JOB_STATES

                        candidates = [
                            j
                            for j in store.list(limit=500)
                            if getattr(j, "domain_entity_id", None) == project.project_id
                            and str(getattr(j, "capability_id", "") or "").startswith("research.")
                        ]
                        active = [
                            j
                            for j in candidates
                            if getattr(j, "state", None) not in TERMINAL_JOB_STATES
                        ]
                        job = (active or candidates or [None])[0]
                    except Exception:  # noqa: BLE001
                        job = None

                run = (
                    self.store.get_run(project.active_run_id)
                    if project.active_run_id
                    else self.store.get_latest_run(project.project_id)
                )
                run_started = run is not None and run.started_at is not None

                if job is None:
                    try:
                        enqueued = self.enqueue_advance(project.project_id)
                        project.kernel_job_id = getattr(enqueued, "job_id", None)
                        availability = self._research_worker_availability()
                        project.wait_reason = (
                            None
                            if availability.worker_state == WorkerMeasuredState.AVAILABLE
                            else availability.wait_reason
                        )
                        self.store.save_project(project)
                        fixed.append(project.project_id)
                        self.store.add_event(
                            project.project_id,
                            "reconciled",
                            "Re-enqueued missing research.advance job",
                            {"job_id": project.kernel_job_id},
                        )
                    except Exception:  # noqa: BLE001
                        continue
                    continue

                state = getattr(job, "state", None)
                state_val = state.value if hasattr(state, "value") else str(state or "")
                if state_val in {JobState.COMPLETED.value, "COMPLETED"} and not run_started:
                    try:
                        gen = f"reconcile:{utc_now()}"
                        enqueued = self.enqueue_advance(
                            project.project_id,
                            generation=gen,
                        )
                        project.kernel_job_id = getattr(enqueued, "job_id", None)
                        project.wait_reason = None
                        project.error = None
                        self.store.save_project(project)
                        fixed.append(project.project_id)
                        self.store.add_event(
                            project.project_id,
                            "reconciled",
                            "Kernel job completed without ResearchRun; re-enqueued",
                            {"job_id": project.kernel_job_id, "prior_job_id": job.job_id},
                        )
                    except Exception:  # noqa: BLE001
                        continue
                    continue

                if state_val in {JobState.FAILED.value, "FAILED"} and not run_started:
                    project.status = ResearchStatus.FAILED
                    project.phase = ResearchPhase.FAILED
                    project.error = getattr(job, "error", None) or "research.advance job failed"
                    project.finished_at = utc_now()
                    project.wait_reason = None
                    self.store.save_project(project)
                    fixed.append(project.project_id)
                    continue

                availability = self._research_worker_availability()
                desired = (
                    None
                    if availability.worker_state == WorkerMeasuredState.AVAILABLE
                    else availability.wait_reason
                )
                if project.wait_reason != desired or project.kernel_job_id != job.job_id:
                    project.kernel_job_id = job.job_id
                    project.wait_reason = desired
                    self.store.save_project(project)

            if len(batch) < page_size:
                break
            offset += page_size
            if offset > 100_000:
                break

        return fixed

    def list_budget_presets(self) -> dict[str, dict]:
        return list_presets()

    def budget_catalog(self) -> dict:
        return budget_catalog()

    def create_project(
        self,
        *,
        title: str | None = None,
        topic: str,
        objective: str = "",
        depth: str | ResearchDepth = ResearchDepth.STANDARD,
        allow_web: bool = False,
        respect_robots_txt: bool = True,
        model_profile: dict[str, Any] | None = None,
        budget_overrides: dict[str, Any] | None = None,
        local_scopes: list[str] | None = None,
        seed_sources: list[str] | None = None,
        connected_datasets: list[dict[str, Any]] | None = None,
        execution_mode: str | ResearchExecutionMode = ResearchExecutionMode.CUSTOM,
    ) -> ResearchProject:
        topic_clean = (topic or "").strip()
        if not topic_clean:
            raise ResearchError("VALIDATION_ERROR", "topic is required", http_status=422)
        depth_enum = ResearchDepth(depth.value if isinstance(depth, ResearchDepth) else str(depth).lower())
        mode = (
            execution_mode
            if isinstance(execution_mode, ResearchExecutionMode)
            else ResearchExecutionMode(str(execution_mode or "normal").lower())
        )
        base = budget_for_depth(depth_enum)
        # Custom may pass overrides; Normal forces 2×10.
        if mode == ResearchExecutionMode.NORMAL:
            budget = resolve_execution_budget(execution_mode=mode, base=base)
        else:
            budget = resolve_execution_budget(
                execution_mode=mode,
                base=merge_budget_overrides(base, budget_overrides),
                overrides=budget_overrides,
            )
        analysis = (
            AnalysisMode.MODEL
            if (model_profile and self.model_caller)
            else AnalysisMode.DETERMINISTIC_FALLBACK
        )
        project = self.store.create_project(
            title=(title or topic_clean)[:200],
            topic=topic_clean,
            objective=objective or "",
            depth=depth_enum,
            allow_web=bool(allow_web),
            respect_robots_txt=bool(respect_robots_txt),
            model_profile=model_profile,
            budget=budget,
            local_scopes=local_scopes,
            seed_sources=seed_sources,
            connected_datasets=connected_datasets,
            execution_mode=mode,
        )
        project.analysis_mode = analysis
        project.total_worker_rounds = (
            0
            if budget.rounds is None
            else int(budget.research_workers) * int(budget.rounds)
        )
        self.store.save_project(project)
        reason = web_unavailable_reason(
            allow_web=project.allow_web,
            allow_outbound=self.allow_outbound,
            provider=self.web,
        )
        project.web_unavailable_reason = reason
        self.store.add_event(project.project_id, "project_created", project.title)
        return project

    def get_project(self, project_id: str) -> ResearchProject:
        project = self.store.get_project(project_id)
        if project is None:
            raise ResearchError("RESEARCH_NOT_FOUND", f"Unknown project: {project_id}", http_status=404)
        project.web_unavailable_reason = web_unavailable_reason(
            allow_web=project.allow_web,
            allow_outbound=self.allow_outbound,
            provider=self.web,
        )
        return project

    def list_projects(self, *, limit: int = 100, offset: int = 0) -> list[ResearchProject]:
        projects = self.store.list_projects(limit=limit, offset=offset)
        for project in projects:
            project.web_unavailable_reason = web_unavailable_reason(
                allow_web=project.allow_web,
                allow_outbound=self.allow_outbound,
                provider=self.web,
            )
        return projects

    def update_project(self, project_id: str, updates: dict[str, Any]) -> ResearchProject:
        project = self.get_project(project_id)
        if project.status in {ResearchStatus.RESEARCHING, ResearchStatus.SYNTHESIZING, ResearchStatus.QUEUED}:
            raise ResearchError(
                "RESEARCH_BUSY",
                "Cannot edit project while research is active",
                http_status=409,
            )
        if "title" in updates and updates["title"] is not None:
            project.title = str(updates["title"]).strip() or project.title
        if "topic" in updates and updates["topic"] is not None:
            project.topic = str(updates["topic"]).strip() or project.topic
        if "objective" in updates and updates["objective"] is not None:
            project.objective = str(updates["objective"])
        if "allow_web" in updates and updates["allow_web"] is not None:
            project.allow_web = bool(updates["allow_web"])
        if "respect_robots_txt" in updates and updates["respect_robots_txt"] is not None:
            project.respect_robots_txt = bool(updates["respect_robots_txt"])
        if "local_scopes" in updates and updates["local_scopes"] is not None:
            project.local_scopes = list(updates["local_scopes"])
        if "seed_sources" in updates and updates["seed_sources"] is not None:
            project.seed_sources = list(updates["seed_sources"])
        if "connected_datasets" in updates and updates["connected_datasets"] is not None:
            project.connected_datasets = list(updates["connected_datasets"])
        if "execution_mode" in updates and updates["execution_mode"] is not None:
            project.execution_mode = ResearchExecutionMode(str(updates["execution_mode"]).lower())
        if "depth" in updates and updates["depth"] is not None:
            project.depth = ResearchDepth(str(updates["depth"]).lower())
            base = budget_for_depth(project.depth)
            project.budget = resolve_execution_budget(
                execution_mode=project.execution_mode,
                base=base,
                overrides=updates.get("budget") if isinstance(updates.get("budget"), dict) else None,
            )
            project.total_rounds = int(project.budget.rounds or 0)
            project.total_worker_rounds = (
                0
                if project.budget.rounds is None
                else int(project.budget.research_workers) * int(project.budget.rounds)
            )
        if "budget" in updates and isinstance(updates["budget"], dict):
            if project.execution_mode == ResearchExecutionMode.NORMAL:
                project.budget = resolve_execution_budget(
                    execution_mode=ResearchExecutionMode.NORMAL,
                    base=project.budget,
                )
            elif project.execution_mode == ResearchExecutionMode.TEAM:
                project.budget = resolve_execution_budget(
                    execution_mode=ResearchExecutionMode.TEAM,
                    base=project.budget,
                    overrides=updates["budget"],
                )
            else:
                project.budget = merge_budget_overrides(project.budget, updates["budget"])
            project.total_rounds = int(project.budget.rounds or 0)
            project.total_worker_rounds = (
                0
                if project.budget.rounds is None
                else int(project.budget.research_workers) * int(project.budget.rounds)
            )
        if "model_profile" in updates and updates["model_profile"] is not None:
            project.model_profile = dict(updates["model_profile"])
            project.analysis_mode = (
                AnalysisMode.MODEL if self.model_caller else AnalysisMode.DETERMINISTIC_FALLBACK
            )
        if project.status == ResearchStatus.COMPLETED:
            pass
        elif project.status not in TERMINAL_STATUSES:
            project.status = ResearchStatus.DRAFT
        self.store.save_project(project)
        self.store.add_event(project_id, "plan_modified", "Project updated")
        return self.get_project(project_id)

    def plan(self, project_id: str, *, edits: dict[str, Any] | None = None) -> ResearchProject:
        """Generate or regenerate a research plan (worker-owned body).

        Control plane must enqueue via :meth:`enqueue_plan` when externalized.
        Bounded manual edits to an already-existing plan use
        :meth:`apply_manual_plan_edits` instead.
        """
        project = self.get_project(project_id)
        plan = build_plan(project)
        if edits:
            plan = apply_plan_edits(plan, edits)
            self.store.add_event(project_id, "plan_modified", "Plan edited by operator")
        else:
            self.store.add_event(project_id, "plan_generated", "Plan generated")
        project.plan = plan
        project.budget = plan.budget
        project.total_rounds = plan.rounds
        project.total_worker_rounds = (
            None
            if plan.rounds is None
            else plan.budget.research_workers * plan.rounds
        )
        project.status = ResearchStatus.PLANNED
        project.phase = ResearchPhase.PLANNING
        project.wait_reason = None
        self.store.save_project(project)
        return self.get_project(project_id)

    def apply_manual_plan_edits(
        self, project_id: str, edits: dict[str, Any]
    ) -> ResearchProject:
        """Bounded operator metadata edits on an already-existing plan.

        Does not rebuild the plan. Control-plane CONTROL_WRITE is allowed.
        """
        project = self.get_project(project_id)
        if project.plan is None:
            raise ResearchError(
                "RESEARCH_PLAN_MISSING",
                "No plan exists yet; enqueue plan generation first",
                http_status=409,
            )
        if not edits:
            return project
        plan = apply_plan_edits(project.plan, edits)
        project.plan = plan
        project.budget = plan.budget
        project.total_rounds = plan.rounds
        project.total_worker_rounds = (
            None
            if plan.rounds is None
            else plan.budget.research_workers * plan.rounds
        )
        self.store.add_event(project_id, "plan_modified", "Plan edited by operator")
        self.store.save_project(project)
        return self.get_project(project_id)

    def enqueue_plan(
        self,
        project_id: str,
        *,
        edits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Enqueue durable ``research.plan`` — fail closed when runtime unbound."""
        project = self.get_project(project_id)
        if self.job_runtime is None:
            raise ResearchError(
                "RESEARCH_WORKER_UNAVAILABLE",
                "JobRuntime not bound; cannot enqueue research.plan",
                http_status=503,
                details={"capability": "research.plan"},
            )
        availability = self._research_worker_availability()
        project.status = ResearchStatus.DRAFT
        project.phase = ResearchPhase.PLANNING
        project.wait_reason = (
            availability.wait_reason
            if availability.worker_state != WorkerMeasuredState.AVAILABLE
            else "QUEUED — research.plan pending"
        )
        project.error = None
        self.store.save_project(project)
        self.store.add_event(
            project_id,
            "plan_queued",
            availability.wait_reason or "Research plan queued for worker execution",
            {
                "can_enqueue": availability.can_enqueue,
                "worker_state": availability.worker_state.value,
                "worker_measured": availability.worker_measured,
            },
        )
        gen = project.updated_at or project.created_at or project_id
        job = self.job_runtime.enqueue(
            capability_id="research.plan",
            arguments={
                "action": "plan",
                "project_id": project_id,
                "edits": edits or None,
            },
            requested_by="api.research.plan",
            domain="research",
            domain_entity_type="research_project",
            domain_entity_id=project_id,
            worker_pool="research",
            resource_class="CPU_HEAVY",
            latency_class="interactive",
            idempotency_key=f"research:plan:{project_id}:{gen}",
            metadata={
                "human_title": project.topic or project.title or project_id,
                "topic": project.topic or project.title,
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
        project = self.get_project(project_id)
        project.kernel_job_id = getattr(job, "job_id", None) or project.kernel_job_id
        self.store.save_project(project)
        self._emit_obs(
            "research.plan_enqueued",
            {
                "project_id": project_id,
                "job_id": getattr(job, "job_id", None),
                "wait_reason": project.wait_reason,
            },
            level="INFO",
            research_project_id=project_id,
            job_id=getattr(job, "job_id", None),
        )
        return {
            "queued": True,
            "job": job.public_dict(),
            "job_id": job.job_id,
            "project": project.public_dict(),
            "plan": project.plan.public_dict() if project.plan else None,
            "status": "QUEUED",
            "truth": {
                "executed_via": "research_worker",
                "fastapi_does_not_build_plan": True,
            },
        }

    def request_plan(
        self,
        project_id: str,
        *,
        edits: dict[str, Any] | None = None,
        regenerate: bool = False,
    ) -> dict[str, Any] | ResearchProject:
        """Control-plane entry: manual edits stay inline; generation is external."""
        project = self.get_project(project_id)
        edits = dict(edits or {})
        # Bounded edits to an existing plan — CONTROL_WRITE, no rebuild.
        if edits and project.plan is not None and not regenerate:
            return self.apply_manual_plan_edits(project_id, edits)
        if self._runners_externalized():
            return self.enqueue_plan(project_id, edits=edits or None)
        if not allow_inprocess_research_execution():
            refuse_inline_research(reason="inprocess_not_allowed", capability="research.plan")
        # Legacy / test in-process path when externalize is off.
        return self.plan(project_id, edits=edits or None)

    def enqueue_web_probe(
        self, *, query: str = "SQLite WAL mode", limit: int = 3
    ) -> dict[str, Any]:
        """Enqueue live web probe — never perform network I/O in FastAPI."""
        if self.job_runtime is None:
            raise ResearchError(
                "RESEARCH_RUNTIME_UNAVAILABLE",
                "JobRuntime not bound; cannot enqueue research.web.probe",
                http_status=503,
                details={"capability": "research.web.probe"},
            )
        safe_limit = max(1, min(int(limit), 5))
        q = (query or "SQLite WAL mode").strip() or "SQLite WAL mode"
        job = self.job_runtime.enqueue(
            capability_id="research.web.probe",
            arguments={
                "action": "web_probe",
                "query": q,
                "limit": safe_limit,
            },
            requested_by="api.research.web.probe",
            domain="research",
            worker_pool="research",
            resource_class="NETWORK_BOUND",
            latency_class="interactive",
            idempotency_key=None,
            metadata={
                "human_title": f"web probe: {q[:80]}",
                "execution_class": "EXTERNAL_REQUIRED",
            },
        )
        return {
            "queued": True,
            "job": job.public_dict(),
            "job_id": job.job_id,
            "probe": {
                "status": "QUEUED",
                "query": q,
                "truth": {
                    "executed_via": "research_worker",
                    "fastapi_does_not_probe_network": True,
                    "persists_artifacts": False,
                },
            },
            "truth": {
                "executed_via": "research_worker",
                "fastapi_does_not_probe_network": True,
            },
        }

    def execute_web_probe(
        self, *, query: str = "SQLite WAL mode", limit: int = 3
    ) -> dict[str, Any]:
        """Worker-owned live web probe body."""
        return self.probe_web_research(query=query, limit=limit)

    def request_web_probe(
        self, *, query: str = "SQLite WAL mode", limit: int = 3
    ) -> dict[str, Any]:
        """Control-plane entry for web probe — external when runners externalized."""
        if self._runners_externalized():
            self._require_external_runtime(capability="research.web.probe")
            return self.enqueue_web_probe(query=query, limit=limit)
        if not allow_inprocess_research_execution():
            refuse_inline_research(
                reason="inprocess_not_allowed",
                capability="research.web.probe",
            )
        return {"probe": self.probe_web_research(query=query, limit=limit)}

    def run(self, project_id: str, *, background: bool = False) -> ResearchProject:
        """User/API start path.

        ``background=True`` (API) enqueues durable execution and returns QUEUED.
        ``background=False`` runs in-process for tests / legacy sync callers.

        When external workers are enabled, ``background=False`` is coerced to enqueue
        unless this process is already a worker (``LEVIATHAN_WORKER_ID`` set).
        """
        project = self.get_project(project_id)
        if project.status in ACTIVE_STATUSES:
            # Idempotent: return current state rather than starting a competing run.
            return project
        if background:
            return self.enqueue_run(project_id)
        if self._runners_externalized():
            import os

            if not os.environ.get("LEVIATHAN_WORKER_ID"):
                return self.enqueue_run(project_id)
        if not allow_inprocess_research_execution():
            return self.enqueue_run(project_id)
        self.runner.run(project_id)
        project = self.get_project(project_id)
        self._maybe_promote_knowledge(project)
        return self.get_project(project_id)

    def execute_queued_run(
        self,
        project_id: str,
        *,
        deepen: bool = False,
        extra_rounds: int = 0,
        resume: bool = False,
        job_id: str | None = None,
        worker_id: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ResearchProject:
        """Worker-owned execution after a canonical ``research.advance`` claim.

        Transitions QUEUED → RESEARCHING via durable CAS, then invokes the
        ResearchCoordinator. Distinct from :meth:`run` / :meth:`enqueue_run`.
        """
        import os

        project = self.get_project(project_id)
        if project.status in {
            ResearchStatus.RESEARCHING,
            ResearchStatus.SYNTHESIZING,
            ResearchStatus.CANCELLING,
        }:
            return project
        if project.status != ResearchStatus.QUEUED:
            raise ResearchError(
                "RESEARCH_NOT_QUEUED",
                (
                    f"execute_queued_run requires QUEUED status "
                    f"(got {project.status.value})"
                ),
                http_status=409,
            )
        if cancel_check is not None and cancel_check():
            self.store.request_cancel(project_id)
            return self.cancel(project_id)

        claimed = self.store.claim_queued_execution(
            project_id,
            worker_pid=os.getpid(),
            kernel_job_id=job_id,
        )
        if not claimed:
            # Lost the race — another physical worker owns execution.
            return self.get_project(project_id)

        self._emit_obs(
            "research.execution_started",
            {
                "project_id": project_id,
                "job_id": job_id,
                "worker_id": worker_id,
                "deepen": bool(deepen),
                "resume": bool(resume),
            },
            level="INFO",
            research_project_id=project_id,
            job_id=job_id,
        )
        self.store.add_event(
            project_id,
            "execution_started",
            "Worker-owned research execution started",
            {"job_id": job_id, "worker_id": worker_id},
        )

        if cancel_check is not None and cancel_check():
            self.store.request_cancel(project_id)
            return self.cancel(project_id)

        try:
            self.runner.run(
                project_id,
                deepen=deepen,
                extra_rounds=extra_rounds,
                resume=resume,
            )
        except Exception as exc:  # noqa: BLE001 — persist + re-raise for job FAILED
            latest = self.get_project(project_id)
            if latest.status not in TERMINAL_STATUSES and latest.status != ResearchStatus.CANCELLED:
                latest.status = ResearchStatus.FAILED
                latest.phase = ResearchPhase.FAILED
                latest.error = f"{type(exc).__name__}: {exc}"
                latest.finished_at = utc_now()
                latest.progress_pct = min(95.0, float(latest.progress_pct or 0))
                self.store.save_project(latest)
                self.store.add_event(project_id, "failed", latest.error or "failed")
            self._emit_obs(
                "research.failed",
                {
                    "project_id": project_id,
                    "job_id": job_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                level="ERROR",
                research_project_id=project_id,
                job_id=job_id,
            )
            raise

        project = self.get_project(project_id)
        try:
            self._maybe_promote_knowledge(project)
        except Exception:  # noqa: BLE001 — promotion never fails the run
            pass
        project = self.get_project(project_id)
        self._emit_obs(
            "research.completed"
            if project.status == ResearchStatus.COMPLETED
            else "research.finished",
            {
                "project_id": project_id,
                "job_id": job_id,
                "status": project.status.value,
                "progress_pct": project.progress_pct,
            },
            level="INFO",
            research_project_id=project_id,
            job_id=job_id,
        )
        return project

    def enqueue_run(
        self,
        project_id: str,
        *,
        deepen: bool = False,
        extra_rounds: int = 0,
        resume: bool = False,
    ) -> ResearchProject:
        project = self.get_project(project_id)
        if project.status in ACTIVE_STATUSES and not deepen and not resume:
            return project
        # Production external mode must never fall open into API threads.
        if self._runners_externalized():
            self._require_external_runtime(capability="research.advance")
        availability = self._research_worker_availability()
        project.status = ResearchStatus.QUEUED
        project.phase = ResearchPhase.PLANNING
        project.error = None
        project.cancel_requested = False
        project.finished_at = None
        project.progress_pct = max(1.0, float(project.progress_pct or 0))
        project.wait_reason = (
            availability.wait_reason
            if availability.worker_state != WorkerMeasuredState.AVAILABLE
            else None
        )
        self.store.save_project(project)
        self.store.add_event(
            project_id,
            "queued",
            availability.wait_reason or "Research queued for execution",
            {
                "can_enqueue": availability.can_enqueue,
                "worker_state": availability.worker_state.value,
                "worker_measured": availability.worker_measured,
            },
        )
        self._emit_obs(
            "research.requested",
            {"project_id": project_id, "deepen": deepen, "resume": resume},
            level="INFO",
            research_project_id=project_id,
        )
        if self._runners_externalized():
            job = self.enqueue_advance(
                project_id,
                deepen=deepen,
                extra_rounds=extra_rounds,
                resume=resume,
            )
            project = self.get_project(project_id)
            project.kernel_job_id = getattr(job, "job_id", None) or project.kernel_job_id
            if (
                availability.worker_state != WorkerMeasuredState.AVAILABLE
                and not project.wait_reason
            ):
                project.wait_reason = availability.wait_reason or (
                    "QUEUED — waiting for research worker"
                )
            self.store.save_project(project)
            self._emit_obs(
                "research.job_enqueued",
                {
                    "project_id": project_id,
                    "job_id": project.kernel_job_id,
                    "wait_reason": project.wait_reason,
                    "worker_state": availability.worker_state.value,
                },
                level="INFO",
                research_project_id=project_id,
                job_id=project.kernel_job_id,
            )
        else:
            if not allow_inprocess_research_execution():
                refuse_inline_research(
                    reason="inprocess_not_allowed",
                    capability="research.advance",
                )
            self._spawn_run(project_id, deepen=deepen, extra_rounds=extra_rounds, resume=resume)
        return self.get_project(project_id)

    def _emit_obs(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        level: str = "INFO",
        **entity: Any,
    ) -> None:
        if self._emit is None:
            return
        try:
            # ObservabilityHub.emit(category, name, *, payload=..., **entity_ids)
            self._emit(
                "research",
                name,
                payload=payload,
                level=level,
                subsystem="research",
                **{k: v for k, v in entity.items() if v is not None},
            )
        except TypeError:
            try:
                self._emit(name, payload)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass

    def _research_worker_availability(self):
        """Return structured availability — UNKNOWN never becomes AVAILABLE."""
        return probe_research_worker_availability(
            db_path=getattr(self.store, "db_path", None),
            runners_are_external=self._runners_externalized(),
        )

    def _spawn_run(
        self,
        project_id: str,
        *,
        deepen: bool,
        extra_rounds: int,
        resume: bool,
    ) -> None:
        if self._runners_externalized() or not allow_inprocess_research_execution():
            refuse_inline_research(
                reason="spawn_run_refused_outside_inprocess_test",
                capability="research.advance",
            )
        with self._bg_lock:
            existing = self._bg_threads.get(project_id)
            if existing and existing.is_alive():
                return

            def _target() -> None:
                try:
                    self.runner.run(
                        project_id,
                        deepen=deepen,
                        extra_rounds=extra_rounds,
                        resume=resume,
                    )
                    try:
                        self._maybe_promote_knowledge(self.get_project(project_id))
                    except Exception:  # noqa: BLE001 — promotion never fails the run
                        pass
                except Exception:  # noqa: BLE001 — runner persists failure
                    pass
                finally:
                    with self._bg_lock:
                        self._bg_threads.pop(project_id, None)

            thread = threading.Thread(
                target=_target,
                name=f"research-run-{project_id[:8]}",
                daemon=True,
            )
            self._bg_threads[project_id] = thread
            thread.start()

    def cancel(self, project_id: str) -> ResearchProject:
        project = self.get_project(project_id)
        if project.status in TERMINAL_STATUSES and project.status != ResearchStatus.INTERRUPTED:
            if project.status == ResearchStatus.CANCELLED:
                return project
            raise ResearchError(
                "RESEARCH_TERMINAL",
                f"Project already terminal: {project.status.value}",
                http_status=409,
            )
        self.store.request_cancel(project_id)
        self.store.add_event(project_id, "cancelled", "Cancel requested")

        kernel_cancel_error: str | None = None
        kernel_cancel_state: str | None = None
        kernel_cancel_acked = False
        # Mirror cancel onto the kernel job when linked — failures must be observable.
        if project.kernel_job_id and self.job_runtime is not None:
            try:
                from Data.modules.jobs.states import JobState

                jstore = getattr(self.job_runtime, "store", None)
                if jstore is not None:
                    job = jstore.get(project.kernel_job_id)
                    if job is not None and job.state not in {
                        JobState.COMPLETED,
                        JobState.FAILED,
                        JobState.CANCELLED,
                    }:
                        if hasattr(self.job_runtime, "cancel"):
                            cancelled_job = self.job_runtime.cancel(
                                project.kernel_job_id,
                                reason="research project cancel",
                            )
                            state = getattr(cancelled_job, "state", None) or getattr(
                                job, "state", None
                            )
                        elif hasattr(jstore, "request_cancel"):
                            jstore.request_cancel(
                                project.kernel_job_id,
                                reason="research project cancel",
                            )
                            state = JobState.CANCEL_REQUESTED
                        else:
                            jstore.transition(
                                project.kernel_job_id,
                                JobState.CANCEL_REQUESTED
                                if hasattr(JobState, "CANCEL_REQUESTED")
                                else JobState.CANCELLED,
                                error="research project cancel",
                            )
                            state = JobState.CANCEL_REQUESTED
                        kernel_cancel_state = (
                            state.value if hasattr(state, "value") else str(state)
                        )
                        kernel_cancel_acked = True
                    elif job is not None:
                        kernel_cancel_state = (
                            job.state.value if hasattr(job.state, "value") else str(job.state)
                        )
                        kernel_cancel_acked = True
            except Exception as exc:  # noqa: BLE001 — record, do not pretend cancelled
                kernel_cancel_error = f"{type(exc).__name__}: {exc}"
                self.store.add_event(
                    project_id,
                    "cancel_kernel_failed",
                    kernel_cancel_error,
                    {"kernel_job_id": project.kernel_job_id},
                )
                self._emit_obs(
                    "research.cancel_kernel_failed",
                    {
                        "project_id": project_id,
                        "kernel_job_id": project.kernel_job_id,
                        "error": kernel_cancel_error,
                    },
                    level="ERROR",
                    research_project_id=project_id,
                    job_id=project.kernel_job_id,
                )
        elif project.kernel_job_id and self.job_runtime is None:
            kernel_cancel_error = "job_runtime_unbound"
            self.store.add_event(
                project_id,
                "cancel_kernel_failed",
                "JobRuntime unbound; kernel cancel not acknowledged",
                {"kernel_job_id": project.kernel_job_id},
            )

        latest = self.get_project(project_id)
        profile = dict(latest.model_profile or {})
        profile["cancel_ack_at"] = utc_now()
        profile["cancel_ack_job_state"] = kernel_cancel_state
        profile["cancel_ack_error"] = kernel_cancel_error
        latest.model_profile = profile
        self.store.save_project(latest)

        with self._bg_lock:
            alive = bool(
                self._bg_threads.get(project_id) and self._bg_threads[project_id].is_alive()
            )
        # Only mark terminal CANCELLED when execution is not running AND kernel
        # cancel was acknowledged (or there was no kernel job).
        can_terminal_cancel = (
            latest.status
            in {
                ResearchStatus.DRAFT,
                ResearchStatus.PLANNED,
                ResearchStatus.QUEUED,
                ResearchStatus.INTERRUPTED,
                ResearchStatus.CANCELLING,
            }
            and not alive
            and latest.worker_pid is None
            and (not latest.kernel_job_id or kernel_cancel_acked)
        )
        if can_terminal_cancel:
            latest = self.get_project(project_id)
            latest.status = ResearchStatus.CANCELLED
            latest.phase = ResearchPhase.CANCELLED
            latest.cancel_requested = False
            latest.worker_pid = None
            latest.finished_at = utc_now()
            latest.error = latest.error or "Cancelled by request"
            latest.progress_pct = min(95.0, float(latest.progress_pct or 0))
            latest.wait_reason = None
            profile = dict(latest.model_profile or {})
            profile["cancel_ack_at"] = profile.get("cancel_ack_at") or utc_now()
            profile["cancel_ack_job_state"] = kernel_cancel_state or profile.get(
                "cancel_ack_job_state"
            )
            profile["cancel_ack_error"] = kernel_cancel_error
            latest.model_profile = profile
            self.store.save_project(latest)
            if latest.kernel_job_id and self.job_runtime is not None and kernel_cancel_acked:
                try:
                    from Data.modules.jobs.states import JobState

                    jstore = self.job_runtime.store
                    job = jstore.get(latest.kernel_job_id)
                    if job is not None and job.state in {
                        JobState.QUEUED,
                        JobState.CANCEL_REQUESTED,
                    }:
                        jstore.transition(
                            latest.kernel_job_id,
                            JobState.CANCELLED,
                            error="research project cancelled before claim",
                        )
                except Exception as exc:  # noqa: BLE001
                    latest = self.get_project(project_id)
                    profile = dict(latest.model_profile or {})
                    profile["cancel_ack_error"] = f"{type(exc).__name__}: {exc}"
                    latest.model_profile = profile
                    latest.status = ResearchStatus.CANCELLING
                    latest.cancel_requested = True
                    self.store.save_project(latest)
                    self.store.add_event(
                        project_id,
                        "cancel_kernel_failed",
                        profile["cancel_ack_error"],
                        {"kernel_job_id": latest.kernel_job_id, "phase": "terminal_transition"},
                    )
        elif kernel_cancel_error and latest.kernel_job_id:
            # Keep CANCELLING — do not claim CANCELLED while kernel may still run.
            latest = self.get_project(project_id)
            if latest.status not in TERMINAL_STATUSES:
                latest.status = ResearchStatus.CANCELLING
                latest.cancel_requested = True
                self.store.save_project(latest)
        return self.get_project(project_id)

    def resume(self, project_id: str, *, background: bool = False) -> ResearchProject:
        project = self.get_project(project_id)
        if project.status not in {
            ResearchStatus.INTERRUPTED,
            ResearchStatus.FAILED,
            ResearchStatus.CANCELLED,
            ResearchStatus.PLANNED,
            ResearchStatus.DRAFT,
        }:
            if project.status == ResearchStatus.COMPLETED:
                raise ResearchError(
                    "RESEARCH_COMPLETED",
                    "Project already completed; use deepen instead of resume",
                    http_status=409,
                )
            if project.status in ACTIVE_STATUSES:
                return project
            raise ResearchError(
                "RESEARCH_NOT_RESUMABLE",
                f"Cannot resume from status {project.status.value}",
                http_status=409,
            )
        self.store.add_event(project_id, "round_started", "Resume requested")
        if background:
            return self.enqueue_run(project_id, resume=True)
        if self._runners_externalized():
            import os

            if not os.environ.get("LEVIATHAN_WORKER_ID"):
                return self.enqueue_run(project_id, resume=True)
        self.runner.run(project_id, resume=True)
        project = self.get_project(project_id)
        self._maybe_promote_knowledge(project)
        return self.get_project(project_id)

    def deepen(
        self,
        project_id: str,
        *,
        extra_rounds: int = 1,
        background: bool = False,
    ) -> ResearchProject:
        project = self.get_project(project_id)
        if project.status not in {
            ResearchStatus.COMPLETED,
            ResearchStatus.INTERRUPTED,
            ResearchStatus.FAILED,
        }:
            raise ResearchError(
                "RESEARCH_NOT_DEEPENABLE",
                f"Cannot deepen from status {project.status.value}",
                http_status=409,
            )
        if background:
            return self.enqueue_run(
                project_id, deepen=True, extra_rounds=max(1, int(extra_rounds))
            )
        if self._runners_externalized():
            import os

            if not os.environ.get("LEVIATHAN_WORKER_ID"):
                return self.enqueue_run(
                    project_id, deepen=True, extra_rounds=max(1, int(extra_rounds))
                )
        self.runner.run(
            project_id, deepen=True, extra_rounds=max(1, int(extra_rounds))
        )
        project = self.get_project(project_id)
        self._maybe_promote_knowledge(project)
        return self.get_project(project_id)

    def _maybe_promote_knowledge(self, project: ResearchProject) -> None:
        """Promote verified claims after COMPLETED. Never fails research completion.

        Research COMPLETED ≠ knowledge learned. Status is stored separately.
        """
        if project.status != ResearchStatus.COMPLETED:
            return
        if not bool(getattr(self, "auto_promote_verified_knowledge", True)):
            profile = dict(project.model_profile or {})
            profile["knowledge_promotion_status"] = KnowledgePromotionStatus.NOT_REQUESTED.value
            project.model_profile = profile
            self.store.save_project(project)
            return
        if self.assimilation_service is None or self.knowledge is None:
            profile = dict(project.model_profile or {})
            profile["knowledge_promotion_status"] = KnowledgePromotionStatus.NOT_REQUESTED.value
            project.model_profile = profile
            self.store.save_project(project)
            return
        if not hasattr(self.assimilation_service, "assimilate_research_project"):
            profile = dict(project.model_profile or {})
            profile["knowledge_promotion_status"] = KnowledgePromotionStatus.NOT_REQUESTED.value
            project.model_profile = profile
            self.store.save_project(project)
            return
        claims = self.store.list_claims(project.project_id)
        evidence = self.store.list_evidence(project.project_id)
        profile = dict(project.model_profile or {})
        profile["knowledge_promotion_status"] = KnowledgePromotionStatus.RUNNING.value
        project.model_profile = profile
        self.store.save_project(project)
        try:
            receipt = self.assimilation_service.assimilate_research_project(
                project,
                claims=claims,
                evidence=evidence,
                knowledge_store=self.knowledge,
                atlas_store=self.atlas_store,
            )
            receipt_dict = (
                receipt.public_dict() if hasattr(receipt, "public_dict") else dict(receipt or {})
            )
            failures = int(receipt_dict.get("failure_count") or 0)
            successes = int(receipt_dict.get("success_count") or 0)
            if receipt_dict.get("ok") is False or (failures > 0 and successes == 0):
                promo_status = KnowledgePromotionStatus.FAILED.value
            elif failures > 0 and successes > 0:
                promo_status = KnowledgePromotionStatus.PARTIAL.value
            elif receipt_dict.get("ok") is True or successes > 0:
                promo_status = KnowledgePromotionStatus.COMPLETED.value
            else:
                promo_status = KnowledgePromotionStatus.UNKNOWN.value
            project.model_profile = {
                **dict(project.model_profile or {}),
                "knowledge_promotion": receipt_dict,
                "knowledge_promotion_status": promo_status,
                "knowledge_promotion_error": None,
            }
            self.store.save_project(project)
            self.store.add_event(
                project.project_id,
                "knowledge_promoted",
                "Research claims assimilated into knowledge",
                {
                    "receipt_id": receipt_dict.get("receipt_id"),
                    "ok": receipt_dict.get("ok"),
                    "status": promo_status,
                    "success_count": receipt_dict.get("success_count"),
                    "skipped_count": receipt_dict.get("skipped_count"),
                    "failure_count": receipt_dict.get("failure_count"),
                },
            )
            if self._emit is not None:
                self._emit(
                    "research",
                    "knowledge_promoted",
                    payload={
                        "project_id": project.project_id,
                        "receipt_id": receipt_dict.get("receipt_id"),
                        "ok": receipt_dict.get("ok"),
                        "status": promo_status,
                        "success_count": receipt_dict.get("success_count"),
                        "document_ids": list(receipt_dict.get("document_ids") or [])[:20],
                    },
                    success=bool(receipt_dict.get("ok")),
                )
        except Exception as exc:  # noqa: BLE001 — promotion must not fail research
            error_payload = {
                "error": f"{type(exc).__name__}: {exc}",
                "project_id": project.project_id,
                "code": "KNOWLEDGE_PROMOTION_FAILED",
            }
            try:
                project.model_profile = {
                    **dict(project.model_profile or {}),
                    "knowledge_promotion_error": error_payload,
                    "knowledge_promotion_status": KnowledgePromotionStatus.FAILED.value,
                }
                self.store.save_project(project)
                self.store.add_event(
                    project.project_id,
                    "knowledge_promotion_failed",
                    str(exc),
                    error_payload,
                )
            except Exception:  # noqa: BLE001
                pass
            if self._emit is not None:
                try:
                    self._emit(
                        "research",
                        "knowledge_promotion_failed",
                        payload=error_payload,
                        level="warning",
                        success=False,
                    )
                except Exception:  # noqa: BLE001
                    pass

    def upload_source(
        self,
        project_id: str,
        *,
        filename: str,
        stream: BinaryIO,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if self.source_ingestion is not None:
            result = self.source_ingestion.accept_upload(
                project.project_id,
                filename=filename,
                stream=stream,
                content_type=content_type,
            )
            is_archive = result.get("source_type") == "archive"
            source_id = str(result.get("source_id") or "")
            # TEST-ONLY: inprocess_test drain under mechanical allow gate.
            # Production fabric path never parses / extracts / OCR here.
            self._maybe_drain_source_ingestion_inprocess(
                source_id, is_archive=bool(is_archive), idempotent=bool(result.get("idempotent"))
            )
            source = self.store.get_source(source_id)
            progress = self.source_ingestion.get_status(source_id)
            text_chars = 0
            page_count = None
            from Data.modules.source_ingestion.execution_gate import allow_inprocess_execution

            inprocess = allow_inprocess_execution(self.source_ingestion.settings)
            if source and source.snapshot_path and inprocess:
                try:
                    text_chars = len(Path(source.snapshot_path).read_text(encoding="utf-8"))
                except OSError:
                    text_chars = 0
                page_count = (source.provenance or {}).get("page_count")
            elif source:
                page_count = (source.provenance or {}).get("page_count")
                text_chars = int((source.provenance or {}).get("extracted_chars") or 0)

            # Backward-compatible honesty for single-file uploads: raise on hard failures
            # the way UploadIngestor historically did (archives use aggregate status instead).
            if not is_archive and source is not None:
                meta = source.metadata or {}
                prov = source.provenance or {}
                err_code = prov.get("error_code") or meta.get("error_code")
                skip_reason = (
                    (meta.get("quarantine_reason") or meta.get("skip_reason") or source.brain_error)
                    or ""
                )
                if source.parse_status.value == "failed":
                    code = str(err_code or "SOURCE_PARSE_FAILED")
                    raise ResearchError(
                        code,
                        str(skip_reason or source.brain_error or "Parse failed"),
                        http_status=422,
                        details={"source_id": source_id, "filename": filename},
                    )
                if source.parse_status.value == "skipped":
                    if "secrets" in str(skip_reason) or "quarantine" in str(skip_reason):
                        pass  # quarantined secrets stay durable without raising
                    else:
                        kind = (prov.get("detection") or {}).get("kind")
                        ext = Path(filename).suffix.lower()
                        if (
                            kind == "binary"
                            or ext in {".exe", ".dll", ".so", ".dylib", ".bin"}
                            or "binary" in str(skip_reason)
                            or "unsupported" in str(skip_reason)
                            or "ocr_unavailable" in str(skip_reason)
                        ):
                            raise ResearchError(
                                "UNSUPPORTED_SOURCE_TYPE",
                                f"Unsupported file type: {ext or '(none)'}",
                                http_status=422,
                                details={"filename": filename, "reason": skip_reason or "binary"},
                            )

            return {
                "source_id": source_id,
                "job_id": result.get("job_id"),
                "status": progress.status.value,
                "source_type": result.get("source_type"),
                "filename": result.get("filename"),
                "source": (source.public_dict() if source else result.get("source")),
                "extracted_chars": text_chars,
                "page_count": page_count,
                "progress": progress.public_dict(),
            }

        # Fail closed: never fall back to synchronous UploadIngestor PDF/text parse.
        raise ResearchError(
            "SOURCE_INGESTION_UNAVAILABLE",
            "Source ingestion worker path required; synchronous PDF parse fallback disabled",
            http_status=503,
            details={"filename": filename},
        )

    def _maybe_drain_source_ingestion_inprocess(
        self,
        source_id: str,
        *,
        is_archive: bool = False,
        idempotent: bool = False,
    ) -> None:
        """TEST-ONLY helper: claim/process one SI job when inprocess_test allow gate is open.

        Production ResearchService must never call process_next / process_source.
        """
        if idempotent or self.source_ingestion is None:
            return
        from Data.modules.source_ingestion.execution_gate import allow_inprocess_execution

        if not allow_inprocess_execution(self.source_ingestion.settings):
            return
        if self.source_ingestion.jobs is not None:
            self.source_ingestion.process_next()
            if is_archive:
                pending = self.source_ingestion.get_status(source_id).files_pending
                if pending > 0:
                    self.source_ingestion.pipeline().process_source(source_id)
        else:
            self.source_ingestion.pipeline().process_source(source_id)

    def get_ingestion_status(self, project_id: str, source_id: str) -> dict[str, Any]:
        self.get_project(project_id)
        source = self.store.get_source(source_id)
        if source is None or source.project_id != project_id:
            raise ResearchError("SOURCE_NOT_FOUND", source_id, http_status=404)
        if self.source_ingestion is None:
            return {"source": source.public_dict()}
        progress = self.source_ingestion.get_status(source_id)
        out: dict[str, Any] = {
            "source": source.public_dict(),
            "progress": progress.public_dict(),
        }
        prov = source.provenance or {}
        if prov.get("ocr") or prov.get("ocr_job"):
            out["ocr"] = prov.get("ocr") or prov.get("ocr_job")
        if prov.get("dataset_route"):
            out["dataset_route"] = prov.get("dataset_route")
        container = self.source_ingestion.ingestion.get_container(source_id)
        if container:
            out["container"] = {
                "phase": container.get("phase"),
                "job_id": container.get("job_id"),
                "cancel_requested": container.get("cancel_requested"),
                "error": container.get("error"),
            }
            out["progress_meta"] = container.get("progress") or {}
        try:
            from Data.modules.source_ingestion.capabilities import build_format_capabilities
            from Data.modules.source_ingestion.metrics import ingestion_metrics

            out["format_capabilities"] = build_format_capabilities(self.source_ingestion.settings)
            out["metrics"] = ingestion_metrics().public_dict()
        except Exception:  # noqa: BLE001 — diagnostics must not break status
            pass
        return out

    def list_ingestion_children(
        self,
        project_id: str,
        source_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
        outcome: str | None = None,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        source = self.store.get_source(source_id)
        if source is None or source.project_id != project_id:
            raise ResearchError("SOURCE_NOT_FOUND", source_id, http_status=404)
        if self.source_ingestion is None:
            return {"source_id": source_id, "members": [], "total": 0}
        return self.source_ingestion.list_children(
            source_id, offset=offset, limit=limit, outcome=outcome
        )

    def cancel_ingestion(self, project_id: str, source_id: str) -> dict[str, Any]:
        self.get_project(project_id)
        source = self.store.get_source(source_id)
        if source is None or source.project_id != project_id:
            raise ResearchError("SOURCE_NOT_FOUND", source_id, http_status=404)
        if self.source_ingestion is None:
            raise ResearchError("SOURCE_INGESTION_UNAVAILABLE", "Not configured", http_status=503)
        return {"progress": self.source_ingestion.cancel(source_id)}

    def retry_ingestion(
        self,
        project_id: str,
        source_id: str,
        *,
        failed_only: bool = True,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        source = self.store.get_source(source_id)
        if source is None or source.project_id != project_id:
            raise ResearchError("SOURCE_NOT_FOUND", source_id, http_status=404)
        if self.source_ingestion is None:
            raise ResearchError("SOURCE_INGESTION_UNAVAILABLE", "Not configured", http_status=503)
        result = self.source_ingestion.retry(source_id, failed_only=failed_only)
        # TEST-ONLY drain — production only enqueues.
        self._maybe_drain_source_ingestion_inprocess(source_id, is_archive=False, idempotent=False)
        from Data.modules.source_ingestion.execution_gate import allow_inprocess_execution

        if allow_inprocess_execution(self.source_ingestion.settings):
            result["progress"] = self.source_ingestion.get_status(source_id).public_dict()
        return result

    def retry_ingestion_brain(self, project_id: str, source_id: str) -> dict[str, Any]:
        self.get_project(project_id)
        source = self.store.get_source(source_id)
        if source is None or source.project_id != project_id:
            raise ResearchError("SOURCE_NOT_FOUND", source_id, http_status=404)
        # Production: always durable enqueue. Never inline Knowledge sync / reparse.
        if self.source_ingestion is not None:
            from Data.modules.source_ingestion.execution_gate import allow_inprocess_execution

            if allow_inprocess_execution(self.source_ingestion.settings):
                return self.source_ingestion.retry_brain(source_id)
            return self.source_ingestion.enqueue_brain_retry(source_id)
        if self.job_runtime is not None:
            return self._enqueue_source_brain_retry(project_id, source_id)
        raise ResearchError(
            "SOURCE_INGESTION_UNAVAILABLE",
            "Brain retry requires source_ingestion worker / JobRuntime",
            http_status=503,
            details={"source_id": source_id},
        )

    def _enqueue_source_brain_retry(self, project_id: str, source_id: str) -> dict[str, Any]:
        job = self.job_runtime.enqueue(
            capability_id="source_ingestion.brain_retry",
            arguments={"source_id": source_id, "project_id": project_id},
            requested_by="api.research.brain_retry",
            domain="source_ingestion",
            domain_entity_type="source",
            domain_entity_id=source_id,
            worker_pool="source_ingestion",
            resource_class="CPU_HEAVY",
            latency_class="background",
            idempotency_key=f"source_ingestion:brain_retry:{source_id}",
            metadata={"human_title": source_id, "filename": (self.store.get_source(source_id) or type("X", (), {"title": source_id})).title},
        )
        return {
            "queued": True,
            "job_id": job.job_id,
            "job": job.public_dict(),
            "source_id": source_id,
            "status": "QUEUED",
        }

    def add_url_source(self, project_id: str, url: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        cleaned = (url or "").strip()
        if not cleaned:
            raise ResearchError("VALIDATION_ERROR", "url is required", http_status=422)
        # Control-plane SSRF shape check (no remote HTTP wait). Full DNS on worker.
        decision = validate_url_for_fetch(cleaned, resolve_dns=not self._runners_externalized())
        if not decision.allowed:
            raise ResearchError(
                "URL_BLOCKED",
                decision.reason or "URL blocked by SSRF policy",
                http_status=400,
                details={"url": cleaned, "reason": decision.reason},
            )
        if self._runners_externalized():
            self._require_external_runtime(capability="research.fetch_url")
            return self._enqueue_url_fetch(project_id, cleaned)
        if not allow_inprocess_research_execution():
            refuse_inline_research(
                reason="inprocess_not_allowed",
                capability="research.fetch_url",
            )
        return self._fetch_url_source_inline(project_id, cleaned)

    def _enqueue_url_fetch(self, project_id: str, url: str) -> dict[str, Any]:
        from .types import BrainStatus, ParseStatus, ResearchSource, SourceType
        from .store import utc_now
        import uuid as _uuid

        source_id = str(_uuid.uuid4())
        pending = ResearchSource(
            source_id=source_id,
            project_id=project_id,
            source_type=SourceType.WEB_PAGE,
            original_uri=url,
            canonical_uri=url,
            title=url,
            fetched_at=None,
            content_hash=None,
            mime_type="text/html",
            snapshot_path=None,
            parse_status=ParseStatus.PENDING,
            parser=None,
            brain_status=BrainStatus.PENDING,
            provenance={"url": url, "pending_fetch": True},
            metadata={"url": url, "fetch_status": "PENDING"},
            created_at=utc_now(),
        )
        stored = self.store.upsert_source(pending)
        job = self.job_runtime.enqueue(
            capability_id="research.fetch_url",
            arguments={
                "action": "fetch_url",
                "project_id": project_id,
                "url": url,
                "source_id": stored.source_id,
            },
            requested_by="api.research.add_url",
            domain="research",
            domain_entity_type="source",
            domain_entity_id=stored.source_id,
            worker_pool="research",
            resource_class="NETWORK_BOUND",
            latency_class="interactive",
            idempotency_key=f"research:fetch_url:{project_id}:{stored.source_id}",
            metadata={"human_title": url, "topic": url, "filename": url},
        )
        self.store.add_event(
            project_id,
            "source_fetch_queued",
            url,
            {"source_id": stored.source_id, "job_id": job.job_id, "url": url},
        )
        return {
            "queued": True,
            "job": job.public_dict(),
            "job_id": job.job_id,
            "source": stored.public_dict(),
            "status": "PENDING",
            "truth": {"executed_via": "research_worker", "fetch_deferred": True},
        }

    def _fetch_url_source_inline(
        self,
        project_id: str,
        cleaned: str,
        *,
        reserved_source_id: str | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        reason = web_unavailable_reason(
            allow_web=True,
            allow_outbound=self.allow_outbound,
            provider=self.web,
        )
        if reason:
            seeds = list(project.seed_sources)
            if cleaned not in seeds:
                seeds.append(cleaned)
                project.seed_sources = seeds
                self.store.save_project(project)
            raise ResearchError(
                "WEB_SEARCH_UNCONFIGURED" if "unconfigured" in reason else "WEB_UNAVAILABLE",
                f"Cannot fetch URL: {reason}",
                http_status=503,
                details={"reason": reason, "url": cleaned, "seeded": True},
            )
        try:
            page = self.web.fetch_page(
                cleaned,
                respect_robots_txt=project.respect_robots_txt,
            )
        except Exception as exc:  # noqa: BLE001
            raise ResearchError(
                "SOURCE_FETCH_FAILED",
                str(exc),
                http_status=502,
                details={"url": cleaned, "source_id": reserved_source_id},
            ) from exc
        from .sources import ResearchSourceCollector

        ingestor = ResearchSourceCollector(self.store, self.snapshots_root)
        source, text = ingestor.from_web_page(
            project_id,
            page,
            reserved_source_id=reserved_source_id,
        )
        try:
            synced = self.brain.sync_web_page(source, text)
        except Exception as exc:  # noqa: BLE001 — source fetched; brain sync failure visible
            from dataclasses import replace

            from .types import BrainStatus

            meta = dict(source.metadata or {})
            meta["fetch_status"] = "FETCHED"
            meta["brain_sync_error"] = f"{type(exc).__name__}: {exc}"
            failed = self.store.save_source(
                replace(
                    source,
                    brain_status=BrainStatus.FAILED,
                    metadata=meta,
                )
            )
            self.store.add_event(
                project_id,
                "brain_sync_failed",
                str(exc),
                {"source_id": failed.source_id, "url": cleaned, "stage": "web_page"},
            )
            return {
                "source": failed.public_dict(),
                "brain_sync": {"ok": False, "error": str(exc)},
            }
        self.store.add_event(
            project_id,
            "source_fetched",
            synced.title or cleaned,
            {"source_id": synced.source_id, "url": cleaned},
        )
        return {"source": synced.public_dict(), "brain_sync": {"ok": True}}

    def execute_fetch_url(
        self,
        project_id: str,
        url: str,
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """Worker-owned URL fetch + Brain sync.

        When ``source_id`` names a reserved PENDING source, that durable identity
        is transitioned (PENDING → OK/FAILED) rather than minting a second row.
        """
        from dataclasses import replace

        from .sources import ResearchSourceCollector
        from .types import BrainStatus, ParseStatus

        reserved = None
        if source_id:
            reserved = self.store.get_source(source_id)
            if reserved is None or reserved.project_id != project_id:
                raise ResearchError(
                    "SOURCE_IDENTITY_CONFLICT",
                    f"Reserved source_id {source_id} not found for project",
                    http_status=409,
                    details={"source_id": source_id, "project_id": project_id},
                )
            # Mark FETCHING for operator truth before network I/O.
            meta = dict(reserved.metadata or {})
            meta["fetch_status"] = "FETCHING"
            prov = dict(reserved.provenance or {})
            prov["pending_fetch"] = True
            reserved = self.store.save_source(
                replace(reserved, metadata=meta, provenance=prov)
            )

        try:
            result = self._fetch_url_source_inline(
                project_id,
                url,
                reserved_source_id=source_id,
            )
        except ResearchError as exc:
            if reserved is not None:
                meta = dict(reserved.metadata or {})
                meta["fetch_status"] = "FAILED"
                meta["fetch_error"] = exc.message
                reserved = self.store.save_source(
                    replace(
                        reserved,
                        parse_status=ParseStatus.FAILED,
                        brain_status=BrainStatus.FAILED,
                        metadata=meta,
                    )
                )
                self.store.add_event(
                    project_id,
                    "source_fetch_failed",
                    exc.message,
                    {"source_id": reserved.source_id, "code": exc.code},
                )
            raise
        except Exception as exc:  # noqa: BLE001
            if reserved is not None:
                meta = dict(reserved.metadata or {})
                meta["fetch_status"] = "FAILED"
                meta["fetch_error"] = f"{type(exc).__name__}: {exc}"
                reserved = self.store.save_source(
                    replace(
                        reserved,
                        parse_status=ParseStatus.FAILED,
                        brain_status=BrainStatus.FAILED,
                        metadata=meta,
                    )
                )
            raise ResearchError(
                "SOURCE_FETCH_FAILED",
                str(exc),
                http_status=502,
                details={"url": url, "source_id": source_id},
            ) from exc
        return result

    def connect_dataset(
        self,
        project_id: str,
        *,
        dataset_id: str,
        version_id: str | None = None,
        indexed: bool | None = None,
        label: str | None = None,
    ) -> ResearchProject:
        """Connect a dataset only after DatasetService canonical learning verification.

        Caller-supplied ``indexed`` is advisory/backward-compatible and never grants
        authority.
        """
        project = self.get_project(project_id)
        if not dataset_id:
            raise ResearchError("VALIDATION_ERROR", "dataset_id is required", http_status=422)

        learning = self._resolve_canonical_dataset_learning(
            dataset_id, version_id=version_id
        )
        canonical_state = str(learning.get("canonical_state") or "")
        index_usable = bool(learning.get("index_usable") or learning.get("learned"))
        if not index_usable:
            raise ResearchError(
                "DATASET_NOT_LEARNED",
                (
                    "Dataset is not in a usable learned/indexed state "
                    f"(canonical={canonical_state or 'UNKNOWN'}; "
                    f"client_indexed={indexed!r} ignored as authority)"
                ),
                http_status=409,
                details={
                    "dataset_id": dataset_id,
                    "version_id": version_id or learning.get("version_id"),
                    "canonical_state": canonical_state or "UNKNOWN",
                    "client_indexed": indexed,
                    "learning": {
                        k: learning.get(k)
                        for k in (
                            "canonical_state",
                            "version_id",
                            "index_ref",
                            "learned",
                            "index_usable",
                            "brainStatus",
                            "usableIndexId",
                        )
                        if k in learning
                    },
                },
            )

        if version_id and learning.get("version_matches") is False:
            raise ResearchError(
                "DATASET_VERSION_MISMATCH",
                "Requested dataset version is not the learned/indexed version",
                http_status=409,
                details={
                    "dataset_id": dataset_id,
                    "requested_version_id": version_id,
                    "learned_version_id": learning.get("learned_version_id"),
                },
            )

        resolved_version = str(
            version_id or learning.get("version_id") or ""
        ) or None
        entry = {
            "dataset_id": dataset_id,
            "version_id": resolved_version,
            "indexed": True,
            "label": label or dataset_id,
            "canonical_state": canonical_state or None,
            "client_indexed_advisory": indexed,
            "verified_by": "DatasetService",
            "index_ref": learning.get("index_ref"),
        }
        from Data.modules.datasets.knowledge_identity import research_scopes_for_dataset

        scopes_for_ds = research_scopes_for_dataset(
            dataset_id, version_id=resolved_version
        )
        entry["knowledge_scopes"] = list(scopes_for_ds)
        entry["canonical_knowledge_source"] = scopes_for_ds[0] if scopes_for_ds else None
        datasets = [d for d in project.connected_datasets if d.get("dataset_id") != dataset_id]
        datasets.append(entry)
        project.connected_datasets = datasets
        scopes = list(project.local_scopes)
        # Remove ambiguous legacy bare "dataset" and "dataset:dataset" scopes.
        scopes = [
            s
            for s in scopes
            if s not in {"dataset", "dataset:dataset"}
        ]
        for scope in scopes_for_ds:
            if scope not in scopes:
                scopes.append(scope)
        project.local_scopes = scopes
        self.store.save_project(project)
        self.store.add_event(
            project_id,
            "dataset_connected",
            entry["label"],
            entry,
        )
        return self.get_project(project_id)

    def _resolve_canonical_dataset_learning(
        self,
        dataset_id: str,
        *,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve learning truth via DatasetService — never from client booleans."""
        ds = getattr(self, "dataset_service", None)
        if ds is None:
            ds = getattr(self, "_dataset_service", None)
        if ds is None:
            raise ResearchError(
                "DATASET_NOT_LEARNED",
                "DatasetService not bound; cannot verify canonical learning state",
                http_status=503,
                details={"dataset_id": dataset_id, "version_id": version_id},
            )
        try:
            if hasattr(ds, "learning_state_for_dataset"):
                state = ds.learning_state_for_dataset(dataset_id)
            elif hasattr(ds, "brain_status_for_dataset"):
                state = ds.brain_status_for_dataset(dataset_id)
            else:
                raise ResearchError(
                    "DATASET_NOT_LEARNED",
                    "DatasetService lacks learning_state_for_dataset",
                    http_status=503,
                    details={"dataset_id": dataset_id},
                )
        except ResearchError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ResearchError(
                "DATASET_NOT_LEARNED",
                f"Failed to resolve dataset learning state: {type(exc).__name__}: {exc}",
                http_status=503,
                details={"dataset_id": dataset_id},
            ) from exc
        if not isinstance(state, dict):
            state = dict(getattr(state, "public_dict", lambda: {})())
        out = dict(state)
        # Normalize camelCase DatasetLearningState.public_dict → snake for Research.
        canon = (
            out.get("canonical_state")
            or out.get("canonicalState")
            or out.get("state")
            or out.get("learning_state")
            or ""
        )
        out["canonical_state"] = str(canon)
        out["version_id"] = out.get("version_id") or out.get("versionId")
        out["learned_version_id"] = out.get("version_id")
        out["index_version_id"] = out.get("version_id")
        out["learned"] = bool(out.get("learned"))
        out["index_usable"] = bool(
            out.get("learned")
            or out.get("usableIndexId")
            or out.get("usable_index_id")
            or str(canon).upper() in {"LEARNED", "STALE_JOB"}
        )
        out["retrieval_ready"] = out["index_usable"]
        out["index_ref"] = out.get("usableIndexId") or out.get("indexId") or out.get("index_id")
        if version_id:
            out["requested_version_id"] = version_id
            # Reject if a specific version was requested but learned version differs.
            learned_v = out.get("version_id")
            if learned_v and str(version_id) != str(learned_v):
                out["version_matches"] = False
            else:
                out["version_matches"] = True
        else:
            out["version_matches"] = True
        return out

    def retry_brain_sync(self, project_id: str, source_id: str) -> dict[str, Any]:
        self.get_project(project_id)
        source = self.store.get_source(source_id)
        if source is None or source.project_id != project_id:
            raise ResearchError("SOURCE_NOT_FOUND", "Unknown source", http_status=404)
        # Production: enqueue only. Inline Knowledge sync is TEST-ONLY under allow gate.
        if self.source_ingestion is not None:
            from Data.modules.source_ingestion.execution_gate import allow_inprocess_execution

            if allow_inprocess_execution(self.source_ingestion.settings):
                synced = self.brain.retry_brain_sync(source_id)
                return {"source": synced.public_dict()}
            return self.source_ingestion.enqueue_brain_retry(source_id)
        if self.job_runtime is not None:
            return self._enqueue_source_brain_retry(project_id, source_id)
        raise ResearchError(
            "SOURCE_INGESTION_UNAVAILABLE",
            "Brain retry requires source_ingestion worker / JobRuntime",
            http_status=503,
            details={"source_id": source_id},
        )

    def list_workers(self, project_id: str):
        self.get_project(project_id)
        return self.store.list_workers(project_id)

    def list_events(self, project_id: str, *, limit: int = 200):
        self.get_project(project_id)
        return self.store.list_events(project_id, limit=limit)

    def list_sources(self, project_id: str, *, limit: int = 200):
        self.get_project(project_id)
        return self.store.list_sources(project_id, limit=limit)

    def list_evidence(self, project_id: str, *, limit: int = 500):
        self.get_project(project_id)
        return self.store.list_evidence(project_id, limit=limit)

    def list_claims(self, project_id: str, *, limit: int = 500):
        self.get_project(project_id)
        return self.store.list_claims(project_id, limit=limit)

    def list_conflicts(self, project_id: str, *, limit: int = 200):
        self.get_project(project_id)
        return self.store.list_conflicts(project_id, limit=limit)

    def coverage(self, project_id: str):
        project = self.get_project(project_id)
        if project.coverage:
            return project.coverage
        from .coverage import build_coverage

        reason = project.web_unavailable_reason
        web_status = reason or ("ok" if project.allow_web else "not_requested")
        return build_coverage(self.store, project, web_status=web_status)

    def get_report(self, project_id: str):
        self.get_project(project_id)
        report = self.store.get_latest_report(project_id)
        if report is None:
            raise ResearchError("REPORT_NOT_FOUND", "No report generated yet", http_status=404)
        return report

    def regenerate_report(self, project_id: str):
        project = self.get_project(project_id)
        if self._runners_externalized():
            self._require_external_runtime(capability="research.report.generate")
            job = self.job_runtime.enqueue(
                capability_id="research.report.generate",
                arguments={"action": "regenerate_report", "project_id": project_id},
                requested_by="api.research.regenerate_report",
                domain="research",
                domain_entity_type="project",
                domain_entity_id=project_id,
                worker_pool="research",
                resource_class="CPU_HEAVY",
                latency_class="interactive",
                idempotency_key=f"research:report:{project_id}:{project.updated_at or project.created_at}",
                metadata={
                    "human_title": project.topic or project.title or project_id,
                    "topic": project.topic or project.title,
                },
            )
            return {
                "queued": True,
                "job": job.public_dict(),
                "job_id": job.job_id,
                "project_id": project_id,
                "status": "QUEUED",
                "truth": {"executed_via": "research_worker"},
            }
        if not allow_inprocess_research_execution():
            refuse_inline_research(
                reason="inprocess_not_allowed",
                capability="research.report.generate",
            )
        return self._regenerate_report_inline(project_id)

    def _regenerate_report_inline(self, project_id: str):
        project = self.get_project(project_id)
        report = self.reports.generate(project)
        self.store.add_event(
            project_id,
            "report_generated",
            f"Report version {report.version}",
            {"report_id": report.report_id},
        )
        try:
            self.brain.sync_report(project, report)
        except Exception as exc:  # noqa: BLE001
            self.store.add_event(project_id, "brain_sync_failed", str(exc), {"stage": "report"})
        return report

    def export(self, project_id: str, *, fmt: str = "markdown") -> dict:
        self.get_project(project_id)
        try:
            return self.reports.export_bundle(project_id, fmt=fmt)
        except ValueError as exc:
            raise ResearchError("EXPORT_UNSUPPORTED", str(exc), http_status=422) from exc

    def resolve_citation(self, project_id: str, citation_key: str):
        self.get_project(project_id)
        return self.ledger.resolve_citation(project_id, citation_key)

    def claim_evidence_graph(self, project_id: str) -> dict[str, Any]:
        self.get_project(project_id)
        from .graph import ClaimEvidenceGraphBuilder

        return ClaimEvidenceGraphBuilder(self.store).build(project_id).public_dict()

    def verify_claims_independently(self, project_id: str) -> dict[str, Any]:
        """Independent verifier path — does not reuse authoring-model judgments.

        Deterministic entailment + source-independence only. Cross-model
        verification remains UNAVAILABLE unless a separate verifier is wired.
        """
        self.get_project(project_id)
        from .independent_verifier import IndependentClaimVerifier

        report = IndependentClaimVerifier(self.store).verify_project(project_id)
        self.store.add_event(
            project_id,
            "independent_verification",
            f"Independent verifier report {report.report_id}",
            {
                "report_id": report.report_id,
                "counts": report.public_dict()["counts"],
                "cross_model_status": report.cross_model_status,
            },
        )
        return report.public_dict()

    def bounded_web_search(
        self,
        queries: list[str],
        *,
        limit: int = 5,
        max_workers: int | None = None,
    ) -> dict[str, Any]:
        """Search multiple queries with a hard concurrency ceiling (Wave 10–11)."""
        from .concurrency import (
            DEFAULT_SEARCH_CONCURRENCY,
            BoundedConcurrencyGate,
            clamp_concurrency,
            partition_successes,
        )

        gate = BoundedConcurrencyGate(
            max_workers=clamp_concurrency(
                max_workers,
                default=DEFAULT_SEARCH_CONCURRENCY,
                ceiling=8,
            ),
            name="research.search",
        )
        provider = self.web

        def _one(q: str) -> dict[str, Any]:
            hits = provider.search(str(q), limit=limit)
            return {
                "query": q,
                "results": [h.public_dict() if hasattr(h, "public_dict") else h for h in hits],
            }

        raw = gate.run_bounded(list(queries or []), _one)
        ok, err = partition_successes(raw)
        return {
            "results": ok,
            "errors": [{"error": str(e)[:300]} for e in err],
            "concurrency": gate.public_dict(),
            "truth": {
                "bounded_concurrency": True,
                "search_hits_are_discovery_only": True,
            },
        }

    def bounded_web_fetch(
        self,
        urls: list[str],
        *,
        max_workers: int | None = None,
        timeout_seconds: float = 20.0,
    ) -> dict[str, Any]:
        """Fetch multiple URLs with a hard concurrency ceiling (Wave 10–11)."""
        from .concurrency import (
            DEFAULT_FETCH_CONCURRENCY,
            BoundedConcurrencyGate,
            clamp_concurrency,
            partition_successes,
        )

        gate = BoundedConcurrencyGate(
            max_workers=clamp_concurrency(
                max_workers,
                default=DEFAULT_FETCH_CONCURRENCY,
                ceiling=8,
            ),
            name="research.fetch",
        )
        provider = self.web

        def _one(url: str) -> dict[str, Any]:
            page = provider.fetch_page(str(url), timeout_seconds=timeout_seconds)
            return page.public_dict() if hasattr(page, "public_dict") else dict(page)

        raw = gate.run_bounded(list(urls or []), _one)
        ok, err = partition_successes(raw)
        return {
            "pages": ok,
            "errors": [{"error": str(e)[:300]} for e in err],
            "concurrency": gate.public_dict(),
            "truth": {
                "bounded_concurrency": True,
                "fetched_content_is_source_of_truth": True,
            },
        }

    def list_gaps(self, project_id: str) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        from .gaps import GapAnalyzer

        return [g.public_dict() for g in GapAnalyzer().analyze(self.store, project)]

    def source_assessments(self, project_id: str) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        from .source_quality import assess_source

        topic_tokens = [t.lower() for t in project.topic.split() if len(t) > 2]
        out: list[dict[str, Any]] = []
        for src in self.store.list_sources(project_id):
            existing = (src.metadata or {}).get("source_assessment")
            if isinstance(existing, dict):
                out.append(existing)
            else:
                out.append(assess_source(src, topic_tokens=topic_tokens).public_dict())
        return out

    def citation_audit(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        from .citation_audit import audit_report

        report = self.store.get_latest_report(project_id)
        body = getattr(report, "body_markdown", "") if report is not None else ""
        return audit_report(self.store, project, body or "").public_dict()

    def quality_scorecard(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        from .quality_scorecard import build_quality_scorecard

        report = self.store.get_latest_report(project_id)
        body = getattr(report, "body_markdown", None) if report is not None else None
        return build_quality_scorecard(self.store, project, report_markdown=body).public_dict()

    def plan_history(self, project_id: str) -> list[dict[str, Any]]:
        """Plan evolution events for operator inspection."""
        self.get_project(project_id)
        events = self.store.list_events(project_id, limit=500)
        history: list[dict[str, Any]] = []
        for ev in events:
            if ev.event_type in {"plan_generated", "plan_adapted", "deepen_requested"}:
                history.append(ev.public_dict())
        return history

    def export_reproducibility_bundle(
        self,
        project_id: str,
        *,
        model_revision: str | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        from .graph import ReproducibilityBundleExporter

        exporter = ReproducibilityBundleExporter(self.store, self.exports_root)
        bundle = exporter.export(project, model_revision=model_revision)
        self.store.add_event(
            project_id,
            "reproducibility_bundle",
            f"Exported {bundle.bundle_id}",
            {"bundle_id": bundle.bundle_id, "path": bundle.path},
        )
        return bundle.public_dict()
