"""Brain / KnowledgeStore synchronization for Research artifacts."""

from __future__ import annotations

from typing import Any

from Data.modules.knowledge import KnowledgeStore

from .store import ResearchStore
from .types import BrainStatus, ParseStatus, ResearchProject, ResearchReport, ResearchSource, SourceType


class ResearchBrainSync:
    def __init__(self, store: ResearchStore, knowledge: KnowledgeStore | None) -> None:
        self.store = store
        self.knowledge = knowledge

    def sync_uploaded_source(self, source: ResearchSource, text: str) -> ResearchSource:
        """Always Brain-sync user-provided parsed files."""
        if self.knowledge is None:
            return self._mark(source, BrainStatus.FAILED, error="KnowledgeStore unavailable")

        if source.parse_status != ParseStatus.OK or not (text or "").strip():
            return self._mark(source, BrainStatus.SKIPPED, error="No parseable text")

        doc_id = f"research-upload:{source.content_hash or source.source_id}"
        prov = source.provenance or {}
        archive = prov.get("archive_filename")
        rel = prov.get("relative_path")
        title = f"{archive}/{rel}" if archive and rel else (source.title or "Research upload")
        try:
            record = self.knowledge.upsert_document(
                document_id=doc_id,
                title=title,
                content=text,
                source="research_upload",
                original_path=str(rel or source.original_uri),
                size_bytes=len(text.encode("utf-8")),
                parser=source.parser or "research_upload",
                source_type="research_upload",
                trust_metadata={
                    "trust": "user_supplied",
                    "source": "research_upload",
                    "project_id": source.project_id,
                    "research_source_id": source.source_id,
                    "filename": source.title,
                    "mime_type": source.mime_type,
                    "content_hash": source.content_hash,
                    "parser": source.parser,
                    "parser_version": prov.get("parser_version"),
                    "container_source_id": prov.get("container_source_id"),
                    "parent_source_id": prov.get("parent_source_id"),
                    "archive_filename": archive,
                    "relative_path": rel,
                    "original_path": rel or source.original_uri,
                },
            )
            return self._mark(
                source,
                BrainStatus.SYNCED,
                document_id=record.id if hasattr(record, "id") else doc_id,
            )
        except Exception as exc:  # noqa: BLE001 — preserve ResearchSource
            return self._mark(source, BrainStatus.FAILED, error=str(exc))

    def sync_web_page(self, source: ResearchSource, text: str) -> ResearchSource:
        """Brain-sync successfully fetched full web pages that Research used."""
        if self.knowledge is None:
            return self._mark(source, BrainStatus.FAILED, error="KnowledgeStore unavailable")
        if source.source_type != SourceType.WEB_PAGE:
            return self._mark(source, BrainStatus.SKIPPED, error="Not a full web page")
        if source.parse_status != ParseStatus.OK or not (text or "").strip():
            return self._mark(source, BrainStatus.SKIPPED, error="No page text")
        # Do not sync bare search snippets.
        if source.source_type == SourceType.WEB_SEARCH:
            return self._mark(source, BrainStatus.SKIPPED, error="Search snippets are not full documents")

        doc_id = f"research-web:{source.content_hash or source.source_id}"
        try:
            record = self.knowledge.upsert_document(
                document_id=doc_id,
                title=source.title or source.canonical_uri or "Web page",
                content=text,
                source="research_web",
                original_path=source.canonical_uri or source.original_uri,
                parser=source.parser or "http_fetch",
                source_type="research_web",
                trust_metadata={
                    "trust": "web_retrieved",
                    "source": "research_web",
                    "project_id": source.project_id,
                    "research_source_id": source.source_id,
                    "url": source.canonical_uri or source.original_uri,
                    "content_hash": source.content_hash,
                },
                confidence=0.5,
                uncertainty_notes="Web content is not authoritative merely because it entered Brain.",
            )
            return self._mark(
                source,
                BrainStatus.SYNCED,
                document_id=record.id if hasattr(record, "id") else doc_id,
            )
        except Exception as exc:  # noqa: BLE001
            return self._mark(source, BrainStatus.FAILED, error=str(exc))

    def sync_report(self, project: ResearchProject, report: ResearchReport) -> None:
        if self.knowledge is None:
            raise RuntimeError("KnowledgeStore unavailable")
        doc_id = f"research-report:{project.project_id}:{report.version}"
        self.knowledge.upsert_document(
            document_id=doc_id,
            title=report.title,
            content=report.body_markdown,
            source="research_report",
            parser="research_report",
            source_type="research_report",
            trust_metadata={
                "trust": "research_synthesis",
                "source": "research_report",
                "project_id": project.project_id,
                "report_id": report.report_id,
                "version": report.version,
                "workers": project.budget.research_workers,
                "rounds": project.budget.rounds,
                "execution_mode": project.execution_mode.value,
                "analysis_mode": project.analysis_mode.value,
            },
            confidence=0.7,
            uncertainty_notes="Report claims must be verified against stored evidence citations.",
        )

    def retry_brain_sync(self, source_id: str) -> ResearchSource:
        source = self.store.get_source(source_id)
        if source is None:
            raise KeyError(source_id)
        if not source.snapshot_path:
            return self._mark(source, BrainStatus.FAILED, error="No snapshot to sync")
        from pathlib import Path

        text = Path(source.snapshot_path).read_text(encoding="utf-8")
        if source.source_type == SourceType.LOCAL_FILE:
            return self.sync_uploaded_source(source, text)
        if source.source_type == SourceType.WEB_PAGE:
            return self.sync_web_page(source, text)
        return self._mark(source, BrainStatus.SKIPPED, error="Source type not Brain-synced")

    def _mark(
        self,
        source: ResearchSource,
        status: BrainStatus,
        *,
        document_id: str | None = None,
        error: str | None = None,
    ) -> ResearchSource:
        updated = ResearchSource(
            source_id=source.source_id,
            project_id=source.project_id,
            source_type=source.source_type,
            created_at=source.created_at,
            original_uri=source.original_uri,
            canonical_uri=source.canonical_uri,
            title=source.title,
            author=source.author,
            published_at=source.published_at,
            fetched_at=source.fetched_at,
            content_hash=source.content_hash,
            mime_type=source.mime_type,
            snapshot_path=source.snapshot_path,
            parse_status=source.parse_status,
            parser=source.parser,
            brain_status=status,
            brain_document_id=document_id if document_id is not None else source.brain_document_id,
            brain_error=error,
            provenance=dict(source.provenance),
            metadata=dict(source.metadata),
        )
        return self.store.save_source(updated)
