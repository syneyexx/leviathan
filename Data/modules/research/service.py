"""ResearchService — public façade for API and runners."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.common.corpus import CorpusLayout, build_corpus_layout
from Data.modules.knowledge import KnowledgeStore

from .budgets import budget_for_depth, list_presets, merge_budget_overrides
from .evidence import EvidenceLedger
from .local_retrieval import LocalResearchRetriever, build_default_local_retriever
from .planner import apply_plan_edits, build_plan
from .reports import ReportBuilder
from .runner import ResearchRunner
from .store import ResearchStore
from .types import (
    ResearchDepth,
    ResearchError,
    ResearchProject,
    ResearchStatus,
    TERMINAL_STATUSES,
)
from .web import UnconfiguredWebProvider, WebResearchProvider, build_web_provider, web_unavailable_reason


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
        corpus: CorpusLayout | None = None,
    ) -> None:
        self.store = store
        self.knowledge = knowledge
        self.allow_outbound = bool(allow_outbound)
        if corpus is not None:
            self.snapshots_root = corpus.research_snapshots
            self.reports_root = corpus.research_reports
            self.exports_root = corpus.research_exports
        else:
            self.snapshots_root = Path(snapshots_root or store.db_path.parent / "research_snapshots")
            self.reports_root = Path(reports_root or store.db_path.parent / "research_reports")
            self.exports_root = self.reports_root.parent / "research_exports"
        self.local = local or build_default_local_retriever(knowledge)
        self.web = web or (
            build_web_provider(allow_outbound=allow_outbound)
            if allow_outbound
            else UnconfiguredWebProvider()
        )
        self.runner = ResearchRunner(
            store,
            local=self.local,
            web=self.web,
            allow_outbound=self.allow_outbound,
            snapshots_root=self.snapshots_root,
            reports_root=self.reports_root,
        )
        self.ledger = EvidenceLedger(store)
        self.reports = ReportBuilder(store, reports_root=self.reports_root)

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
    ) -> "ResearchService":
        corpus = build_corpus_layout(settings)
        store = ResearchStore(db_path)
        store.initialize()
        allow_outbound = bool(settings.network.allow_outbound)
        endpoint = search_endpoint
        api_key = search_api_key
        if hasattr(settings, "research_integration"):
            endpoint = endpoint or settings.research_integration.web_search_endpoint
            api_key = api_key if api_key is not None else settings.research_integration.web_search_api_key
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
            if hasattr(self.runner, "web"):
                self.runner.web = self.web

    def recover(self) -> list[str]:
        return self.runner.recover_interrupted()

    def list_budget_presets(self) -> dict[str, dict]:
        return list_presets()

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
    ) -> ResearchProject:
        topic_clean = (topic or "").strip()
        if not topic_clean:
            raise ResearchError("VALIDATION_ERROR", "topic is required", http_status=422)
        depth_enum = ResearchDepth(depth.value if isinstance(depth, ResearchDepth) else str(depth).lower())
        budget = merge_budget_overrides(budget_for_depth(depth_enum), budget_overrides)
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
        )
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
        if "depth" in updates and updates["depth"] is not None:
            project.depth = ResearchDepth(str(updates["depth"]).lower())
            project.budget = budget_for_depth(project.depth)
            project.total_rounds = project.budget.rounds
        if "budget" in updates and isinstance(updates["budget"], dict):
            project.budget = merge_budget_overrides(project.budget, updates["budget"])
            project.total_rounds = project.budget.rounds
        if "model_profile" in updates and updates["model_profile"] is not None:
            project.model_profile = dict(updates["model_profile"])
        # Editing invalidates prior plan visibility — regenerate on next plan call unless plan edits provided.
        if project.status == ResearchStatus.COMPLETED:
            # Keep completed; edits prepare for deepen/resume.
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
        project.status = ResearchStatus.PLANNED
        self.store.save_project(project)
        return self.get_project(project_id)

    def run(self, project_id: str) -> ResearchProject:
        self.runner.run(project_id)
        return self.get_project(project_id)

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
        # Cooperative cancel for in-process runs; if not running, finalize now.
        latest = self.get_project(project_id)
        if latest.status in {
            ResearchStatus.DRAFT,
            ResearchStatus.PLANNED,
            ResearchStatus.QUEUED,
            ResearchStatus.INTERRUPTED,
            ResearchStatus.CANCELLING,
        } and not (
            latest.worker_pid and latest.status == ResearchStatus.CANCELLING
        ):
            # If no active worker loop will observe the flag, mark cancelled immediately
            # unless currently researching in this process (runner checks flag).
            if latest.status != ResearchStatus.CANCELLING or latest.worker_pid is None:
                latest.status = ResearchStatus.CANCELLED
                latest.cancel_requested = False
                latest.worker_pid = None
                from .store import utc_now

                latest.finished_at = utc_now()
                latest.error = latest.error or "Cancelled by request"
                self.store.save_project(latest)
        return self.get_project(project_id)

    def resume(self, project_id: str) -> ResearchProject:
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
            raise ResearchError(
                "RESEARCH_NOT_RESUMABLE",
                f"Cannot resume from status {project.status.value}",
                http_status=409,
            )
        self.store.add_event(project_id, "round_started", "Resume requested")
        self.runner.run(project_id)
        return self.get_project(project_id)

    def deepen(self, project_id: str, *, extra_rounds: int = 1) -> ResearchProject:
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
        self.runner.run(project_id, deepen=True, extra_rounds=max(1, int(extra_rounds)))
        return self.get_project(project_id)

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
