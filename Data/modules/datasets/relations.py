"""Grounded relation extraction from dataset records into KnowledgeStore.

Only relations supported by concrete record content are accepted.
Uncertain or model-only guesses are rejected — never stored as facts.
Optional model extractors may plug in later but must not block the base path.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from Data.modules.knowledge import KnowledgeStore
from Data.modules.knowledge.types import RelationClass

from .types import CanonicalRecord

_ENTITY_KEY_RE = re.compile(
    r"^(entity|subject|object|concept|term|name|label|topic|tag|id|ref|parent|child|"
    r"related|source|target|from|to)s?$",
    re.IGNORECASE,
)
_MIN_CONFIDENCE = 0.55
_MAX_RELATIONS_PER_DOC = 24


@dataclass
class RelationCandidate:
    subject_ref: str
    object_ref: str
    relation_class: RelationClass
    confidence: float
    evidence: str
    evidence_refs: list[str] = field(default_factory=list)
    notes: str = ""
    document_id: str | None = None
    chunk_id: str | None = None
    rejected: bool = False
    reject_reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "subjectRef": self.subject_ref,
            "objectRef": self.object_ref,
            "relationClass": self.relation_class.value,
            "confidence": self.confidence,
            "evidence": self.evidence[:240],
            "evidenceRefs": list(self.evidence_refs),
            "notes": self.notes,
            "documentId": self.document_id,
            "chunkId": self.chunk_id,
            "rejected": self.rejected,
            "rejectReason": self.reject_reason,
        }


def stable_relation_atom_id(
    *,
    dataset_id: str,
    version_id: str,
    subject_ref: str,
    object_ref: str,
    relation_class: str,
) -> str:
    digest = hashlib.sha256(
        f"{dataset_id}|{version_id}|{subject_ref}|{object_ref}|{relation_class}".encode("utf-8")
    ).hexdigest()[:32]
    return f"rel:{dataset_id}:{digest}"


def _norm_ref(value: Any, *, prefix: str = "entity") -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        return None
    if not text or len(text) > 200:
        return None
    # Avoid treating free prose as an entity id.
    if "\n" in text or len(text.split()) > 8:
        return None
    return f"{prefix}:{text.lower()}"


def _evidence_snippet(text: str, needle: str, *, width: int = 120) -> str:
    hay = text or ""
    idx = hay.lower().find(needle.lower()) if needle else -1
    if idx < 0:
        return hay[:width]
    start = max(0, idx - width // 3)
    end = min(len(hay), idx + len(needle) + width // 2)
    return hay[start:end].strip()


def extract_relation_candidates(
    rec: CanonicalRecord,
    *,
    document_id: str,
    dataset_id: str,
    version_id: str,
    text: str,
    max_relations: int = _MAX_RELATIONS_PER_DOC,
) -> list[RelationCandidate]:
    """Extract concrete, evidence-backed relation candidates from one record."""
    candidates: list[RelationCandidate] = []
    labels = dict(rec.labels or {}) if isinstance(rec.labels, dict) else {}
    meta = dict(rec.metadata or {}) if isinstance(rec.metadata, dict) else {}

    # 1) Explicit relations array in labels/metadata (structured evidence).
    for bucket_name, bucket in (("labels", labels), ("metadata", meta)):
        raw_rels = bucket.get("relations") or bucket.get("related")
        if not isinstance(raw_rels, list):
            continue
        for item in raw_rels:
            if not isinstance(item, dict):
                continue
            subj = _norm_ref(item.get("subject") or item.get("from") or item.get("source"))
            obj = _norm_ref(item.get("object") or item.get("to") or item.get("target"))
            if not subj or not obj or subj == obj:
                continue
            rel_raw = str(item.get("relation") or item.get("class") or "like").lower()
            try:
                rel_class = RelationClass(rel_raw) if rel_raw in {c.value for c in RelationClass} else RelationClass.LIKE
            except ValueError:
                rel_class = RelationClass.LIKE
            conf = float(item.get("confidence") or 0.85)
            evidence = str(item.get("evidence") or item.get("quote") or text[:160])
            candidates.append(
                RelationCandidate(
                    subject_ref=subj,
                    object_ref=obj,
                    relation_class=rel_class,
                    confidence=min(0.95, max(0.0, conf)),
                    evidence=evidence,
                    evidence_refs=[f"dataset:{dataset_id}:{version_id}:{rec.id}:{bucket_name}.relations"],
                    notes=f"explicit_{bucket_name}_relation",
                    document_id=document_id,
                )
            )

    # 2) subject/object pair fields.
    subj = _norm_ref(labels.get("subject") or meta.get("subject") or labels.get("from"))
    obj = _norm_ref(labels.get("object") or meta.get("object") or labels.get("to"))
    if subj and obj and subj != obj:
        snippet = _evidence_snippet(text, subj.split(":", 1)[-1])
        candidates.append(
            RelationCandidate(
                subject_ref=subj,
                object_ref=obj,
                relation_class=RelationClass.LIKE,
                confidence=0.8,
                evidence=snippet or text[:160],
                evidence_refs=[f"dataset:{dataset_id}:{version_id}:{rec.id}:subject_object"],
                notes="subject_object_fields",
                document_id=document_id,
            )
        )

    # 3) parent_id / related_id style references (concrete ids only).
    for key in ("parent_id", "parentId", "related_id", "relatedId", "ref", "see_also", "seeAlso"):
        value = labels.get(key) if key in labels else meta.get(key)
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        self_ref = _norm_ref(rec.id, prefix="record")
        for item in values:
            other = _norm_ref(item, prefix="record")
            if not self_ref or not other or self_ref == other:
                continue
            candidates.append(
                RelationCandidate(
                    subject_ref=self_ref,
                    object_ref=other,
                    relation_class=RelationClass.LIKE,
                    confidence=0.75,
                    evidence=f"{key}={item}",
                    evidence_refs=[f"dataset:{dataset_id}:{version_id}:{rec.id}:{key}"],
                    notes=f"structured_ref:{key}",
                    document_id=document_id,
                )
            )

    # 4) Co-occurring short entity-like label values (same record = shared evidence).
    entity_vals: list[str] = []
    for key, value in {**meta, **labels}.items():
        if not _ENTITY_KEY_RE.match(str(key)):
            continue
        vals = value if isinstance(value, list) else [value]
        for item in vals:
            ref = _norm_ref(item)
            if ref and ref not in entity_vals:
                entity_vals.append(ref)
    for i, left in enumerate(entity_vals):
        for right in entity_vals[i + 1 :]:
            left_tok = left.split(":", 1)[-1]
            right_tok = right.split(":", 1)[-1]
            # Require both tokens to appear in the text when text is non-empty.
            if text.strip():
                low = text.lower()
                if left_tok not in low or right_tok not in low:
                    continue
            snippet = _evidence_snippet(text, left_tok)
            candidates.append(
                RelationCandidate(
                    subject_ref=left,
                    object_ref=right,
                    relation_class=RelationClass.LIKE,
                    confidence=0.65,
                    evidence=snippet or text[:160],
                    evidence_refs=[f"dataset:{dataset_id}:{version_id}:{rec.id}:cooccur"],
                    notes="label_cooccurrence_with_text_evidence",
                    document_id=document_id,
                )
            )

    # 5) Proven membership: document belongs to dataset (always grounded).
    candidates.append(
        RelationCandidate(
            subject_ref=f"knowledge:document:{document_id}",
            object_ref=f"dataset:{dataset_id}",
            relation_class=RelationClass.LIKE,
            confidence=1.0,
            evidence=f"record {rec.id} ingested from dataset {dataset_id}",
            evidence_refs=[f"dataset:{dataset_id}:{version_id}:{rec.id}:membership"],
            notes="document_dataset_membership",
            document_id=document_id,
        )
    )

    # Deduplicate by endpoints+class, keep highest confidence.
    best: dict[tuple[str, str, str], RelationCandidate] = {}
    for cand in candidates:
        key = (cand.subject_ref, cand.object_ref, cand.relation_class.value)
        prev = best.get(key)
        if prev is None or cand.confidence > prev.confidence:
            best[key] = cand
    ordered = sorted(best.values(), key=lambda c: c.confidence, reverse=True)
    return ordered[: max(1, int(max_relations))]


def verify_candidate(cand: RelationCandidate) -> RelationCandidate:
    """Reject unproven / weak candidates. Never promote UNKNOWN without evidence."""
    if cand.rejected:
        return cand
    if not cand.subject_ref or not cand.object_ref:
        cand.rejected = True
        cand.reject_reason = "missing_endpoints"
        return cand
    if cand.subject_ref == cand.object_ref:
        cand.rejected = True
        cand.reject_reason = "self_relation"
        return cand
    if not cand.evidence or not str(cand.evidence).strip():
        cand.rejected = True
        cand.reject_reason = "missing_evidence"
        return cand
    if not cand.evidence_refs:
        cand.rejected = True
        cand.reject_reason = "missing_evidence_refs"
        return cand
    if cand.confidence < _MIN_CONFIDENCE:
        cand.rejected = True
        cand.reject_reason = "confidence_below_threshold"
        return cand
    if cand.relation_class == RelationClass.UNKNOWN and cand.confidence < 0.9:
        cand.rejected = True
        cand.reject_reason = "unknown_without_high_confidence"
        return cand
    return cand


def store_verified_relations(
    knowledge: KnowledgeStore,
    candidates: Iterable[RelationCandidate],
    *,
    dataset_id: str,
    version_id: str,
    replace_document_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Persist verified atoms idempotently; reject the rest."""
    if replace_document_ids:
        for doc_id in replace_document_ids:
            knowledge.delete_relation_atoms_for_document(doc_id)

    accepted = 0
    rejected = 0
    samples: list[dict[str, Any]] = []
    for cand in candidates:
        verified = verify_candidate(cand)
        if verified.rejected:
            rejected += 1
            if len(samples) < 8:
                samples.append(verified.public_dict())
            continue
        atom_id = stable_relation_atom_id(
            dataset_id=dataset_id,
            version_id=version_id,
            subject_ref=verified.subject_ref,
            object_ref=verified.object_ref,
            relation_class=verified.relation_class.value,
        )
        knowledge.upsert_relation_atom(
            subject_ref=verified.subject_ref,
            object_ref=verified.object_ref,
            relation_class=verified.relation_class,
            supporting_evidence_refs=verified.evidence_refs,
            document_id=verified.document_id,
            chunk_id=verified.chunk_id,
            confidence=verified.confidence,
            notes=f"{verified.notes}|evidence={verified.evidence[:180]}",
            atom_id=atom_id,
        )
        accepted += 1
        if len(samples) < 8:
            samples.append(verified.public_dict())

    return {
        "relationsAccepted": accepted,
        "relationsRejected": rejected,
        "relationSamples": samples,
        "truth": {
            "only_evidence_backed_relations_stored": True,
            "uncertain_relations_are_not_facts": True,
        },
    }


def extract_and_store_relations_for_record(
    knowledge: KnowledgeStore,
    rec: CanonicalRecord,
    *,
    document_id: str,
    dataset_id: str,
    version_id: str,
    text: str,
    max_relations: int = _MAX_RELATIONS_PER_DOC,
    replace: bool = True,
) -> dict[str, Any]:
    candidates = extract_relation_candidates(
        rec,
        document_id=document_id,
        dataset_id=dataset_id,
        version_id=version_id,
        text=text,
        max_relations=max_relations,
    )
    return store_verified_relations(
        knowledge,
        candidates,
        dataset_id=dataset_id,
        version_id=version_id,
        replace_document_ids=[document_id] if replace else None,
    )


# Extension point: optional model-backed extractor (must never be required).
ModelRelationExtractor = Callable[[CanonicalRecord, str], list[RelationCandidate]]
