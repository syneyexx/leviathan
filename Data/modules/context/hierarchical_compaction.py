"""Hierarchical conversation compaction — derived segments only.

Canonical history is never deleted. Segments are versioned by content hash so
unchanged older segments are reused when only the recent tail changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .compaction import CompactionResult, compact_conversation, extract_hard_constraints

COMPACTOR_VERSION = "hierarchical-compactor-v1"


@dataclass(frozen=True)
class CompactionSegment:
    segment_id: str
    kind: str  # raw_tail | compacted | session_summary | pinned
    source_range: tuple[int, int]
    source_hash: str
    artifact_hash: str
    summary: str
    hard_constraints: tuple[str, ...]
    commitments: tuple[str, ...]
    created_at: str | None = None
    model_prompt_version: str | None = None
    compactor_version: str = COMPACTOR_VERSION

    def public_dict(self) -> dict[str, Any]:
        return {
            "segmentId": self.segment_id,
            "kind": self.kind,
            "sourceRange": list(self.source_range),
            "sourceHash": self.source_hash,
            "artifactHash": self.artifact_hash,
            "summaryPreview": self.summary[:240] + ("…" if len(self.summary) > 240 else ""),
            "hardConstraints": list(self.hard_constraints),
            "commitments": list(self.commitments),
            "createdAt": self.created_at,
            "modelPromptVersion": self.model_prompt_version,
            "compactorVersion": self.compactor_version,
            "truth": {
                "summary_is_derived": True,
                "does_not_replace_canonical_history": True,
            },
        }


@dataclass
class HierarchicalCompactionResult:
    segments: tuple[CompactionSegment, ...]
    hard_constraints: tuple[str, ...]
    recent_tail: tuple[dict[str, str], ...]
    reused_segment_ids: tuple[str, ...] = ()
    total_source_messages: int = 0

    def as_history_overlay(self) -> list[dict[str, str]]:
        """Build derived history messages for packing — originals remain elsewhere."""
        out: list[dict[str, str]] = []
        if self.hard_constraints:
            out.append(
                {
                    "role": "system",
                    "content": "Pinned hard constraints (authoritative):\n- "
                    + "\n- ".join(self.hard_constraints),
                }
            )
        for seg in self.segments:
            if seg.kind == "raw_tail":
                continue
            out.append(
                {
                    "role": "system",
                    "content": (
                        f"[Derived {seg.kind} {seg.segment_id} | src={seg.source_hash[:12]}]\n"
                        f"{seg.summary}"
                    ),
                }
            )
        out.extend(list(self.recent_tail))
        return out

    def public_dict(self) -> dict[str, Any]:
        return {
            "segments": [s.public_dict() for s in self.segments],
            "hardConstraints": list(self.hard_constraints),
            "reusedSegmentIds": list(self.reused_segment_ids),
            "totalSourceMessages": self.total_source_messages,
            "recentTailCount": len(self.recent_tail),
            "truth": {
                "canonical_history_preserved": True,
                "hierarchical_reuse": True,
            },
        }


def _msg_hash(messages: list[dict[str, Any]]) -> str:
    blob = json.dumps(
        [{"role": m.get("role"), "content": m.get("content")} for m in messages],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compact_hierarchical(
    history: list[dict[str, Any]],
    *,
    recent_tail_messages: int = 8,
    segment_size: int = 20,
    existing_segments: dict[str, CompactionSegment] | None = None,
    max_summary_chars: int = 1200,
) -> HierarchicalCompactionResult:
    """Build hierarchical derived segments; reuse unchanged older segment hashes."""
    usable = [
        {"role": str(m.get("role") or ""), "content": str(m.get("content") or "")}
        for m in history
        if str(m.get("role") or "") in {"user", "assistant"} and str(m.get("content") or "").strip()
    ]
    existing = existing_segments or {}
    reused: list[str] = []
    segments: list[CompactionSegment] = []
    all_hard: list[str] = []

    if len(usable) <= recent_tail_messages:
        # Only raw tail — no compaction needed.
        for m in usable:
            all_hard.extend(extract_hard_constraints(m["content"]))
        return HierarchicalCompactionResult(
            segments=(),
            hard_constraints=tuple(dict.fromkeys(all_hard)),
            recent_tail=tuple(usable),
            reused_segment_ids=(),
            total_source_messages=len(usable),
        )

    tail = usable[-recent_tail_messages:]
    older = usable[:-recent_tail_messages]

    # Chunk older history into segments.
    for start in range(0, len(older), segment_size):
        chunk = older[start : start + segment_size]
        end = start + len(chunk) - 1
        source_hash = _msg_hash(chunk)
        seg_id = f"seg:{source_hash[:16]}"
        if seg_id in existing and existing[seg_id].source_hash == source_hash:
            segments.append(existing[seg_id])
            reused.append(seg_id)
            all_hard.extend(existing[seg_id].hard_constraints)
            continue
        result: CompactionResult = compact_conversation(chunk, max_summary_chars=max_summary_chars)
        seg = CompactionSegment(
            segment_id=seg_id,
            kind="compacted",
            source_range=(start, end),
            source_hash=source_hash,
            artifact_hash=result.artifact_hash,
            summary=result.summary,
            hard_constraints=result.hard_constraints,
            commitments=result.commitments,
        )
        segments.append(seg)
        all_hard.extend(result.hard_constraints)

    # Long-horizon session summary from segment summaries when many segments.
    if len(segments) >= 3:
        summary_src = [{"role": "assistant", "content": s.summary} for s in segments]
        src_hash = _msg_hash(summary_src)
        sid = f"session:{src_hash[:16]}"
        if sid in existing and existing[sid].source_hash == src_hash:
            session = existing[sid]
            reused.append(sid)
        else:
            rolled = compact_conversation(summary_src, max_summary_chars=max_summary_chars)
            session = CompactionSegment(
                segment_id=sid,
                kind="session_summary",
                source_range=(0, len(older) - 1),
                source_hash=src_hash,
                artifact_hash=rolled.artifact_hash,
                summary=rolled.summary,
                hard_constraints=rolled.hard_constraints,
                commitments=rolled.commitments,
            )
        # Keep session summary + drop intermediate if we roll up? Keep all for provenance;
        # packing layer may prefer session + recent.
        segments = [session]

    for m in tail:
        all_hard.extend(extract_hard_constraints(m["content"]))

    # Dedupe hard constraints preserving order
    hard = tuple(dict.fromkeys(all_hard))
    return HierarchicalCompactionResult(
        segments=tuple(segments),
        hard_constraints=hard,
        recent_tail=tuple(tail),
        reused_segment_ids=tuple(reused),
        total_source_messages=len(usable),
    )
