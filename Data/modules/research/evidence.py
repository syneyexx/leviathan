"""Evidence ledger and citation resolution.

Citations are valid only when they resolve: citation → evidence → source → snapshot.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import ResearchStore
from .types import CitationResolution, ResearchEvidence, ResearchSource


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_CITATION_RE = re.compile(r"\[(?:e:)?([0-9a-fA-F-]{8,})\]")


class EvidenceLedger:
    def __init__(self, store: ResearchStore) -> None:
        self.store = store

    def add_span(
        self,
        *,
        project_id: str,
        source_id: str,
        span_text: str,
        chunk_id: str | None = None,
        location: dict[str, Any] | None = None,
        retrieval_method: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ResearchEvidence:
        text = (span_text or "").strip()
        if not text:
            raise ValueError("Evidence span cannot be empty")
        evidence = ResearchEvidence(
            evidence_id=str(uuid.uuid4()),
            project_id=project_id,
            source_id=source_id,
            chunk_id=chunk_id,
            span_text=text,
            location=dict(location or {}),
            retrieval_method=retrieval_method,
            associated_claim_ids=[],
            created_at=utc_now(),
            metadata=dict(metadata or {}),
        )
        return self.store.add_evidence(evidence)

    def resolve_citation(self, project_id: str, citation_key: str) -> CitationResolution:
        key = (citation_key or "").strip()
        evidence_id = key
        if key.startswith("e:"):
            evidence_id = key[2:]
        elif key.startswith("[") and key.endswith("]"):
            inner = key[1:-1]
            evidence_id = inner[2:] if inner.startswith("e:") else inner

        evidence = self.store.get_evidence(evidence_id)
        if evidence is None or evidence.project_id != project_id:
            return CitationResolution(
                citation_key=citation_key,
                resolved=False,
                reason="evidence_not_found",
            )
        source = self.store.get_source(evidence.source_id)
        if source is None:
            return CitationResolution(
                citation_key=citation_key,
                resolved=False,
                evidence_id=evidence.evidence_id,
                reason="source_not_found",
            )
        snapshot_ok = True
        if source.snapshot_path:
            snapshot_ok = Path(source.snapshot_path).is_file()
        if not snapshot_ok and source.source_type.value == "web_search":
            # Search hits may lack body snapshots until fetched.
            snapshot_ok = True
        if source.snapshot_path and not Path(source.snapshot_path).is_file():
            return CitationResolution(
                citation_key=citation_key,
                resolved=False,
                evidence_id=evidence.evidence_id,
                source_id=source.source_id,
                snapshot_path=source.snapshot_path,
                span_text=evidence.span_text,
                reason="snapshot_missing",
            )
        return CitationResolution(
            citation_key=f"e:{evidence.evidence_id}",
            resolved=True,
            evidence_id=evidence.evidence_id,
            source_id=source.source_id,
            snapshot_path=source.snapshot_path,
            span_text=evidence.span_text,
            reason=None,
            location=dict(evidence.location or {}),
        )

    def resolve_all_in_text(self, project_id: str, text: str) -> list[CitationResolution]:
        keys = []
        for match in _CITATION_RE.finditer(text or ""):
            keys.append(f"e:{match.group(1)}")
        # Deduplicate preserving order.
        seen: set[str] = set()
        out: list[CitationResolution] = []
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            out.append(self.resolve_citation(project_id, key))
        return out

    def mark_unresolved_in_text(self, project_id: str, text: str) -> str:
        """Rewrite unresolved citation markers so they are not presented as valid."""

        def repl(match: re.Match[str]) -> str:
            eid = match.group(1)
            resolution = self.resolve_citation(project_id, f"e:{eid}")
            if resolution.resolved:
                return f"[e:{eid}]"
            return f"[unresolved:{eid}]"

        return _CITATION_RE.sub(repl, text or "")


def evidence_to_citation_map(
    evidence_list: list[ResearchEvidence],
) -> dict[str, ResearchEvidence]:
    return {f"e:{item.evidence_id}": item for item in evidence_list}


def source_lookup(
    sources: list[ResearchSource],
) -> dict[str, ResearchSource]:
    return {item.source_id: item for item in sources}
