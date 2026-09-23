"""Editable artifact runtime over content-addressed ArtifactStore (U383–U386 foundations).

Edits always create a new version (new content hash). Never mutate prior bytes.
Fixture document/spreadsheet/slide structure only — not a full Office suite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .store import ArtifactStore
from .types import ArtifactRecord


@dataclass(frozen=True)
class ArtifactVersion:
    artifact_id: str
    lineage_id: str
    version: int
    content_hash: str
    artifact_type: str
    parent_artifact_id: str | None = None
    sections: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "lineage_id": self.lineage_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "artifact_type": self.artifact_type,
            "parent_artifact_id": self.parent_artifact_id,
            "sections": list(self.sections),
            "metadata": self.metadata,
            "truth": {
                "edit_creates_new_version": True,
                "content_addressed_bytes_immutable": True,
                "not_full_office_suite": True,
            },
        }


class EditableArtifactRuntime:
    """Structured create/edit for documents, tables, slides as artifact operations."""

    SUPPORTED_TYPES = frozenset({"document", "spreadsheet", "presentation", "report", "code_bundle"})

    def __init__(self, store: ArtifactStore) -> None:
        self.store = store
        self._lineage_heads: dict[str, str] = {}  # lineage_id -> latest artifact_id

    def create(
        self,
        *,
        artifact_type: str,
        title: str,
        sections: list[dict[str, Any]] | None = None,
        producer: str = "artifact_runtime",
        run_id: str | None = None,
        project_id: str | None = None,
        lineage_id: str | None = None,
    ) -> ArtifactVersion:
        kind = artifact_type.strip().lower()
        if kind not in self.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported artifact type for editable runtime: {artifact_type}")
        body = {
            "title": title,
            "artifact_type": kind,
            "sections": list(sections or [{"id": "s1", "heading": title, "body": ""}]),
            "revision": 1,
        }
        data = json.dumps(body, sort_keys=True).encode("utf-8")
        lid = lineage_id or f"lin_{body['title'][:24]}"
        record = self.store.create_from_bytes(
            data=data,
            artifact_type=kind,
            producer=producer,
            filename=f"{kind}.json",
            run_id=run_id,
            metadata={
                "lineage_id": lid,
                "version": 1,
                "title": title,
                "project_id": project_id,
                "parent_artifact_id": None,
            },
        )
        self._lineage_heads[lid] = record.artifact_id
        return self._as_version(record, body["sections"])

    def edit(
        self,
        artifact_id: str,
        *,
        sections: list[dict[str, Any]] | None = None,
        title: str | None = None,
        patch_note: str = "",
        producer: str = "artifact_runtime",
        run_id: str | None = None,
    ) -> ArtifactVersion:
        parent = self.store.get(artifact_id)
        if parent is None:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        raw = Path_read(parent.path)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Artifact is not an editable structured document") from exc
        if sections is not None:
            body["sections"] = list(sections)
        if title is not None:
            body["title"] = title
        body["revision"] = int(body.get("revision") or 1) + 1
        if patch_note:
            body.setdefault("revision_notes", []).append(patch_note)
        lineage_id = str(parent.metadata.get("lineage_id") or parent.artifact_id)
        version = int(parent.metadata.get("version") or 1) + 1
        data = json.dumps(body, sort_keys=True).encode("utf-8")
        record = self.store.create_from_bytes(
            data=data,
            artifact_type=parent.artifact_type,
            producer=producer,
            filename=f"{parent.artifact_type}_v{version}.json",
            run_id=run_id,
            metadata={
                "lineage_id": lineage_id,
                "version": version,
                "title": body.get("title"),
                "project_id": parent.metadata.get("project_id"),
                "parent_artifact_id": parent.artifact_id,
                "patch_note": patch_note,
            },
        )
        self._lineage_heads[lineage_id] = record.artifact_id
        return self._as_version(record, body.get("sections") or [])

    def get_version(self, artifact_id: str) -> ArtifactVersion:
        record = self.store.get(artifact_id)
        if record is None:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        raw = Path_read(record.path)
        sections: list[dict[str, Any]] = []
        try:
            body = json.loads(raw.decode("utf-8"))
            sections = list(body.get("sections") or [])
        except (json.JSONDecodeError, UnicodeDecodeError):
            sections = []
        return self._as_version(record, sections)

    def lineage(self, lineage_id: str) -> list[ArtifactVersion]:
        # Scan is fine for fixture foundation; production would index by lineage_id.
        # ArtifactStore has no list-all — use head chain via parent links from head.
        head_id = self._lineage_heads.get(lineage_id)
        if head_id is None:
            return []
        chain: list[ArtifactVersion] = []
        current = head_id
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            version = self.get_version(current)
            chain.append(version)
            current = version.parent_artifact_id or ""
        chain.reverse()
        return chain

    def _as_version(self, record: ArtifactRecord, sections: list[dict[str, Any]]) -> ArtifactVersion:
        return ArtifactVersion(
            artifact_id=record.artifact_id,
            lineage_id=str(record.metadata.get("lineage_id") or record.artifact_id),
            version=int(record.metadata.get("version") or 1),
            content_hash=record.content_hash,
            artifact_type=record.artifact_type,
            parent_artifact_id=record.metadata.get("parent_artifact_id"),
            sections=tuple(sections),
            metadata=dict(record.metadata),
        )


def Path_read(path: str) -> bytes:
    from pathlib import Path

    return Path(path).read_bytes()
