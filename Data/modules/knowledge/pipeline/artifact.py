"""Typed knowledge artifact produced by workers — content is file-backed when large."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class KnowledgeArtifact:
    artifact_id: str
    artifact_type: str
    producer: str
    producer_version: str
    title: str
    summary: str = ""
    job_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    source_kind: str | None = None
    source_ref: str | None = None
    source_digest: str | None = None
    domain: str | None = None
    scope: str | None = None
    project_id: str | None = None
    content_ref: str | None = None
    content_digest: str | None = None
    content_inline: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    citation_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    confidence: float | None = None
    trust: float | None = None
    uncertainty: str | None = None
    sensitivity: str | None = None
    security_flags: list[str] = field(default_factory=list)
    suggested_destinations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        artifact_type: str,
        producer: str,
        title: str,
        content: str | None = None,
        producer_version: str = "1",
        **kwargs: Any,
    ) -> KnowledgeArtifact:
        digest = None
        if content is not None:
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return cls(
            artifact_id=str(uuid.uuid4()),
            artifact_type=artifact_type,
            producer=producer,
            producer_version=producer_version,
            title=title,
            content_inline=content if content is not None and len(content) < 64_000 else None,
            content_digest=digest,
            **kwargs,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "producer": self.producer,
            "producer_version": self.producer_version,
            "job_id": self.job_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "source_digest": self.source_digest,
            "domain": self.domain,
            "scope": self.scope,
            "project_id": self.project_id,
            "title": self.title,
            "summary": self.summary,
            "content_ref": self.content_ref,
            "content_digest": self.content_digest,
            "has_inline_content": self.content_inline is not None,
            "provenance": dict(self.provenance),
            "citation_refs": list(self.citation_refs),
            "evidence_refs": list(self.evidence_refs),
            "claims": list(self.claims),
            "topics": list(self.topics),
            "entities": list(self.entities),
            "tags": list(self.tags),
            "confidence": self.confidence,
            "trust": self.trust,
            "uncertainty": self.uncertainty,
            "sensitivity": self.sensitivity,
            "security_flags": list(self.security_flags),
            "suggested_destinations": list(self.suggested_destinations),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.public_dict(), ensure_ascii=False)
