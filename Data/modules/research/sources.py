"""Source ingestion — durable records with hash-aware snapshots."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.common.atomic import atomic_write_text, ensure_dir
from Data.modules.common.hashing import sha256_text

from .local_retrieval import LocalHit
from .store import ResearchStore
from .types import ParseStatus, ResearchSource, SourceType
from .web import WebPageContent, WebSearchResult


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SourceIngestor:
    def __init__(self, store: ResearchStore, snapshots_root: Path) -> None:
        self.store = store
        self.snapshots_root = ensure_dir(Path(snapshots_root))

    def _snapshot(self, project_id: str, source_id: str, text: str) -> Path:
        dest_dir = ensure_dir(self.snapshots_root / project_id)
        path = dest_dir / f"{source_id}.txt"
        atomic_write_text(path, text)
        return path

    def from_local_hit(self, project_id: str, hit: LocalHit) -> tuple[ResearchSource, str]:
        content = hit.content
        content_hash = hit.document_hash or sha256_text(content)
        source_id = str(uuid.uuid4())
        snapshot = self._snapshot(project_id, source_id, content)
        source = ResearchSource(
            source_id=source_id,
            project_id=project_id,
            source_type=SourceType.KNOWLEDGE,
            original_uri=hit.original_path or f"knowledge://{hit.document_id}",
            canonical_uri=f"knowledge://{hit.document_id}#{hit.chunk_id}",
            title=hit.title,
            fetched_at=hit.retrieved_at,
            content_hash=content_hash,
            mime_type="text/plain",
            snapshot_path=str(snapshot),
            parse_status=ParseStatus.OK,
            parser="knowledge_chunk",
            provenance={
                "document_id": hit.document_id,
                "chunk_id": hit.chunk_id,
                "chunk_index": hit.chunk_index,
                "chunk_hash": hit.chunk_hash,
                "knowledge_source": hit.source,
                "score": hit.score,
                "modality": hit.modality,
                "query": hit.query,
            },
            metadata={"retriever": "local_knowledge"},
            created_at=utc_now(),
        )
        stored = self.store.upsert_source(source)
        # If deduped, use existing snapshot/content.
        if stored.source_id != source.source_id and stored.snapshot_path:
            try:
                content = Path(stored.snapshot_path).read_text(encoding="utf-8")
            except OSError:
                content = hit.content
        elif stored.source_id != source.source_id:
            content = hit.content
        return stored, content

    def from_seed_text(
        self,
        project_id: str,
        *,
        title: str,
        text: str,
        uri: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[ResearchSource, str]:
        content = text.strip()
        content_hash = sha256_text(content)
        source_id = str(uuid.uuid4())
        snapshot = self._snapshot(project_id, source_id, content)
        source = ResearchSource(
            source_id=source_id,
            project_id=project_id,
            source_type=SourceType.SEED,
            original_uri=uri or f"seed://{source_id}",
            canonical_uri=uri or f"seed://{source_id}",
            title=title,
            fetched_at=utc_now(),
            content_hash=content_hash,
            mime_type="text/plain",
            snapshot_path=str(snapshot),
            parse_status=ParseStatus.OK,
            parser="seed_text",
            provenance={"kind": "seed"},
            metadata=dict(metadata or {}),
            created_at=utc_now(),
        )
        return self.store.upsert_source(source), content

    def from_web_search(self, project_id: str, result: WebSearchResult) -> ResearchSource:
        source = ResearchSource(
            source_id=str(uuid.uuid4()),
            project_id=project_id,
            source_type=SourceType.WEB_SEARCH,
            original_uri=result.url,
            canonical_uri=result.url,
            title=result.title,
            fetched_at=result.retrieved_at,
            mime_type="text/uri-list",
            parse_status=ParseStatus.PENDING,
            parser=None,
            provenance={"provider": result.provider, "snippet": result.snippet},
            metadata={"snippet": result.snippet},
            created_at=utc_now(),
        )
        return self.store.upsert_source(source)

    def from_web_page(self, project_id: str, page: WebPageContent) -> tuple[ResearchSource, str]:
        source_id = str(uuid.uuid4())
        snapshot = self._snapshot(project_id, source_id, page.text)
        source = ResearchSource(
            source_id=source_id,
            project_id=project_id,
            source_type=SourceType.WEB_PAGE,
            original_uri=page.url,
            canonical_uri=page.canonical_url,
            title=page.title,
            fetched_at=page.fetched_at,
            content_hash=page.content_hash,
            mime_type=page.content_type,
            snapshot_path=str(snapshot),
            parse_status=ParseStatus.OK if page.status_code < 400 else ParseStatus.FAILED,
            parser="http_fetch",
            provenance={"status_code": page.status_code, **page.metadata},
            metadata=dict(page.metadata),
            created_at=utc_now(),
        )
        stored = self.store.upsert_source(source)
        content = page.text
        if stored.source_id != source.source_id and stored.snapshot_path:
            try:
                content = Path(stored.snapshot_path).read_text(encoding="utf-8")
            except OSError:
                content = page.text
        return stored, content
