"""Unified evidence reference parsing (U118) — one format across research/coding/tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvidenceRef:
    kind: str  # evidence | research | chunk | document | observation | artifact | receipt | file | research_project
    ref_id: str
    raw: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref_id": self.ref_id,
            "raw": self.raw,
            "truth": {"model_output_is_not_evidence": True},
        }

    def canonical(self) -> str:
        prefix = {
            "evidence": "ev",
            "research": "e",
            "chunk": "chunk",
            "document": "doc",
            "observation": "obs",
            "artifact": "art",
            "receipt": "receipt",
            "file": "file",
            "research_project": "research_project",
        }.get(self.kind, self.kind)
        return f"{prefix}:{self.ref_id}"


def parse_evidence_ref(raw: str) -> EvidenceRef | None:
    text = (raw or "").strip()
    if not text:
        return None
    if ":" not in text:
        return EvidenceRef(kind="evidence", ref_id=text, raw=text)
    prefix, _, rest = text.partition(":")
    rest = rest.strip()
    if not rest:
        return None
    mapping = {
        "ev": "evidence",
        "evidence": "evidence",
        "e": "research",
        "chunk": "chunk",
        "doc": "document",
        "document": "document",
        "obs": "observation",
        "observation": "observation",
        "art": "artifact",
        "artifact": "artifact",
        "receipt": "receipt",
        "cap": "receipt",
        "capability_receipt": "receipt",
        "file": "file",
        "path": "file",
        "research_project": "research_project",
    }
    kind = mapping.get(prefix.lower())
    if kind is None:
        return EvidenceRef(kind="evidence", ref_id=text, raw=text)
    return EvidenceRef(kind=kind, ref_id=rest, raw=text)


def format_evidence_ref(*, kind: str, ref_id: str) -> str:
    return EvidenceRef(kind=kind, ref_id=ref_id, raw="").canonical()
