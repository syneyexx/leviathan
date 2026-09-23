"""Semantic conversation compaction — derived summaries, never destructive (U065–U066).

Dutch is first-class. English keyword matching is not the sole semantic representation.
Hard constraints survive compaction as authoritative derived artifacts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


# Multilingual constraint cues — Dutch first-class alongside English.
CONSTRAINT_PATTERNS = (
    # Dutch
    re.compile(
        r"\b(moet|moeten|nooit|altijd|uitsluitend|alleen|verplicht|verboden|"
        r"niet\s+(?:wijzigen|veranderen|aanpassen|schrijven|verwijderen)|"
        r"gebruik\s+uitsluitend|blijf\s+binnen|binnen\s+de\s+projectmap)\b",
        re.I,
    ),
    # English
    re.compile(r"\b(must|shall|never|always|do not|don't|required|constraint|only)\b", re.I),
    re.compile(r"\b(prefer|preference|remember that)\b", re.I),
)

HARD_CONSTRAINT_PATTERNS = (
    re.compile(
        r"(gebruik\s+uitsluitend\s+[^.!?\n]+|"
        r"wijzig\s+nooit\s+[^.!?\n]+|"
        r"never\s+(?:modify|change|write|delete|share)\s+[^.!?\n]+|"
        r"must\s+(?:never|always|only)\s+[^.!?\n]+|"
        r"do\s+not\s+(?:modify|change|write|delete)\s+[^.!?\n]+)",
        re.I,
    ),
)

COMMITMENT_PATTERNS = (
    re.compile(r"\b(ik\s+zal|we\s+zullen|afgesproken|besloten)\b", re.I),
    re.compile(r"\b(will |i'll |we will |decided|i will )\b", re.I),
)

# Rhetorical / resolved question markers — do NOT permanently pin these as unresolved.
_RESOLVED_OR_RHETORICAL = re.compile(
    r"(\?$)|(\?\s*$)",
)
_NOT_UNRESOLVED = re.compile(
    r"\b(rhetorical|voorbeeld|example|right\?|toch\?|hè\?|hé\?)\b",
    re.I,
)


@dataclass(frozen=True)
class CompactionResult:
    summary: str
    commitments: tuple[str, ...]
    constraints: tuple[str, ...]
    hard_constraints: tuple[str, ...]
    unresolved: tuple[str, ...]
    decisions: tuple[str, ...]
    source_message_count: int
    artifact_hash: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "commitments": list(self.commitments),
            "constraints": list(self.constraints),
            "hard_constraints": list(self.hard_constraints),
            "unresolved": list(self.unresolved),
            "decisions": list(self.decisions),
            "source_message_count": self.source_message_count,
            "artifact_hash": self.artifact_hash,
            "truth": {
                "summary_is_derived_artifact": True,
                "does_not_replace_canonical_history": True,
                "dutch_is_first_class": True,
                "hard_constraints_remain_authoritative": True,
                "not_every_question_mark_is_unresolved": True,
            },
        }


def extract_hard_constraints(text: str) -> list[str]:
    """Pull hard constraint spans from free text (Dutch + English)."""
    found: list[str] = []
    for pattern in HARD_CONSTRAINT_PATTERNS:
        for match in pattern.finditer(text or ""):
            span = match.group(0).strip().rstrip(".")
            if span:
                found.append(span[:240])
    return found


def compact_conversation(
    history: list[dict[str, str]],
    *,
    max_summary_chars: int = 1200,
) -> CompactionResult:
    """Extract commitments/constraints from history without deleting originals."""
    commitments: list[str] = []
    constraints: list[str] = []
    hard_constraints: list[str] = []
    unresolved: list[str] = []
    decisions: list[str] = []
    lines: list[str] = []
    for item in history:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if not content or role not in {"user", "assistant"}:
            continue
        lines.append(f"{role}: {content}")

        # Hard constraints from any role (user constraints are authoritative).
        for hc in extract_hard_constraints(content):
            hard_constraints.append(hc)
            constraints.append(hc)

        for pattern in CONSTRAINT_PATTERNS:
            if pattern.search(content):
                constraints.append(content[:240])
                break

        if role == "user" and "?" in content:
            # Only treat as unresolved when it looks like a real open question,
            # not every sentence containing '?'.
            if not _NOT_UNRESOLVED.search(content) and content.rstrip().endswith("?"):
                # Skip very short confirmations / tag questions.
                words = content.replace("?", "").split()
                if len(words) >= 4:
                    unresolved.append(content[:240])

        if role == "assistant":
            if any(p.search(content) for p in COMMITMENT_PATTERNS):
                commitments.append(content[:240])
            if re.search(r"\b(besloten|decided|we\s+choose|we\s+chose|keuze:)\b", content, re.I):
                decisions.append(content[:240])

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
    hard_u = uniq(hard_constraints)
    # Ensure every hard constraint is also listed under constraints.
    for hc in hard_u:
        if hc.lower() not in {c.lower() for c in constraints_u}:
            constraints_u = constraints_u + (hc,)
    commitments_u = uniq(commitments)
    unresolved_u = uniq(unresolved)[-5:]
    decisions_u = uniq(decisions)[-5:]
    parts = [
        "COMPACTED CONTEXT (derived — originals retained)",
        f"hard_constraints({len(hard_u)}): " + " | ".join(hard_u) if hard_u else "hard_constraints: none",
        f"constraints({len(constraints_u)}): " + " | ".join(constraints_u) if constraints_u else "constraints: none",
        f"commitments({len(commitments_u)}): " + " | ".join(commitments_u) if commitments_u else "commitments: none",
        f"decisions({len(decisions_u)}): " + " | ".join(decisions_u) if decisions_u else "decisions: none",
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
        hard_constraints=hard_u,
        unresolved=unresolved_u,
        decisions=decisions_u,
        source_message_count=len(lines),
        artifact_hash=f"ctxsum:{digest}",
    )
