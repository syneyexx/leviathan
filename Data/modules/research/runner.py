"""Research execution runner — local/web rounds with cancel and deepen."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from Data.modules.common.process import pid_is_alive

from .claims import ClaimAnalyzer
from .conflicts import ConflictDetector
from .coverage import build_coverage
from .evidence import EvidenceLedger
from .local_retrieval import LocalResearchRetriever
from .planner import build_plan
from .reports import ReportBuilder
from .sources import SourceIngestor
from .store import ResearchStore, utc_now
from .types import (
    ACTIVE_STATUSES,
    ResearchError,
    ResearchProject,
    ResearchStatus,
    TERMINAL_STATUSES,
)
from .web import WebResearchProvider, web_unavailable_reason


class ResearchRunner:
    def __init__(
        self,
        store: ResearchStore,
        *,
        local: LocalResearchRetriever,
        web: WebResearchProvider,
        allow_outbound: bool,
        snapshots_root: Path,
        reports_root: Path | None = None,
    ) -> None:
        self.store = store
        self.local = local
        self.web = web
        self.allow_outbound = bool(allow_outbound)
        self.sources = SourceIngestor(store, snapshots_root)
        self.evidence = EvidenceLedger(store)
        self.claims = ClaimAnalyzer(store)
        self.conflicts = ConflictDetector(store)
        self.reports = ReportBuilder(store, reports_root=reports_root)

    def recover_interrupted(self) -> list[str]:
        """Mark researching projects with dead workers as interrupted."""
        recovered: list[str] = []
        for project in self.store.list_projects(limit=500):
            if project.status not in ACTIVE_STATUSES:
                continue
            pid = project.worker_pid
            if pid is None:
                continue
            if pid_is_alive(pid):
                continue
            project.status = ResearchStatus.INTERRUPTED
            project.error = f"Worker pid {pid} no longer alive"
            project.worker_pid = None
            project.finished_at = utc_now()
            self.store.save_project(project)
            self.store.add_event(
                project.project_id,
                "interrupted",
                project.error,
                {"worker_pid": pid},
            )
            recovered.append(project.project_id)
        return recovered

    def run(
        self,
        project_id: str,
        *,
        extra_rounds: int = 0,
        deepen: bool = False,
    ) -> ResearchProject:
        project = self.store.get_project(project_id)
        if project is None:
            raise ResearchError("RESEARCH_NOT_FOUND", f"Unknown project: {project_id}", http_status=404)

        if project.status in {ResearchStatus.RESEARCHING, ResearchStatus.SYNTHESIZING}:
            if project.worker_pid and pid_is_alive(project.worker_pid):
                raise ResearchError(
                    "RESEARCH_BUSY",
                    "Project is already researching",
                    http_status=409,
                )

        if project.plan is None:
            project.plan = build_plan(project)
            project.status = ResearchStatus.PLANNED
            project.total_rounds = project.plan.rounds
            self.store.save_project(project)
            self.store.add_event(project_id, "plan_generated", "Plan created before run")

        if deepen:
            project.total_rounds = max(project.total_rounds, project.current_round) + max(1, extra_rounds or 1)
            self.store.add_event(
                project_id,
                "deepen_requested",
                f"Additional round(s); total_rounds={project.total_rounds}",
            )
        elif extra_rounds > 0:
            project.total_rounds = max(project.total_rounds, project.current_round + extra_rounds)

        project.cancel_requested = False
        project.error = None
        project.status = ResearchStatus.RESEARCHING
        project.started_at = project.started_at or utc_now()
        project.finished_at = None
        project.worker_pid = os.getpid()
        web_reason = web_unavailable_reason(
            allow_web=project.allow_web,
            allow_outbound=self.allow_outbound,
            provider=self.web,
        )
        project.web_unavailable_reason = web_reason
        self.store.save_project(project)
        self.store.add_event(project_id, "round_started", f"Starting from round {project.current_round}")

        try:
            while project.current_round < project.total_rounds:
                if self._cancelled(project_id):
                    return self._finalize_cancelled(project_id)

                project.current_round += 1
                self.store.save_project(project)
                self.store.add_event(
                    project_id,
                    "round_started",
                    f"Round {project.current_round}/{project.total_rounds}",
                    {"round": project.current_round},
                )

                self._run_local_round(project)
                if self._cancelled(project_id):
                    return self._finalize_cancelled(project_id)

                self._run_web_round(project)
                if self._cancelled(project_id):
                    return self._finalize_cancelled(project_id)

                claims = self.claims.analyze_project(project_id)
                conflicts = self.conflicts.detect(project_id, claims)
                for conflict in conflicts:
                    self.store.add_event(
                        project_id,
                        "contradiction_detected",
                        conflict.summary,
                        {"conflict_id": conflict.conflict_id},
                    )

                # Next-round query adaptation: unresolved conflict questions.
                if project.current_round < project.total_rounds and project.plan:
                    for conflict in conflicts:
                        for q in conflict.unresolved_questions:
                            if q not in project.plan.retrieval_queries:
                                project.plan.retrieval_queries.append(q)
                    project.plan.retrieval_queries = project.plan.retrieval_queries[
                        : project.budget.search_queries + 3
                    ]
                    self.store.save_project(project)

                self.store.add_event(
                    project_id,
                    "round_completed",
                    f"Round {project.current_round} complete",
                    {"round": project.current_round},
                )
                project = self.store.get_project(project_id) or project

            if self._cancelled(project_id):
                return self._finalize_cancelled(project_id)

            project = self.store.get_project(project_id) or project
            project.status = ResearchStatus.SYNTHESIZING
            self.store.save_project(project)
            self.store.add_event(project_id, "synthesis_started", "Building coverage and report")

            web_status = web_reason or ("ok" if project.allow_web else "not_requested")
            if not project.allow_web:
                web_status = "not_requested"
            elif web_reason:
                web_status = web_reason
            else:
                web_status = "ok"

            project.coverage = build_coverage(
                self.store,
                project,
                web_status=web_status,
                rounds_completed=project.current_round,
            )
            project.web_unavailable_reason = web_reason
            self.store.save_project(project)

            report = self.reports.generate(project)
            self.store.add_event(
                project_id,
                "report_generated",
                f"Report version {report.version}",
                {"report_id": report.report_id, "version": report.version},
            )

            project = self.store.get_project(project_id) or project
            project.status = ResearchStatus.COMPLETED
            project.worker_pid = None
            project.finished_at = utc_now()
            project.cancel_requested = False
            self.store.save_project(project)
            self.store.add_event(project_id, "completed", "Research completed")
            return self.store.get_project(project_id) or project

        except ResearchError:
            raise
        except Exception as exc:  # noqa: BLE001 — persist failure honestly
            project = self.store.get_project(project_id) or project
            project.status = ResearchStatus.FAILED
            project.error = str(exc)
            project.worker_pid = None
            project.finished_at = utc_now()
            self.store.save_project(project)
            self.store.add_event(project_id, "failed", str(exc))
            raise ResearchError(
                "RESEARCH_FAILED",
                str(exc),
                http_status=500,
                details={"project_id": project_id},
            ) from exc

    def _cancelled(self, project_id: str) -> bool:
        return self.store.is_cancel_requested(project_id)

    def _finalize_cancelled(self, project_id: str) -> ResearchProject:
        project = self.store.get_project(project_id)
        assert project is not None
        project.status = ResearchStatus.CANCELLED
        project.worker_pid = None
        project.finished_at = utc_now()
        project.cancel_requested = False
        project.error = project.error or "Cancelled by request"
        self.store.save_project(project)
        self.store.add_event(project_id, "cancelled", "Research cancelled")
        return project

    def _run_local_round(self, project: ResearchProject) -> None:
        if not self.local.available:
            self.store.add_event(
                project.project_id,
                "query_completed",
                "Local retriever unavailable",
                {"local_available": False},
            )
            return
        plan = project.plan
        queries = list(plan.retrieval_queries) if plan else [project.topic]
        # Prefer unresolved / later queries on deeper rounds.
        if project.current_round > 1 and len(queries) > 1:
            queries = queries[project.current_round - 1 :] + queries[: project.current_round - 1]

        budget = project.budget
        remaining = budget.max_sources - len(self.store.list_sources(project.project_id))
        if remaining <= 0:
            return

        for query in queries[: budget.search_queries]:
            if self._cancelled(project.project_id):
                return
            self.store.add_event(
                project.project_id,
                "query_started",
                f"Local retrieval: {query}",
                {"channel": "local", "query": query},
            )
            hits = self.local.search(
                query,
                limit=min(budget.max_local_hits, max(1, remaining)),
                local_scopes=project.local_scopes or None,
            )
            if self._cancelled(project.project_id):
                return
            added = 0
            for hit in hits:
                if remaining <= 0 or self._cancelled(project.project_id):
                    break
                source, content = self.sources.from_local_hit(project.project_id, hit)
                self.store.add_event(
                    project.project_id,
                    "source_discovered",
                    source.title or source.source_id,
                    {"source_id": source.source_id, "channel": "local"},
                )
                spans = _select_spans(content, query, limit=budget.max_evidence_per_source)
                for span in spans:
                    self.evidence.add_span(
                        project_id=project.project_id,
                        source_id=source.source_id,
                        span_text=span,
                        chunk_id=hit.chunk_id,
                        location={
                            "document_id": hit.document_id,
                            "chunk_id": hit.chunk_id,
                            "chunk_index": hit.chunk_index,
                        },
                        retrieval_method="local_knowledge",
                        metadata={"score": hit.score, "query": query},
                    )
                    self.store.add_event(
                        project.project_id,
                        "evidence_added",
                        span[:120],
                        {"source_id": source.source_id},
                    )
                added += 1
                remaining -= 1
            self.store.add_event(
                project.project_id,
                "query_completed",
                f"Local hits used: {added}",
                {"channel": "local", "query": query, "hits": len(hits)},
            )

        # Seed sources as explicit local evidence inputs.
        for seed in project.seed_sources:
            if remaining <= 0:
                break
            if seed.startswith("text:"):
                body = seed[5:]
                title = "Seed text"
            else:
                # Treat as a label-only seed without inventing content.
                continue
            source, content = self.sources.from_seed_text(
                project.project_id, title=title, text=body
            )
            for span in _select_spans(content, project.topic, limit=2):
                self.evidence.add_span(
                    project_id=project.project_id,
                    source_id=source.source_id,
                    span_text=span,
                    retrieval_method="seed",
                )
            remaining -= 1

    def _run_web_round(self, project: ResearchProject) -> None:
        if not project.allow_web:
            return
        reason = web_unavailable_reason(
            allow_web=True,
            allow_outbound=self.allow_outbound,
            provider=self.web,
        )
        if reason:
            self.store.add_event(
                project.project_id,
                "query_completed",
                f"Web research unavailable: {reason}",
                {"channel": "web", "status": "unavailable", "reason": reason},
            )
            project.web_unavailable_reason = reason
            self.store.save_project(project)
            return

        plan = project.plan
        queries = list(plan.retrieval_queries) if plan else [project.topic]
        budget = project.budget
        remaining = budget.max_sources - len(self.store.list_sources(project.project_id))
        if remaining <= 0:
            return

        search_ready = getattr(self.web, "search_configured", lambda: False)()
        if not search_ready:
            # Honest: fetch provider may be outbound-ready but search endpoint missing.
            reason = "web_search_endpoint_unconfigured"
            self.store.add_event(
                project.project_id,
                "query_completed",
                f"Web research unavailable: {reason}",
                {"channel": "web", "status": "unavailable", "reason": reason},
            )
            project.web_unavailable_reason = reason
            self.store.save_project(project)
            # Still attempt seed URL fetches if any look like URLs.
            self._fetch_seed_urls(project, remaining)
            return

        for query in queries[: budget.search_queries]:
            if self._cancelled(project.project_id):
                return
            self.store.add_event(
                project.project_id,
                "query_started",
                f"Web search: {query}",
                {"channel": "web", "query": query},
            )
            try:
                results = self.web.search(query, limit=budget.urls_per_query)
            except Exception as exc:  # noqa: BLE001
                self.store.add_event(
                    project.project_id,
                    "query_completed",
                    f"Web search failed: {exc}",
                    {"channel": "web", "error": str(exc)},
                )
                continue
            for result in results:
                if remaining <= 0:
                    break
                self.sources.from_web_search(project.project_id, result)
                try:
                    page = self.web.fetch_page(
                        result.url,
                        respect_robots_txt=project.respect_robots_txt,
                    )
                except Exception as exc:  # noqa: BLE001
                    self.store.add_event(
                        project.project_id,
                        "source_parse_failed",
                        str(exc),
                        {"url": result.url},
                    )
                    continue
                source, content = self.sources.from_web_page(project.project_id, page)
                self.store.add_event(
                    project.project_id,
                    "source_fetched",
                    source.title or source.canonical_uri or "",
                    {"source_id": source.source_id},
                )
                for span in _select_spans(content, query, limit=budget.max_evidence_per_source):
                    self.evidence.add_span(
                        project_id=project.project_id,
                        source_id=source.source_id,
                        span_text=span,
                        retrieval_method="web_fetch",
                        metadata={"url": page.canonical_url, "query": query},
                    )
                remaining -= 1
            self.store.add_event(
                project.project_id,
                "query_completed",
                f"Web results: {len(results)}",
                {"channel": "web", "query": query},
            )

    def _fetch_seed_urls(self, project: ResearchProject, remaining: int) -> None:
        for seed in project.seed_sources:
            if remaining <= 0:
                break
            if not (seed.startswith("http://") or seed.startswith("https://")):
                continue
            try:
                page = self.web.fetch_page(
                    seed,
                    respect_robots_txt=project.respect_robots_txt,
                )
            except Exception as exc:  # noqa: BLE001
                self.store.add_event(
                    project.project_id,
                    "source_parse_failed",
                    str(exc),
                    {"url": seed},
                )
                continue
            source, content = self.sources.from_web_page(project.project_id, page)
            for span in _select_spans(content, project.topic, limit=2):
                self.evidence.add_span(
                    project_id=project.project_id,
                    source_id=source.source_id,
                    span_text=span,
                    retrieval_method="web_seed_fetch",
                )
            remaining -= 1


def _select_spans(text: str, query: str, *, limit: int = 3) -> list[str]:
    """Pick query-relevant sentences; fall back to leading sentences — never invent text."""
    import re

    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    q_tokens = {t.lower() for t in re.findall(r"[A-Za-z0-9]{3,}", query.lower())}
    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        s = sentence.strip()
        if len(s) < 20:
            continue
        tokens = {t.lower() for t in re.findall(r"[A-Za-z0-9]{3,}", s.lower())}
        score = len(q_tokens & tokens)
        scored.append((score, s[:800]))
    scored.sort(key=lambda item: (-item[0], -len(item[1])))
    picked = [s for score, s in scored if score > 0][:limit]
    if picked:
        return picked
    # Fallback: first non-trivial sentences from the real source text.
    return [s.strip()[:800] for s in sentences if len(s.strip()) >= 20][:limit]
