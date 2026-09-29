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


class ResearchSourceCollector:
    """Collects research/web/local evidence into durable ResearchSource records."""

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

    def from_web_search(
        self,
        project_id: str,
        result: WebSearchResult,
        *,
        query: str | None = None,
        rank: int | None = None,
    ) -> ResearchSource:
        """Persist discovery metadata only — snippet is NOT verified evidence."""
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
            provenance={
                "provider": result.provider,
                "snippet": result.snippet,
                "query": query,
                "rank": rank,
                "discovered_url": result.url,
                "retrieval_status": "DISCOVERED_BUT_UNVERIFIED",
                "epistemic": "discovery_metadata_not_evidence",
            },
            metadata={
                "snippet": result.snippet,
                "query": query,
                "rank": rank,
                "retrieval_status": "DISCOVERED_BUT_UNVERIFIED",
            },
            created_at=utc_now(),
        )
        return self.store.upsert_source(source)

    def mark_discovery_unverified(
        self,
        source: ResearchSource,
        *,
        retrieval_status: str,
        error: str | None = None,
    ) -> ResearchSource:
        """Mark a search hit whose page could not be fetched/verified."""
        from dataclasses import replace

        status = (retrieval_status or "FETCH_FAILED").upper()
        if status not in {"FETCH_FAILED", "ROBOTS_BLOCKED", "DISCOVERED_BUT_UNVERIFIED"}:
            status = "FETCH_FAILED"
        meta = dict(source.metadata or {})
        prov = dict(source.provenance or {})
        meta["retrieval_status"] = status
        prov["retrieval_status"] = status
        if error:
            meta["fetch_error"] = str(error)[:500]
            prov["fetch_error"] = str(error)[:500]
        updated = replace(
            source,
            metadata=meta,
            provenance=prov,
            parse_status=(
                ParseStatus.FAILED
                if status != "DISCOVERED_BUT_UNVERIFIED"
                else ParseStatus.PENDING
            ),
        )
        return self.store.save_source(updated)

    def from_web_page(
        self,
        project_id: str,
        page: WebPageContent,
        *,
        discovery: ResearchSource | None = None,
        query: str | None = None,
        rank: int | None = None,
        provider: str | None = None,
    ) -> tuple[ResearchSource, str]:
        source_id = str(uuid.uuid4())
        snapshot = self._snapshot(project_id, source_id, page.text)
        robots = (page.metadata or {}).get("robots") or {}
        provenance = {
            "status_code": page.status_code,
            "provider": provider or (page.metadata or {}).get("provider"),
            "query": query,
            "rank": rank,
            "discovered_url": page.url,
            "canonical_url": page.canonical_url,
            "fetched_at": page.fetched_at,
            "published_at": (page.metadata or {}).get("published_at"),
            "content_hash": page.content_hash,
            "content_type": page.content_type,
            "http_status": page.status_code,
            "robots_decision": robots.get("reason") if isinstance(robots, dict) else None,
            "retrieval_status": "FETCHED" if page.status_code < 400 else "FETCH_FAILED",
            **{k: v for k, v in (page.metadata or {}).items() if k not in {"robots"}},
            "robots": robots,
        }
        if discovery is not None:
            provenance["discovery_source_id"] = discovery.source_id
            provenance.setdefault("provider", (discovery.provenance or {}).get("provider"))
            provenance.setdefault("query", (discovery.provenance or {}).get("query"))
            provenance.setdefault("rank", (discovery.provenance or {}).get("rank"))
        source = ResearchSource(
            source_id=source_id,
            project_id=project_id,
            source_type=SourceType.WEB_PAGE,
            original_uri=page.url,
            canonical_uri=page.canonical_url,
            title=page.title,
            published_at=(page.metadata or {}).get("published_at"),
            fetched_at=page.fetched_at,
            content_hash=page.content_hash,
            mime_type=page.content_type,
            snapshot_path=str(snapshot),
            parse_status=ParseStatus.OK if page.status_code < 400 else ParseStatus.FAILED,
            parser=str((page.metadata or {}).get("extractor") or "http_fetch"),
            provenance=provenance,
            metadata=dict(page.metadata),
            created_at=utc_now(),
        )
        stored = self.store.upsert_source(source)
        if discovery is not None and discovery.parse_status == ParseStatus.PENDING:
            # Link discovery → fetched page without promoting snippet to evidence.
            from dataclasses import replace

            dmeta = dict(discovery.metadata or {})
            dprov = dict(discovery.provenance or {})
            dmeta["retrieval_status"] = "FETCHED"
            dmeta["fetched_source_id"] = stored.source_id
            dprov["retrieval_status"] = "FETCHED"
            dprov["fetched_source_id"] = stored.source_id
            self.store.save_source(
                replace(
                    discovery,
                    metadata=dmeta,
                    provenance=dprov,
                    parse_status=ParseStatus.OK,
                )
            )
        content = page.text
        if stored.source_id != source.source_id and stored.snapshot_path:
            try:
                content = Path(stored.snapshot_path).read_text(encoding="utf-8")
            except OSError:
                content = page.text
        return stored, content


# Deprecated alias — research evidence collector, not Data/modules/source_ingestion/.
SourceIngestor = ResearchSourceCollector
