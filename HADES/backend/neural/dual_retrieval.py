"""Exact Brain + Neural Memory dual retrieval (Phase 11).

Keeps categories distinct. Neural associations are never treated as verified
evidence. Results compile into existing ContextItem / Context Compiler inputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal, Mapping, Sequence

from reasoning.contracts import ContextItem
from reasoning.context import budget_context_items, estimate_chars


ProvenanceStatus = Literal["exact_source", "neural_association", "durable_memory", "unknown"]
CandidateType = Literal["exact", "neural", "durable_memory"]


@dataclass(frozen=True)
class RetrievalCandidate:
    candidate_id: str
    candidate_type: CandidateType
    content: str
    score: float
    confidence: float
    domain: str = "general"
    checkpoint_id: str | None = None
    provenance_status: ProvenanceStatus = "unknown"
    source_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


@dataclass
class DualRetrievalResult:
    query: str
    exact: list[RetrievalCandidate] = field(default_factory=list)
    neural: list[RetrievalCandidate] = field(default_factory=list)
    durable: list[RetrievalCandidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def all_candidates(self) -> list[RetrievalCandidate]:
        return list(self.exact) + list(self.neural) + list(self.durable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "exact": [c.to_dict() for c in self.exact],
            "neural": [c.to_dict() for c in self.neural],
            "durable": [c.to_dict() for c in self.durable],
            "notes": list(self.notes),
        }


def candidate_to_context_item(candidate: RetrievalCandidate, *, priority_base: int = 100) -> ContextItem:
    """Map a retrieval candidate to a ContextItem without collapsing categories."""
    if candidate.candidate_type == "neural":
        # Never mark neural associations trusted / evidence-grade.
        return ContextItem(
            item_id=candidate.candidate_id,
            kind="neural_association",
            content=(
                f"[neural_association domain={candidate.domain} "
                f"checkpoint={candidate.checkpoint_id or 'none'} "
                f"score={candidate.score:.3f}]\n{candidate.content}"
            ),
            provenance=f"neural_association:{candidate.checkpoint_id or 'unspecified'}",
            priority=priority_base + max(0, int(100 * (1.0 - candidate.score))),
            trusted=False,
            redactable=True,
        )
    if candidate.candidate_type == "exact":
        return ContextItem(
            item_id=candidate.candidate_id,
            kind="evidence",
            content=candidate.content,
            provenance=candidate.source_ref or f"exact:{candidate.candidate_id}",
            priority=priority_base + max(0, int(80 * (1.0 - candidate.score))),
            trusted=True,
            redactable=True,
        )
    return ContextItem(
        item_id=candidate.candidate_id,
        kind="memory",
        content=candidate.content,
        provenance=candidate.source_ref or f"durable:{candidate.candidate_id}",
        priority=priority_base + max(0, int(90 * (1.0 - candidate.score))),
        trusted=False,
        redactable=True,
    )


def candidates_to_compiler_items(candidates: Sequence[RetrievalCandidate]) -> list[dict[str, Any]]:
    """Pack candidates for gen2.compile_context item dicts without mixing provenance."""
    items: list[dict[str, Any]] = []
    for cand in candidates:
        item = candidate_to_context_item(cand)
        items.append(
            {
                "id": item.item_id,
                "content": item.content,
                "score": float(cand.score),
                "source": item.provenance,
                "candidate_type": cand.candidate_type,
                "provenance_status": cand.provenance_status,
                "domain": cand.domain,
                "checkpoint_id": cand.checkpoint_id,
                "trusted": item.trusted,
                "kind": item.kind,
            }
        )
    return items


def retrieve_dual(
    query: str,
    *,
    exact_retrieve: Callable[[str], Sequence[Mapping[str, Any] | RetrievalCandidate]] | None = None,
    neural_retrieve: Callable[[str], Sequence[Mapping[str, Any] | RetrievalCandidate]] | None = None,
    durable_retrieve: Callable[[str], Sequence[Mapping[str, Any] | RetrievalCandidate]] | None = None,
    max_exact: int = 8,
    max_neural: int = 4,
    max_durable: int = 4,
) -> DualRetrievalResult:
    """Query Exact / Neural / Durable banks independently; do not dump all Brain."""
    result = DualRetrievalResult(query=query)
    if exact_retrieve is not None:
        result.exact = _normalize_batch(exact_retrieve(query), default_type="exact", limit=max_exact)
    else:
        result.notes.append("exact_retrieve_skipped")
    if neural_retrieve is not None:
        result.neural = _normalize_batch(neural_retrieve(query), default_type="neural", limit=max_neural)
    else:
        result.notes.append("neural_retrieve_skipped")
    if durable_retrieve is not None:
        result.durable = _normalize_batch(durable_retrieve(query), default_type="durable_memory", limit=max_durable)
    else:
        result.notes.append("durable_retrieve_skipped")
    return result


def compile_dual_context(
    result: DualRetrievalResult,
    *,
    modes: Sequence[str] | None = None,
    max_chars: int = 4000,
) -> dict[str, Any]:
    """Build budgeted ContextItems for experiment modes A/B/C/D.

    A: no memory
    B: exact only
    C: neural only
    D: exact + neural (+ durable if present)
    """
    mode_list = list(modes or ("A", "B", "C", "D"))
    reports: dict[str, Any] = {}
    for mode in mode_list:
        selected: list[RetrievalCandidate] = []
        if mode == "A":
            selected = []
        elif mode == "B":
            selected = list(result.exact)
        elif mode == "C":
            selected = list(result.neural)
        elif mode == "D":
            selected = list(result.exact) + list(result.neural) + list(result.durable)
        else:
            raise ValueError(f"unsupported dual-retrieval mode: {mode}")
        items = [candidate_to_context_item(c) for c in selected]
        kept, budget = budget_context_items(items, max_chars=max_chars)
        # Guard: neural items must never be trusted.
        for item in kept:
            if item.kind == "neural_association" and item.trusted:
                raise AssertionError("neural_association must not be trusted")
        reports[mode] = {
            "mode": mode,
            "candidate_count": len(selected),
            "kept_items": [item.to_dict() for item in kept],
            "budget": budget.to_dict(),
            "token_estimate_chars": sum(estimate_chars(item.content) for item in kept),
            "exact_kept": sum(1 for i in kept if i.kind == "evidence"),
            "neural_kept": sum(1 for i in kept if i.kind == "neural_association"),
            "durable_kept": sum(1 for i in kept if i.kind == "memory"),
            "compiler_items": candidates_to_compiler_items(selected),
        }
    return {
        "query": result.query,
        "modes": reports,
        "notes": list(result.notes),
    }


def _normalize_batch(
    raw_items: Sequence[Mapping[str, Any] | RetrievalCandidate],
    *,
    default_type: CandidateType,
    limit: int,
) -> list[RetrievalCandidate]:
    out: list[RetrievalCandidate] = []
    for index, raw in enumerate(raw_items):
        if len(out) >= max(0, int(limit)):
            break
        if isinstance(raw, RetrievalCandidate):
            cand = raw
        else:
            ctype = str(raw.get("candidate_type") or default_type)
            if ctype not in {"exact", "neural", "durable_memory"}:
                ctype = default_type
            cand = RetrievalCandidate(
                candidate_id=str(raw.get("candidate_id") or raw.get("id") or f"{ctype}-{index}"),
                candidate_type=ctype,  # type: ignore[arg-type]
                content=str(raw.get("content") or ""),
                score=float(raw.get("score") or 0.0),
                confidence=float(raw.get("confidence") or raw.get("score") or 0.0),
                domain=str(raw.get("domain") or "general"),
                checkpoint_id=(str(raw["checkpoint_id"]) if raw.get("checkpoint_id") is not None else None),
                provenance_status=(
                    "neural_association"
                    if ctype == "neural"
                    else (
                        "exact_source"
                        if ctype == "exact"
                        else ("durable_memory" if ctype == "durable_memory" else "unknown")
                    )
                ),
                source_ref=(str(raw["source_ref"]) if raw.get("source_ref") is not None else None),
                metadata=dict(raw.get("metadata") or {}),
            )
        if not cand.content.strip():
            continue
        if default_type == "neural" or cand.candidate_type == "neural":
            # Hard enforce neural category separation.
            cand = RetrievalCandidate(
                candidate_id=cand.candidate_id,
                candidate_type="neural",
                content=cand.content,
                score=cand.score,
                confidence=cand.confidence,
                domain=cand.domain,
                checkpoint_id=cand.checkpoint_id,
                provenance_status="neural_association",
                source_ref=cand.source_ref,
                metadata=dict(cand.metadata),
            )
        out.append(cand)
    out.sort(key=lambda c: (-c.score, c.candidate_id))
    return out
