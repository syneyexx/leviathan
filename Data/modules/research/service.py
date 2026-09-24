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
from .local_retrieval import LocalResearchRetriever, build_default_local_retriever
from .planner import apply_plan_edits, build_plan
from .reports import ReportBuilder
from .runner import ResearchRunner
from .ssrf import validate_url_for_fetch
from .store import ResearchStore, utc_now
from .types import (
    ACTIVE_STATUSES,
    AnalysisMode,
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
    ) -> None:
        self.store = store
        self.knowledge = knowledge
        self.allow_outbound = bool(allow_outbound)
        self.assimilation_service = assimilation_service
        self.atlas_store = atlas_store
        self._emit = observability_emit
        self.auto_promote_verified_knowledge = bool(auto_promote_verified_knowledge)
        self.model_caller = model_caller
        if corpus is not None:
            self.snapshots_root = corpus.research_snapshots
            self.reports_root = corpus.research_reports
            self.exports_root = corpus.research_exports
            self.sources_root = corpus.research_sources
        else:
            self.snapshots_root = Path(snapshots_root or store.db_path.parent / "research_snapshots")
            self.reports_root = Path(reports_root or store.db_path.parent / "research_reports")
            self.exports_root = self.reports_root.parent / "research_exports"
            self.sources_root = Path(sources_root or store.db_path.parent / "research_sources")
        self.local = local or build_default_local_retriever(knowledge)
        self.web = web or (
            build_web_provider(allow_outbound=allow_outbound)
            if allow_outbound
            else UnconfiguredWebProvider()
        )
        self.brain = ResearchBrainSync(store, knowledge)
        self.uploads = UploadIngestor(
            store,
            sources_root=self.sources_root,
            snapshots_root=self.snapshots_root,
        )
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
        self.reports = ReportBuilder(store, reports_root=self.reports_root)
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
    ) -> "ResearchService":
        corpus = build_corpus_layout(settings)
        store = ResearchStore(db_path)
        store.initialize()
        allow_outbound = bool(settings.network.allow_outbound)
        endpoint = search_endpoint
        api_key = search_api_key
        auto_promote = True
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
        provider = web or build_web_provider(
            allow_outbound=allow_outbound,
            search_endpoint=endpoint,
            api_key=api_key,
        )
        return cls(
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
        )

    def reconfigure_web(
        self,
        *,
        allow_outbound: bool,
        search_endpoint: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Hot-apply outbound / search provider settings from the Settings Control Plane."""
        from Data.modules.research.web import build_web_provider

        self.allow_outbound = bool(allow_outbound)
        self.web = build_web_provider(
            allow_outbound=self.allow_outbound,
            search_endpoint=search_endpoint,
            api_key=api_key,
        )
        if hasattr(self, "runner") and self.runner is not None:
            self.runner.allow_outbound = self.allow_outbound
            self.runner.web = self.web
            if hasattr(self.runner, "coordinator"):
                self.runner.coordinator.allow_outbound = self.allow_outbound
                self.runner.coordinator.web = self.web

    def set_model_caller(self, caller: Callable[..., dict[str, Any]] | None) -> None:
        self.model_caller = caller

    def start_background(self, *, poll_seconds: float = 0.5) -> None:
        """Background dispatcher for queued research runs."""
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

    def stop_background(self) -> None:
        self._dispatcher_stop.set()

    def _dispatch_queued(self) -> None:
        for project in self.store.list_projects(limit=100):
            if project.status != ResearchStatus.QUEUED:
                continue
            with self._bg_lock:
                t = self._bg_threads.get(project.project_id)
                if t and t.is_alive():
                    continue
            self._spawn_run(project.project_id, deepen=False, extra_rounds=0, resume=False)

    def recover(self) -> list[str]:
        return self.runner.recover_interrupted()

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
        project.total_worker_rounds = budget.research_workers * budget.rounds
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

    def list_projects(self, *, limit: int = 100) -> list[ResearchProject]:
        projects = self.store.list_projects(limit=limit)
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
            project.total_rounds = project.budget.rounds
            project.total_worker_rounds = project.budget.research_workers * project.budget.rounds
        if "budget" in updates and isinstance(updates["budget"], dict):
            if project.execution_mode == ResearchExecutionMode.NORMAL:
                project.budget = resolve_execution_budget(
                    execution_mode=ResearchExecutionMode.NORMAL,
                    base=project.budget,
                )
            else:
                project.budget = merge_budget_overrides(project.budget, updates["budget"])
            project.total_rounds = project.budget.rounds
            project.total_worker_rounds = project.budget.research_workers * project.budget.rounds
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
        project.total_worker_rounds = plan.budget.research_workers * plan.rounds
        project.status = ResearchStatus.PLANNED
        project.phase = ResearchPhase.PLANNING
        self.store.save_project(project)
        return self.get_project(project_id)

    def run(self, project_id: str, *, background: bool = False) -> ResearchProject:
        project = self.get_project(project_id)
        if project.status in ACTIVE_STATUSES:
            # Idempotent: return current state rather than starting a competing run.
            return project
        if background:
            return self.enqueue_run(project_id)
        self.runner.run(project_id)
        project = self.get_project(project_id)
        self._maybe_promote_knowledge(project)
        return self.get_project(project_id)

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
        project.status = ResearchStatus.QUEUED
        project.phase = ResearchPhase.PLANNING
        project.error = None
        project.cancel_requested = False
        project.finished_at = None
        project.progress_pct = max(1.0, float(project.progress_pct or 0))
        self.store.save_project(project)
        self.store.add_event(project_id, "queued", "Research queued for execution")
        self._spawn_run(project_id, deepen=deepen, extra_rounds=extra_rounds, resume=resume)
        return self.get_project(project_id)

    def _spawn_run(
        self,
        project_id: str,
        *,
        deepen: bool,
        extra_rounds: int,
        resume: bool,
    ) -> None:
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
        latest = self.get_project(project_id)
        with self._bg_lock:
            alive = bool(
                self._bg_threads.get(project_id) and self._bg_threads[project_id].is_alive()
            )
        if latest.status in {
            ResearchStatus.DRAFT,
            ResearchStatus.PLANNED,
            ResearchStatus.QUEUED,
            ResearchStatus.INTERRUPTED,
            ResearchStatus.CANCELLING,
        } and not alive:
            if latest.worker_pid is None:
                latest.status = ResearchStatus.CANCELLED
                latest.phase = ResearchPhase.CANCELLED
                latest.cancel_requested = False
                latest.worker_pid = None
                latest.finished_at = utc_now()
                latest.error = latest.error or "Cancelled by request"
                latest.progress_pct = min(95.0, float(latest.progress_pct or 0))
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
        self.runner.run(
            project_id, deepen=True, extra_rounds=max(1, int(extra_rounds))
        )
        project = self.get_project(project_id)
        self._maybe_promote_knowledge(project)
        return self.get_project(project_id)

    def _maybe_promote_knowledge(self, project: ResearchProject) -> None:
        """Promote verified claims after COMPLETED. Never fails research completion."""
        if project.status != ResearchStatus.COMPLETED:
            return
        if not bool(getattr(self, "auto_promote_verified_knowledge", True)):
            return
        if self.assimilation_service is None or self.knowledge is None:
            return
        if not hasattr(self.assimilation_service, "assimilate_research_project"):
            return
        claims = self.store.list_claims(project.project_id)
        evidence = self.store.list_evidence(project.project_id)
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
            project.model_profile = {
                **dict(project.model_profile or {}),
                "knowledge_promotion": receipt_dict,
            }
            self.store.save_project(project)
            self.store.add_event(
                project.project_id,
                "knowledge_promoted",
                "Research claims assimilated into knowledge",
                {
                    "receipt_id": receipt_dict.get("receipt_id"),
                    "ok": receipt_dict.get("ok"),
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
                        "success_count": receipt_dict.get("success_count"),
                        "document_ids": list(receipt_dict.get("document_ids") or [])[:20],
                    },
                    success=bool(receipt_dict.get("ok")),
                )
        except Exception as exc:  # noqa: BLE001 — promotion must not fail research
            error_payload = {
                "error": f"{type(exc).__name__}: {exc}",
                "project_id": project.project_id,
            }
            try:
                project.model_profile = {
                    **dict(project.model_profile or {}),
                    "knowledge_promotion_error": error_payload,
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
        source, text = self.uploads.from_upload_stream(
            project.project_id,
            filename=filename,
            stream=stream,
            content_type=content_type,
        )
        self.store.add_event(
            project_id,
            "source_parsed",
            source.title or filename,
            {
                "source_id": source.source_id,
                "parse_status": source.parse_status.value,
                "mime_type": source.mime_type,
            },
        )
        synced = self.brain.sync_uploaded_source(source, text)
        self.store.add_event(
            project_id,
            "brain_sync" if synced.brain_status.value == "synced" else "brain_sync_failed",
            synced.brain_error or "Upload synced to Brain",
            {
                "source_id": synced.source_id,
                "brain_status": synced.brain_status.value,
                "brain_document_id": synced.brain_document_id,
            },
        )
        return {
            "source": synced.public_dict(),
            "extracted_chars": len(text),
            "page_count": (synced.provenance or {}).get("page_count"),
        }

    def add_url_source(self, project_id: str, url: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        cleaned = (url or "").strip()
        if not cleaned:
            raise ResearchError("VALIDATION_ERROR", "url is required", http_status=422)
        decision = validate_url_for_fetch(cleaned)
        if not decision.allowed:
            raise ResearchError(
                "URL_BLOCKED",
                decision.reason or "URL blocked by SSRF policy",
                http_status=400,
                details={"url": cleaned, "reason": decision.reason},
            )
        reason = web_unavailable_reason(
            allow_web=True,
            allow_outbound=self.allow_outbound,
            provider=self.web,
        )
        if reason:
            # Still record seed so research can attempt later if web becomes available.
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
                details={"url": cleaned},
            ) from exc
        from .sources import SourceIngestor

        ingestor = SourceIngestor(self.store, self.snapshots_root)
        source, text = ingestor.from_web_page(project_id, page)
        synced = self.brain.sync_web_page(source, text)
        self.store.add_event(
            project_id,
            "source_fetched",
            synced.title or cleaned,
            {"source_id": synced.source_id, "url": cleaned},
        )
        return {"source": synced.public_dict()}

    def connect_dataset(
        self,
        project_id: str,
        *,
        dataset_id: str,
        version_id: str | None = None,
        indexed: bool | None = None,
        label: str | None = None,
    ) -> ResearchProject:
        project = self.get_project(project_id)
        if not dataset_id:
            raise ResearchError("VALIDATION_ERROR", "dataset_id is required", http_status=422)
        entry = {
            "dataset_id": dataset_id,
            "version_id": version_id,
            "indexed": bool(indexed) if indexed is not None else False,
            "label": label or dataset_id,
        }
        if indexed is False:
            raise ResearchError(
                "DATASET_NOT_INDEXED",
                "Dataset is not indexed into Brain yet",
                http_status=409,
                details=entry,
            )
        # Scope local retrieval to dataset knowledge source if provided as label/source.
        scope = f"dataset:{dataset_id}"
        if version_id:
            scope = f"dataset:{dataset_id}:{version_id}"
        datasets = [d for d in project.connected_datasets if d.get("dataset_id") != dataset_id]
        datasets.append(entry)
        project.connected_datasets = datasets
        scopes = list(project.local_scopes)
        if scope not in scopes:
            scopes.append(scope)
        # Also allow generic dataset source tag used by Knowledge ingest pipelines.
        for candidate in (f"dataset:{dataset_id}", "dataset"):
            if candidate not in scopes:
                scopes.append(candidate)
        project.local_scopes = scopes
        self.store.save_project(project)
        self.store.add_event(
            project_id,
            "dataset_connected",
            entry["label"],
            entry,
        )
        return self.get_project(project_id)

    def retry_brain_sync(self, project_id: str, source_id: str) -> dict[str, Any]:
        self.get_project(project_id)
        source = self.store.get_source(source_id)
        if source is None or source.project_id != project_id:
            raise ResearchError("SOURCE_NOT_FOUND", "Unknown source", http_status=404)
        synced = self.brain.retry_brain_sync(source_id)
        return {"source": synced.public_dict()}

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
