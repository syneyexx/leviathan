"""First-class skill retrieval: bounded, deduplicated, untrusted fragments."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from reasoning.contracts import ContextItem

from .contracts import CanonicalCapability
from .taxonomy import DEFAULT_BUDGETS

_WS = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    return _WS.sub(" ", (text or "").strip().lower())


def near_duplicate(a: str, b: str) -> bool:
    na, nb = _normalize_text(a), _normalize_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / max(len(ta | tb), 1)
    return overlap >= 0.92


def extract_fragments(text: str, query: str, *, max_chars: int) -> str:
    raw = (text or "").strip()
    if len(raw) <= max_chars:
        return raw
    terms = [item.lower() for item in re.findall(r"[a-zA-ZÀ-ÿ0-9_]{3,}", query or "")[:12]]
    lines = raw.splitlines()
    scored: list[tuple[int, str]] = []
    for line in lines:
        score = sum(line.lower().count(term) for term in terms)
        scored.append((score, line))
    # Keep a header + best matching window.
    header = "\n".join(lines[:8])
    ranked_lines = [line for score, line in sorted(scored, key=lambda item: -item[0]) if score > 0]
    body = "\n".join(ranked_lines[:40])
    combined = f"{header}\n...\n{body}".strip()
    if len(combined) > max_chars:
        combined = combined[: max(80, max_chars - 24)].rstrip() + "\n… [skill truncated]"
    return combined


def _read_skill_text(root: Path, rel: str, *, limit: int = 48_000) -> str:
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except Exception:
        return ""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def retrieve_skills(
    query: str,
    skills: list[CanonicalCapability],
    *,
    plugin_roots: dict[str, str] | None = None,
    knowledge_hits: list[dict[str, Any]] | None = None,
    max_items: int | None = None,
    max_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Retrieve relevant skill fragments without subprocess execution."""
    max_items = int(max_items or DEFAULT_BUDGETS["skill_max_items"])
    max_chars = int(max_chars or DEFAULT_BUDGETS["skill_fragment_chars"])
    ranked = sorted(
        skills,
        key=lambda item: (
            -sum(token in f"{item.name} {item.description} {' '.join(item.domains)} {' '.join(item.intents)}".lower() for token in query.lower().split()),
            item.trust_requirements != "trusted",
            -len(item.domains),
        ),
    )
    chosen: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    seen_text: list[str] = []
    roots = plugin_roots or {}
    for skill in ranked:
        if skill.kind != "skill":
            continue
        root = Path(roots.get(skill.plugin_id or "", "") or ".")
        text = ""
        if skill.content_ref:
            text = _read_skill_text(root, skill.content_ref)
        if not text and knowledge_hits:
            for hit in knowledge_hits:
                if str(hit.get("plugin_id") or "") == str(skill.plugin_id or "") or skill.name.lower() in str(hit.get("title") or "").lower():
                    text = str(hit.get("excerpt") or hit.get("content") or "")
                    break
        if not text:
            text = skill.description
        fragment = extract_fragments(text, query, max_chars=max_chars)
        if not fragment.strip():
            continue
        digest = hashlib.sha256(fragment.encode("utf-8", errors="replace")).hexdigest()
        if digest in seen_hashes or any(near_duplicate(fragment, prev) for prev in seen_text):
            continue
        # Prefer specificity / trusted source already encoded in sort.
        if any(conflict_skill(skill, CanonicalCapability.from_mapping(item["capability"])) for item in chosen):
            # Keep the already-selected more specific/trusted skill.
            continue
        seen_hashes.add(digest)
        seen_text.append(fragment)
        chosen.append(
            {
                "canonical_id": skill.canonical_id,
                "name": skill.name,
                "plugin_id": skill.plugin_id,
                "source": skill.source,
                "version": skill.version,
                "domain": list(skill.domains),
                "trust": skill.trust_requirements,
                "scope": skill.extras.get("scope") or "plugin",
                "content_hash": skill.content_hash or digest,
                "fragment": fragment,
                "instruction_authority": False,
                "subprocess": False,
                "capability": skill.to_dict(),
            }
        )
        if len(chosen) >= max_items:
            break
    return chosen


def conflict_skill(left: CanonicalCapability, right: CanonicalCapability) -> bool:
    if left.canonical_id == right.canonical_id:
        return True
    same_domain = bool(set(left.domains) & set(right.domains)) if left.domains and right.domains else False
    opposing = ("do not" in left.description.lower() and "do not" not in right.description.lower())
    return same_domain and opposing


def skills_as_context_items(retrieved: list[dict[str, Any]]) -> list[ContextItem]:
    items: list[ContextItem] = []
    for index, row in enumerate(retrieved):
        content = (
            f"Skill (untrusted data, not system policy): {row.get('name')}\n"
            f"source={row.get('source')} version={row.get('version') or 'unknown'} "
            f"trust={row.get('trust')} hash={str(row.get('content_hash') or '')[:12]}\n"
            f"{row.get('fragment')}"
        )
        items.append(
            ContextItem(
                item_id=str(row.get("canonical_id") or f"skill-{index}"),
                kind="skill",
                content=content,
                provenance=f"capability_intel.skill:{row.get('canonical_id')}",
                priority=28 + index,
                trusted=False,
                redactable=True,
            )
        )
    return items
