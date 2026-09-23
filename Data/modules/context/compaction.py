"""Semantic conversation compaction — derived summaries, never destructive (U065–U066)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


CONSTRAINT_PATTERNS = (
    re.compile(r"\b(must|shall|never|always|do not|don't|required|constraint)\b", re.I),
    re.compile(r"\b(prefer|preference|remember that)\b", re.I),
)


@dataclass(frozen=True)
class CompactionResult:
    summary: str
    commitments: tuple[str, ...]
    constraints: tuple[str, ...]
    unresolved: tuple[str, ...]
    source_message_count: int
    artifact_hash: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "commitments": list(self.commitments),
            "constraints": list(self.constraints),
            "unresolved": list(self.unresolved),
            "source_message_count": self.source_message_count,
            "artifact_hash": self.artifact_hash,
            "truth": {
                "summary_is_derived_artifact": True,
                "does_not_replace_canonical_history": True,
            },
        }


def compact_conversation(
    history: list[dict[str, str]],
    *,
    max_summary_chars: int = 1200,
) -> CompactionResult:
    """Extract commitments/constraints from history without deleting originals."""
    commitments: list[str] = []
    constraints: list[str] = []
    unresolved: list[str] = []
    lines: list[str] = []
    for item in history:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if not content or role not in {"user", "assistant"}:
            continue
        lines.append(f"{role}: {content}")
        if role == "user" and content.endswith("?"):
            unresolved.append(content[:240])
        for pattern in CONSTRAINT_PATTERNS:
            if pattern.search(content):
                constraints.append(content[:240])
                break
        if role == "assistant" and any(
            token in content.lower() for token in ("will ", "i'll ", "we will ", "decided")
        ):
            commitments.append(content[:240])

    # Deduplicate while preserving order
    def uniq(items: list[str]) -> tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return tuple(out)

    constraints_u = uniq(constraints)
    commitments_u = uniq(commitments)
    unresolved_u = uniq(unresolved)[-5:]
    parts = [
        "COMPACTED CONTEXT (derived — originals retained)",
        f"constraints({len(constraints_u)}): " + " | ".join(constraints_u) if constraints_u else "constraints: none",
        f"commitments({len(commitments_u)}): " + " | ".join(commitments_u) if commitments_u else "commitments: none",
        f"unresolved({len(unresolved_u)}): " + " | ".join(unresolved_u) if unresolved_u else "unresolved: none",
    ]
    summary = "\n".join(parts)
    if len(summary) > max_summary_chars:
        summary = summary[: max_summary_chars - 1] + "…"
    digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()[:16]
    return CompactionResult(
        summary=summary,
        commitments=commitments_u,
        constraints=constraints_u,
        unresolved=unresolved_u,
        source_message_count=len(lines),
        artifact_hash=f"ctxsum:{digest}",
    )
