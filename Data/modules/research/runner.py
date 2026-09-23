"""Research execution runner — delegates parallel work to ResearchCoordinator."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from Data.modules.common.process import pid_is_alive

from .claims import ClaimAnalyzer
from .conflicts import ConflictDetector
from .coordinator import ResearchCoordinator
from .evidence import EvidenceLedger
from .local_retrieval import LocalResearchRetriever
from .reports import ReportBuilder
from .sources import SourceIngestor
from .store import ResearchStore, utc_now
from .types import (
    ACTIVE_STATUSES,
    ResearchError,
    ResearchPhase,
    ResearchProject,
    ResearchStatus,
    WorkerStatus,
)
from .web import WebResearchProvider


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
        brain_sync: Callable[[ResearchProject, Any], None] | None = None,
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
        self.brain_sync = brain_sync
        self.coordinator = ResearchCoordinator(
            store,
            local=local,
            web=web,
            allow_outbound=allow_outbound,
            sources=self.sources,
            evidence=self.evidence,
            claims=self.claims,
            conflicts=self.conflicts,
            reports=self.reports,
            brain_sync=brain_sync,
            select_spans=_select_spans,
        )

    def recover_interrupted(self) -> list[str]:
        """Mark researching projects with dead workers as interrupted."""
        recovered: list[str] = []
        for project in self.store.list_projects(limit=500):
            if project.status not in ACTIVE_STATUSES:
                continue
            pid = project.worker_pid
            if pid is None:
                # Queued with no worker yet — leave for background dispatcher.
                if project.status == ResearchStatus.QUEUED:
                    continue
                # Researching without pid → interrupted (process crash before pid set).
                if project.status in {
                    ResearchStatus.RESEARCHING,
                    ResearchStatus.SYNTHESIZING,
                    ResearchStatus.CANCELLING,
                }:
                    project.status = ResearchStatus.INTERRUPTED
                    project.phase = ResearchPhase.FAILED
                    project.error = project.error or "Research process interrupted"
                    project.finished_at = utc_now()
                    self.store.save_project(project)
                    for worker in self.store.list_workers(project.project_id):
                        if worker.status not in {
                            WorkerStatus.COMPLETED,
                            WorkerStatus.FAILED,
                            WorkerStatus.CANCELLED,
                        }:
                            worker.status = WorkerStatus.FAILED
                            worker.last_error = "process interrupted"
                            worker.finished_at = utc_now()
                            self.store.upsert_worker(worker)
                    self.store.add_event(
                        project.project_id,
                        "interrupted",
                        project.error,
                        {},
                    )
                    recovered.append(project.project_id)
                continue
            if pid_is_alive(pid):
                continue
            project.status = ResearchStatus.INTERRUPTED
            project.phase = ResearchPhase.FAILED
            project.error = f"Worker pid {pid} no longer alive"
            project.worker_pid = None
            project.finished_at = utc_now()
            # Do not claim completion after interruption.
            project.progress_pct = min(95.0, float(project.progress_pct or 0))
            self.store.save_project(project)
            for worker in self.store.list_workers(project.project_id):
                if worker.status not in {
                    WorkerStatus.COMPLETED,
                    WorkerStatus.FAILED,
                    WorkerStatus.CANCELLED,
                }:
                    worker.status = WorkerStatus.FAILED
                    worker.last_error = project.error
                    worker.finished_at = utc_now()
                    self.store.upsert_worker(worker)
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
        resume: bool = False,
    ) -> ResearchProject:
        return self.coordinator.run(
            project_id,
            extra_rounds=extra_rounds,
            deepen=deepen,
            resume=resume,
        )


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
    return [s.strip()[:800] for s in sentences if len(s.strip()) >= 20][:limit]
