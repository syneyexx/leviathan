"""Parallel research worker coordinator — bounded fan-out / barrier / merge."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .claims import ClaimAnalyzer
from .conflicts import ConflictDetector
from .coverage import build_coverage
from .evidence import EvidenceLedger
from .local_retrieval import LocalResearchRetriever
from .planner import apply_plan_edits, build_plan
from .reports import ReportBuilder
from .sources import SourceIngestor
from .store import ResearchStore, utc_now
from .types import (
    ACTIVE_STATUSES,
    AnalysisMode,
    ResearchError,
    ResearchExecutionMode,
    ResearchPhase,
    ResearchProject,
    ResearchRun,
    ResearchStatus,
    ResearchWorker,
    WorkerStatus,
)
from .web import WebResearchProvider, web_unavailable_reason


def compute_progress(
    *,
    completed_worker_rounds: int,
    total_worker_rounds: int,
    phase: ResearchPhase,
) -> float:
    """Monotonic progress: worker-rounds dominate; reserve weight for finals."""
    if phase == ResearchPhase.COMPLETED:
        return 100.0
    if phase in {ResearchPhase.FAILED, ResearchPhase.CANCELLED}:
        base = 0.0
        if total_worker_rounds > 0:
            base = 90.0 * (completed_worker_rounds / total_worker_rounds)
        return min(95.0, max(0.0, base))
    if total_worker_rounds <= 0:
        return 5.0
    round_frac = min(1.0, completed_worker_rounds / total_worker_rounds)
    if phase in {
        ResearchPhase.PLANNING,
        ResearchPhase.SOURCE_INGESTION,
        ResearchPhase.LOCAL_RETRIEVAL,
        ResearchPhase.WEB_SEARCH,
        ResearchPhase.SOURCE_FETCH,
        ResearchPhase.SOURCE_PARSE,
        ResearchPhase.EVIDENCE_EXTRACTION,
        ResearchPhase.CLAIM_ANALYSIS,
        ResearchPhase.CONFLICT_ANALYSIS,
        ResearchPhase.QUERY_ADAPTATION,
    }:
        return round(5.0 + round_frac * 80.0, 2)
    if phase == ResearchPhase.SYNTHESIS:
        return round(85.0 + round_frac * 5.0, 2)
    if phase == ResearchPhase.REPORT_GENERATION:
        return 92.0
    if phase == ResearchPhase.BRAIN_SYNC:
        return 96.0
    return round(5.0 + round_frac * 80.0, 2)


def assign_worker_queries(
    queries: list[str],
    *,
    worker_index: int,
    worker_count: int,
    round_number: int,
    subquestions: list[str] | None = None,
) -> list[str]:
    """Deterministic complementary query assignment — workers do not all search the same thing."""
    pool = list(queries) if queries else []
    if subquestions:
        for sq in subquestions:
            if sq not in pool:
                pool.append(sq)
    if not pool:
        return []
    # Rotate by round, then stride by worker index.
    rotated = pool[round_number % len(pool) :] + pool[: round_number % len(pool)]
    assigned: list[str] = []
    for i, q in enumerate(rotated):
        if i % max(1, worker_count) == (worker_index % max(1, worker_count)):
            assigned.append(q)
    # Personality lanes: odd workers prefer later (conflict/alt) queries.
    if worker_index % 2 == 1 and len(rotated) > 1:
        alt = [q for q in reversed(rotated) if q not in assigned][:1]
        for q in alt:
            if q not in assigned:
                assigned.append(q)
    return assigned or [rotated[worker_index % len(rotated)]]


class ResearchCoordinator:
    """Owns multi-worker round execution for a single ResearchRunner."""

    def __init__(
        self,
        store: ResearchStore,
        *,
        local: LocalResearchRetriever,
        web: WebResearchProvider,
        allow_outbound: bool,
        sources: SourceIngestor,
        evidence: EvidenceLedger,
        claims: ClaimAnalyzer,
        conflicts: ConflictDetector,
        reports: ReportBuilder,
        brain_sync: Callable[[ResearchProject, Any], None] | None = None,
        select_spans: Callable[..., list[str]],
    ) -> None:
        self.store = store
        self.local = local
        self.web = web
        self.allow_outbound = bool(allow_outbound)
        self.sources = sources
        self.evidence = evidence
        self.claims = claims
        self.conflicts = conflicts
        self.reports = reports
        self.brain_sync = brain_sync
        self._select_spans = select_spans
        self._lock = threading.Lock()

    def run(
        self,
        project_id: str,
        *,
        extra_rounds: int = 0,
        deepen: bool = False,
        resume: bool = False,
    ) -> ResearchProject:
        project = self.store.get_project(project_id)
        if project is None:
            raise ResearchError("RESEARCH_NOT_FOUND", f"Unknown project: {project_id}", http_status=404)

        if project.status in {ResearchStatus.RESEARCHING, ResearchStatus.SYNTHESIZING}:
            from Data.modules.common.process import pid_is_alive

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
            project.phase = ResearchPhase.PLANNING
            self.store.save_project(project)
            self.store.add_event(project_id, "plan_generated", "Plan created before run")

        workers_n = max(1, project.budget.research_workers)
        rounds_n = max(1, project.budget.rounds)

        if deepen:
            rounds_n = rounds_n + max(1, extra_rounds or 1)
            project.budget = apply_plan_edits(
                project.plan,
                {"budget": {**project.budget.public_dict(), "rounds": rounds_n}, "rounds": rounds_n},
            ).budget if project.plan else project.budget
            # Keep budget.rounds authoritative.
            from .types import ResearchBudget

            project.budget = ResearchBudget(
                search_queries=project.budget.search_queries,
                urls_per_query=project.budget.urls_per_query,
                max_sources=project.budget.max_sources,
                rounds=rounds_n,
                research_workers=workers_n,
                max_local_hits=project.budget.max_local_hits,
                max_evidence_per_source=project.budget.max_evidence_per_source,
            )
            if project.plan:
                project.plan = apply_plan_edits(project.plan, {"rounds": rounds_n, "budget": project.budget.public_dict()})
            self.store.add_event(
                project_id,
                "deepen_requested",
                f"Additional round(s); rounds_per_worker={rounds_n}",
            )
        elif extra_rounds > 0:
            rounds_n = max(rounds_n, project.current_round + extra_rounds)
            from .types import ResearchBudget

            project.budget = ResearchBudget(
                search_queries=project.budget.search_queries,
                urls_per_query=project.budget.urls_per_query,
                max_sources=project.budget.max_sources,
                rounds=rounds_n,
                research_workers=workers_n,
                max_local_hits=project.budget.max_local_hits,
                max_evidence_per_source=project.budget.max_evidence_per_source,
            )

        start_round = 1
        if resume and project.completed_worker_rounds > 0 and workers_n > 0:
            # Resume from next incomplete worker-round barrier.
            start_round = min(
                rounds_n,
                (project.completed_worker_rounds // workers_n) + 1,
            )
            if start_round < 1:
                start_round = 1

        total_worker_rounds = workers_n * rounds_n
        now = utc_now()
        run = ResearchRun(
            run_id=str(uuid.uuid4()),
            project_id=project_id,
            status=ResearchStatus.RESEARCHING,
            execution_mode=project.execution_mode,
            workers=workers_n,
            rounds_per_worker=rounds_n,
            phase=ResearchPhase.PLANNING,
            completed_worker_rounds=max(0, (start_round - 1) * workers_n),
            total_worker_rounds=total_worker_rounds,
            progress_pct=0.0,
            analysis_mode=project.analysis_mode,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        self.store.create_run(run)

        workers: list[ResearchWorker] = []
        for idx in range(workers_n):
            worker = ResearchWorker(
                worker_id=str(uuid.uuid4()),
                project_id=project_id,
                run_id=run.run_id,
                worker_index=idx + 1,
                status=WorkerStatus.QUEUED,
                total_rounds=rounds_n,
                completed_rounds=max(0, start_round - 1),
                created_at=now,
                updated_at=now,
            )
            self.store.upsert_worker(worker)
            workers.append(worker)

        project.cancel_requested = False
        project.error = None
        project.status = ResearchStatus.RESEARCHING
        project.phase = ResearchPhase.PLANNING
        project.started_at = project.started_at or now
        project.finished_at = None
        project.worker_pid = os.getpid()
        project.active_run_id = run.run_id
        project.total_rounds = rounds_n
        project.total_worker_rounds = total_worker_rounds
        project.completed_worker_rounds = run.completed_worker_rounds
        project.progress_pct = compute_progress(
            completed_worker_rounds=run.completed_worker_rounds,
            total_worker_rounds=total_worker_rounds,
            phase=ResearchPhase.PLANNING,
        )
        web_reason = web_unavailable_reason(
            allow_web=project.allow_web,
            allow_outbound=self.allow_outbound,
            provider=self.web,
        )
        project.web_unavailable_reason = web_reason
        self.store.save_project(project)
        self.store.add_event(
            project_id,
            "run_started",
            f"Run {run.run_id} with {workers_n} workers × {rounds_n} rounds",
            {
                "run_id": run.run_id,
                "workers": workers_n,
                "rounds_per_worker": rounds_n,
                "execution_mode": project.execution_mode.value,
            },
        )
        self.store.add_event(
            project_id,
            "workers_spawned",
            f"Spawned {workers_n} workers",
            {"worker_ids": [w.worker_id for w in workers]},
        )

        try:
            for round_number in range(start_round, rounds_n + 1):
                if self._cancelled(project_id):
                    return self._finalize_cancelled(project_id, run, workers)

                project = self.store.get_project(project_id) or project
                project.current_round = round_number
                project.phase = ResearchPhase.LOCAL_RETRIEVAL
                self.store.save_project(project)
                self.store.add_event(
                    project_id,
                    "round_started",
                    f"Round {round_number}/{rounds_n}",
                    {"round": round_number, "run_id": run.run_id},
                )

                plan = project.plan
                queries = list(plan.retrieval_queries) if plan else [project.topic]
                subqs = list(plan.subquestions) if plan else []

                # Fan-out worker round tasks concurrently.
                with ThreadPoolExecutor(max_workers=workers_n) as pool:
                    futures = {
                        pool.submit(
                            self._worker_round,
                            worker,
                            project_id,
                            round_number,
                            rounds_n,
                            assign_worker_queries(
                                queries,
                                worker_index=worker.worker_index - 1,
                                worker_count=workers_n,
                                round_number=round_number,
                                subquestions=subqs,
                            ),
                        ): worker
                        for worker in workers
                        if worker.status not in {WorkerStatus.FAILED, WorkerStatus.CANCELLED}
                        or worker.completed_rounds < round_number
                    }
                    for fut in as_completed(futures):
                        worker = futures[fut]
                        try:
                            result = fut.result()
                            worker = result
                        except Exception as exc:  # noqa: BLE001 — isolate worker failure
                            worker.status = WorkerStatus.FAILED
                            worker.last_error = str(exc)
                            worker.phase = "failed"
                            worker.heartbeat_at = utc_now()
                            self.store.upsert_worker(worker)
                            self.store.add_event(
                                project_id,
                                "worker_failed",
                                str(exc),
                                {
                                    "worker_id": worker.worker_id,
                                    "worker_index": worker.worker_index,
                                    "round": round_number,
                                },
                            )

                # Barrier: refresh workers, count completed rounds.
                workers = self.store.list_workers(project_id, run_id=run.run_id)
                for worker in workers:
                    if worker.status == WorkerStatus.WAITING_AT_BARRIER:
                        worker.status = WorkerStatus.ANALYZING
                        worker.phase = "analyzing"
                        self.store.upsert_worker(worker)

                if self._cancelled(project_id):
                    return self._finalize_cancelled(project_id, run, workers)

                project = self.store.get_project(project_id) or project
                project.phase = ResearchPhase.CLAIM_ANALYSIS
                self.store.save_project(project)
                claims = self.claims.analyze_project(project_id)
                project.phase = ResearchPhase.CONFLICT_ANALYSIS
                self.store.save_project(project)
                conflicts = self.conflicts.detect(project_id, claims)
                for conflict in conflicts:
                    self.store.add_event(
                        project_id,
                        "contradiction_detected",
                        conflict.summary,
                        {"conflict_id": conflict.conflict_id},
                    )

                # Immutable plan adaptation for next round.
                if round_number < rounds_n and project.plan:
                    project.phase = ResearchPhase.QUERY_ADAPTATION
                    self.store.save_project(project)
                    adapted = list(project.plan.retrieval_queries)
                    for conflict in conflicts:
                        for q in conflict.unresolved_questions:
                            if q not in adapted:
                                adapted.append(q)
                    adapted = adapted[: project.budget.search_queries + 3]
                    project.plan = apply_plan_edits(
                        project.plan,
                        {"retrieval_queries": adapted},
                    )
                    self.store.save_project(project)
                    self.store.add_event(
                        project_id,
                        "plan_adapted",
                        f"Adapted queries after round {round_number}",
                        {"queries": adapted},
                    )

                # Count completed worker-rounds (one per non-cancelled worker this round).
                completed_this = sum(
                    1
                    for w in workers
                    if w.completed_rounds >= round_number
                    and w.status != WorkerStatus.CANCELLED
                )
                run.completed_worker_rounds = (round_number - 1) * workers_n + completed_this
                # Prefer sum of completed_rounds across workers when available.
                run.completed_worker_rounds = sum(w.completed_rounds for w in workers)
                run.progress_pct = compute_progress(
                    completed_worker_rounds=run.completed_worker_rounds,
                    total_worker_rounds=total_worker_rounds,
                    phase=ResearchPhase.CLAIM_ANALYSIS,
                )
                self.store.save_run(run)

                project = self.store.get_project(project_id) or project
                project.completed_worker_rounds = run.completed_worker_rounds
                project.progress_pct = run.progress_pct
                project.current_round = round_number
                self.store.save_project(project)
                self.store.add_event(
                    project_id,
                    "round_completed",
                    f"Round {round_number} complete",
                    {
                        "round": round_number,
                        "completed_worker_rounds": run.completed_worker_rounds,
                    },
                )

            workers = self.store.list_workers(project_id, run_id=run.run_id)
            healthy = [w for w in workers if w.status != WorkerStatus.FAILED]
            if not healthy and workers:
                raise ResearchError(
                    "RESEARCH_FAILED",
                    "All research workers failed",
                    http_status=500,
                    details={"project_id": project_id, "run_id": run.run_id},
                )

            if self._cancelled(project_id):
                return self._finalize_cancelled(project_id, run, workers)

            # Synthesis / report / brain.
            project = self.store.get_project(project_id) or project
            project.status = ResearchStatus.SYNTHESIZING
            project.phase = ResearchPhase.SYNTHESIS
            project.progress_pct = compute_progress(
                completed_worker_rounds=run.completed_worker_rounds,
                total_worker_rounds=total_worker_rounds,
                phase=ResearchPhase.SYNTHESIS,
            )
            self.store.save_project(project)
            run.status = ResearchStatus.SYNTHESIZING
            run.phase = ResearchPhase.SYNTHESIS
            run.progress_pct = project.progress_pct
            self.store.save_run(run)
            self.store.add_event(project_id, "synthesis_started", "Building coverage and report")

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
            project.phase = ResearchPhase.REPORT_GENERATION
            project.progress_pct = 92.0
            self.store.save_project(project)
            run.phase = ResearchPhase.REPORT_GENERATION
            run.progress_pct = 92.0
            self.store.save_run(run)

            report = self.reports.generate(project)
            self.store.add_event(
                project_id,
                "report_generated",
                f"Report version {report.version}",
                {"report_id": report.report_id, "version": report.version},
            )

            project = self.store.get_project(project_id) or project
            project.phase = ResearchPhase.BRAIN_SYNC
            project.progress_pct = 96.0
            self.store.save_project(project)
            if self.brain_sync is not None:
                try:
                    self.brain_sync(project, report)
                    self.store.add_event(project_id, "brain_sync", "Report synced to KnowledgeStore")
                except Exception as exc:  # noqa: BLE001
                    self.store.add_event(
                        project_id,
                        "brain_sync_failed",
                        str(exc),
                        {"stage": "report"},
                    )

            for worker in workers:
                if worker.status not in {WorkerStatus.FAILED, WorkerStatus.CANCELLED}:
                    worker.status = WorkerStatus.COMPLETED
                    worker.phase = "completed"
                    worker.finished_at = utc_now()
                    self.store.upsert_worker(worker)
                    self.store.add_event(
                        project_id,
                        "worker_completed",
                        f"Worker {worker.worker_index} completed",
                        {"worker_id": worker.worker_id, "worker_index": worker.worker_index},
                    )

            project = self.store.get_project(project_id) or project
            project.status = ResearchStatus.COMPLETED
            project.phase = ResearchPhase.COMPLETED
            project.progress_pct = 100.0
            project.worker_pid = None
            project.finished_at = utc_now()
            project.cancel_requested = False
            project.completed_worker_rounds = total_worker_rounds
            self.store.save_project(project)
            run.status = ResearchStatus.COMPLETED
            run.phase = ResearchPhase.COMPLETED
            run.progress_pct = 100.0
            run.completed_worker_rounds = total_worker_rounds
            run.finished_at = utc_now()
            self.store.save_run(run)
            self.store.add_event(project_id, "completed", "Research completed")
            return self.store.get_project(project_id) or project

        except ResearchError as exc:
            self._mark_failed(project_id, run, str(exc.message))
            raise
        except Exception as exc:  # noqa: BLE001
            self._mark_failed(project_id, run, str(exc))
            raise ResearchError(
                "RESEARCH_FAILED",
                str(exc),
                http_status=500,
                details={"project_id": project_id},
            ) from exc

    def _mark_failed(self, project_id: str, run: ResearchRun, message: str) -> None:
        project = self.store.get_project(project_id)
        if project is None:
            return
        project.status = ResearchStatus.FAILED
        project.phase = ResearchPhase.FAILED
        project.error = message
        project.worker_pid = None
        project.finished_at = utc_now()
        # Never claim 100% on failure.
        project.progress_pct = min(95.0, float(project.progress_pct or 0))
        self.store.save_project(project)
        run.status = ResearchStatus.FAILED
        run.phase = ResearchPhase.FAILED
        run.error = message
        run.finished_at = utc_now()
        run.progress_pct = project.progress_pct
        self.store.save_run(run)
        self.store.add_event(project_id, "failed", message)

    def _cancelled(self, project_id: str) -> bool:
        return self.store.is_cancel_requested(project_id)

    def _finalize_cancelled(
        self,
        project_id: str,
        run: ResearchRun,
        workers: list[ResearchWorker],
    ) -> ResearchProject:
        for worker in self.store.list_workers(project_id, run_id=run.run_id):
            if worker.status not in {WorkerStatus.COMPLETED, WorkerStatus.FAILED}:
                worker.status = WorkerStatus.CANCELLED
                worker.phase = "cancelled"
                worker.finished_at = utc_now()
                self.store.upsert_worker(worker)
        project = self.store.get_project(project_id)
        assert project is not None
        project.status = ResearchStatus.CANCELLED
        project.phase = ResearchPhase.CANCELLED
        project.worker_pid = None
        project.finished_at = utc_now()
        project.cancel_requested = False
        project.error = project.error or "Cancelled by request"
        project.progress_pct = min(95.0, float(project.progress_pct or 0))
        self.store.save_project(project)
        run.status = ResearchStatus.CANCELLED
        run.phase = ResearchPhase.CANCELLED
        run.finished_at = utc_now()
        run.progress_pct = project.progress_pct
        self.store.save_run(run)
        self.store.add_event(project_id, "cancelled", "Research cancelled")
        return project

    def _worker_round(
        self,
        worker: ResearchWorker,
        project_id: str,
        round_number: int,
        total_rounds: int,
        queries: list[str],
    ) -> ResearchWorker:
        if self._cancelled(project_id):
            worker.status = WorkerStatus.CANCELLED
            worker.phase = "cancelled"
            worker.finished_at = utc_now()
            self.store.upsert_worker(worker)
            return worker

        project = self.store.get_project(project_id)
        if project is None:
            worker.status = WorkerStatus.FAILED
            worker.last_error = "project missing"
            self.store.upsert_worker(worker)
            return worker

        worker.current_round = round_number
        worker.total_rounds = total_rounds
        worker.started_at = worker.started_at or utc_now()
        worker.heartbeat_at = utc_now()
        worker.status = WorkerStatus.RETRIEVING_LOCAL
        worker.phase = "retrieving_local"
        worker.current_task = f"round:{round_number}"
        self.store.upsert_worker(worker)
        self.store.add_event(
            project_id,
            "worker_phase_changed",
            f"Worker {worker.worker_index} retrieving_local",
            {
                "worker_id": worker.worker_id,
                "worker_index": worker.worker_index,
                "phase": "retrieving_local",
                "round": round_number,
                "total_rounds": total_rounds,
            },
        )

        budget = project.budget
        sources_before = len(self.store.list_sources(project_id))
        evidence_before = len(self.store.list_evidence(project_id))

        # Local retrieval for assigned queries.
        if self.local.available:
            remaining = budget.max_sources - sources_before
            for query in queries[: budget.search_queries]:
                if self._cancelled(project_id):
                    break
                worker.current_query = query
                worker.heartbeat_at = utc_now()
                worker.status = WorkerStatus.RETRIEVING_LOCAL
                worker.phase = "retrieving_local"
                self.store.upsert_worker(worker)
                self.store.add_event(
                    project_id,
                    "query_started",
                    f"Worker {worker.worker_index} local: {query}",
                    {
                        "channel": "local",
                        "query": query,
                        "worker_id": worker.worker_id,
                        "worker_index": worker.worker_index,
                    },
                )
                hits = self.local.search(
                    query,
                    limit=min(budget.max_local_hits, max(1, remaining or 1)),
                    local_scopes=project.local_scopes or None,
                )
                added = 0
                for hit in hits:
                    if remaining <= 0 or self._cancelled(project_id):
                        break
                    worker.status = WorkerStatus.EXTRACTING_EVIDENCE
                    worker.phase = "extracting_evidence"
                    self.store.upsert_worker(worker)
                    source, content = self.sources.from_local_hit(project_id, hit)
                    self.store.add_event(
                        project_id,
                        "source_discovered",
                        source.title or source.source_id,
                        {
                            "source_id": source.source_id,
                            "channel": "local",
                            "worker_id": worker.worker_id,
                        },
                    )
                    for span in self._select_spans(
                        content, query, limit=budget.max_evidence_per_source
                    ):
                        self.evidence.add_span(
                            project_id=project_id,
                            source_id=source.source_id,
                            span_text=span,
                            chunk_id=hit.chunk_id,
                            location={
                                "document_id": hit.document_id,
                                "chunk_id": hit.chunk_id,
                                "chunk_index": hit.chunk_index,
                            },
                            retrieval_method="local_knowledge",
                            metadata={
                                "score": hit.score,
                                "query": query,
                                "worker_index": worker.worker_index,
                            },
                        )
                        self.store.add_event(
                            project_id,
                            "evidence_added",
                            span[:120],
                            {"source_id": source.source_id, "worker_id": worker.worker_id},
                        )
                    added += 1
                    remaining -= 1
                self.store.add_event(
                    project_id,
                    "query_completed",
                    f"Local hits used: {added}",
                    {
                        "channel": "local",
                        "query": query,
                        "hits": len(hits),
                        "worker_id": worker.worker_id,
                    },
                )

        # Seed text once (worker 1 only) on round 1.
        if worker.worker_index == 1 and round_number == 1:
            remaining = budget.max_sources - len(self.store.list_sources(project_id))
            for seed in project.seed_sources:
                if remaining <= 0:
                    break
                if seed.startswith("text:"):
                    body = seed[5:]
                    source, content = self.sources.from_seed_text(
                        project_id, title="Seed text", text=body
                    )
                    for span in self._select_spans(content, project.topic, limit=2):
                        self.evidence.add_span(
                            project_id=project_id,
                            source_id=source.source_id,
                            span_text=span,
                            retrieval_method="seed",
                        )
                    remaining -= 1

        # Web round for this worker's queries.
        if project.allow_web and not self._cancelled(project_id):
            reason = web_unavailable_reason(
                allow_web=True,
                allow_outbound=self.allow_outbound,
                provider=self.web,
            )
            if reason:
                self.store.add_event(
                    project_id,
                    "query_completed",
                    f"Web research unavailable: {reason}",
                    {
                        "channel": "web",
                        "status": "unavailable",
                        "reason": reason,
                        "worker_id": worker.worker_id,
                    },
                )
            else:
                search_ready = getattr(self.web, "search_configured", lambda: False)()
                remaining = budget.max_sources - len(self.store.list_sources(project_id))
                if search_ready and remaining > 0:
                    for query in queries[: budget.search_queries]:
                        if remaining <= 0 or self._cancelled(project_id):
                            break
                        worker.status = WorkerStatus.SEARCHING_WEB
                        worker.phase = "searching_web"
                        worker.current_query = query
                        worker.heartbeat_at = utc_now()
                        self.store.upsert_worker(worker)
                        self.store.add_event(
                            project_id,
                            "worker_phase_changed",
                            f"Worker {worker.worker_index} searching_web",
                            {
                                "worker_id": worker.worker_id,
                                "worker_index": worker.worker_index,
                                "phase": "searching_web",
                                "round": round_number,
                                "total_rounds": total_rounds,
                                "query": query,
                            },
                        )
                        try:
                            results = self.web.search(query, limit=budget.urls_per_query)
                        except Exception as exc:  # noqa: BLE001
                            self.store.add_event(
                                project_id,
                                "query_completed",
                                f"Web search failed: {exc}",
                                {"channel": "web", "error": str(exc), "worker_id": worker.worker_id},
                            )
                            continue
                        for result in results:
                            if remaining <= 0:
                                break
                            self.sources.from_web_search(project_id, result)
                            worker.status = WorkerStatus.FETCHING_SOURCE
                            worker.phase = "fetching_source"
                            worker.current_task = result.url
                            self.store.upsert_worker(worker)
                            try:
                                page = self.web.fetch_page(
                                    result.url,
                                    respect_robots_txt=project.respect_robots_txt,
                                )
                            except Exception as exc:  # noqa: BLE001
                                self.store.add_event(
                                    project_id,
                                    "source_parse_failed",
                                    str(exc),
                                    {"url": result.url, "worker_id": worker.worker_id},
                                )
                                continue
                            worker.status = WorkerStatus.PARSING_SOURCE
                            worker.phase = "parsing_source"
                            self.store.upsert_worker(worker)
                            source, content = self.sources.from_web_page(project_id, page)
                            self.store.add_event(
                                project_id,
                                "source_fetched",
                                source.title or source.canonical_uri or "",
                                {"source_id": source.source_id, "worker_id": worker.worker_id},
                            )
                            worker.status = WorkerStatus.EXTRACTING_EVIDENCE
                            worker.phase = "extracting_evidence"
                            self.store.upsert_worker(worker)
                            for span in self._select_spans(
                                content, query, limit=budget.max_evidence_per_source
                            ):
                                self.evidence.add_span(
                                    project_id=project_id,
                                    source_id=source.source_id,
                                    span_text=span,
                                    retrieval_method="web_fetch",
                                    metadata={
                                        "url": page.canonical_url,
                                        "query": query,
                                        "worker_index": worker.worker_index,
                                    },
                                )
                            remaining -= 1
                        self.store.add_event(
                            project_id,
                            "query_completed",
                            f"Web results: {len(results)}",
                            {
                                "channel": "web",
                                "query": query,
                                "worker_id": worker.worker_id,
                            },
                        )
                elif worker.worker_index == 1 and round_number == 1:
                    # Seed URL fetches on first worker only.
                    remaining = budget.max_sources - len(self.store.list_sources(project_id))
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
                                project_id,
                                "source_parse_failed",
                                str(exc),
                                {"url": seed},
                            )
                            continue
                        source, content = self.sources.from_web_page(project_id, page)
                        for span in self._select_spans(content, project.topic, limit=2):
                            self.evidence.add_span(
                                project_id=project_id,
                                source_id=source.source_id,
                                span_text=span,
                                retrieval_method="web_seed_fetch",
                            )
                        remaining -= 1

        sources_after = len(self.store.list_sources(project_id))
        evidence_after = len(self.store.list_evidence(project_id))
        worker.sources_added += max(0, sources_after - sources_before)
        worker.evidence_added += max(0, evidence_after - evidence_before)
        worker.completed_rounds = round_number
        worker.status = WorkerStatus.WAITING_AT_BARRIER
        worker.phase = "waiting_at_barrier"
        worker.heartbeat_at = utc_now()
        self.store.upsert_worker(worker)
        self.store.add_event(
            project_id,
            "worker_phase_changed",
            f"Worker {worker.worker_index} waiting_at_barrier",
            {
                "worker_id": worker.worker_id,
                "worker_index": worker.worker_index,
                "phase": "waiting_at_barrier",
                "round": round_number,
                "total_rounds": total_rounds,
            },
        )
        return worker
