"""Coding-specific context assembly: ranked tiers, hash cache, deterministic dedupe.

Never drops current requirements, constraints, unresolved failures, or the current diff.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from path_boundary import join_within_root

TIER_TASK = 0
TIER_DIRECT = 1
TIER_DEPS = 2
TIER_TESTS = 3
TIER_ARCH = 4
TIER_HISTORY = 5

PROTECTED_TIERS = {TIER_TASK}

MAX_CACHE_ENTRIES = 400
MAX_BLOB_CHARS = 6000


@dataclass
class ContextItem:
    path: str
    tier: int
    score: float
    reason: str
    content: str = ""
    content_hash: str = ""
    start_line: int | None = None
    end_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "tier": self.tier,
            "score": self.score,
            "reason": self.reason,
            "content_hash": self.content_hash,
            "chars": len(self.content),
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


class ContentCache:
    """Hash-keyed reusable representations. Bounded; invalidated by content hash."""

    def __init__(self, *, max_entries: int = MAX_CACHE_ENTRIES) -> None:
        self.max_entries = max_entries
        self._store: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, content_hash: str) -> dict[str, Any] | None:
        item = self._store.get(content_hash)
        if item is None:
            self.misses += 1
            return None
        self.hits += 1
        return item

    def put(self, content_hash: str, payload: dict[str, Any]) -> None:
        if not content_hash:
            return
        if len(self._store) >= self.max_entries:
            # Drop oldest insertion (dict preserves order).
            self._store.pop(next(iter(self._store)), None)
        self._store[content_hash] = payload

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": len(self._store),
            "hit_rate": (self.hits / total) if total else 0.0,
        }


_CACHE = ContentCache()


def file_summary(rel: str, text: str, *, symbols: list[dict[str, Any]] | None = None) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cached = _CACHE.get(digest)
    if cached and cached.get("summary"):
        return str(cached["summary"])
    names = [str(s.get("name")) for s in (symbols or []) if s.get("name")]
    lines = text.splitlines()
    head = "\n".join(lines[:40])
    summary = f"{rel} symbols={','.join(names[:12])} lines={len(lines)}\n{head}"
    _CACHE.put(digest, {"summary": summary, "path": rel})
    return summary


def score_context_item(
    *,
    rel: str,
    goal_tokens: list[str],
    direct: set[str],
    deps: set[str],
    tests: set[str],
    stack_files: set[str],
    recent: set[str],
    user_selected: set[str],
    requirement_hits: set[str],
) -> tuple[int, float, str]:
    reasons: list[str] = []
    score = 0.0
    if rel in user_selected:
        score += 8
        reasons.append("user_selected")
    if rel in stack_files:
        score += 7
        reasons.append("stack")
    if rel in direct:
        score += 6
        reasons.append("direct")
    if rel in requirement_hits:
        score += 5
        reasons.append("requirement")
    if rel in tests:
        score += 4
        reasons.append("test")
    if rel in deps:
        score += 3
        reasons.append("dependency")
    if rel in recent:
        score += 2
        reasons.append("recent")
    name = rel.lower()
    if any(tok in name for tok in goal_tokens):
        score += 1.5
        reasons.append("name_token")
    if rel in stack_files or rel in user_selected or rel in direct:
        tier = TIER_DIRECT
    elif rel in deps:
        tier = TIER_DEPS
    elif rel in tests:
        tier = TIER_TESTS
    elif score >= 1.5:
        tier = TIER_ARCH
    else:
        tier = TIER_HISTORY
    return tier, score, ",".join(reasons) or "weak"


def assemble_coding_context(
    *,
    root: Path,
    task_contract: dict[str, Any],
    files: list[str],
    index: dict[str, Any] | None = None,
    failures: list[dict[str, Any]] | None = None,
    diff_text: str = "",
    recent_edits: list[str] | None = None,
    user_selected: list[str] | None = None,
    budget_chars: int = 24_000,
) -> dict[str, Any]:
    """Rank and pack context. Compress lower tiers first under pressure."""
    from repo_intelligence import neighbors, tests_covering

    root = Path(root)
    idx = index or {"files": {}, "edges": []}
    goal = str(task_contract.get("goal") or "")
    tokens = [t.lower() for t in goal.replace("/", " ").split() if len(t) > 2]
    direct = set(files)
    stack_files = {str(f.get("file") or "") for f in (failures or []) if f.get("file")}
    stack_files |= {str(f.get("probable_owner") or "") for f in (failures or []) if f.get("probable_owner")}
    deps: set[str] = set()
    tests: set[str] = set()
    for rel in list(direct)[:20]:
        deps.update(neighbors(idx, rel, kinds=["imports", "calls", "implements"], depth=1))
        tests.update(tests_covering(idx, [rel]))
    tests.update(tests_covering(idx, list(direct)))
    recent = set(recent_edits or [])
    selected = set(user_selected or [])
    req_hits: set[str] = set()
    for row in task_contract.get("requirements") or []:
        if isinstance(row, dict):
            req_hits.update(str(p) for p in (row.get("changed_files") or row.get("files") or []) if p)
            text = str(row.get("text") or row.get("requirement") or "").lower()
            for rel in (idx.get("files") or {}):
                if Path(rel).stem.lower() in text:
                    req_hits.add(rel)

    candidates = list(dict.fromkeys([*direct, *stack_files, *deps, *tests, *recent, *selected, *req_hits]))
    items: list[ContextItem] = []
    seen_hash: set[str] = set()
    for rel in candidates:
        if not rel:
            continue
        try:
            path = join_within_root(root, rel)
            text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        except (OSError, ValueError):
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
        if digest and digest in seen_hash:
            continue
        if digest:
            seen_hash.add(digest)
        meta = (idx.get("files") or {}).get(rel) or {}
        tier, score, reason = score_context_item(
            rel=rel,
            goal_tokens=tokens,
            direct=direct,
            deps=deps,
            tests=tests,
            stack_files=stack_files,
            recent=recent,
            user_selected=selected,
            requirement_hits=req_hits,
        )
        summary = file_summary(rel, text, symbols=meta.get("symbols") or [])
        content = text if tier <= TIER_DIRECT else summary
        if len(content) > MAX_BLOB_CHARS:
            content = content[:MAX_BLOB_CHARS]
        items.append(
            ContextItem(path=rel, tier=tier, score=score, reason=reason, content=content, content_hash=digest)
        )
    items.sort(key=lambda i: (i.tier, -i.score, i.path))

    # Always include the task contract and failures/diff as tier 0.
    pinned = _tier0_blob(task_contract, failures or [], diff_text)
    packed: list[ContextItem] = []
    used = len(pinned)
    dropped: list[str] = []
    for item in items:
        add = len(item.content) + 80
        if used + add > budget_chars and item.tier not in PROTECTED_TIERS and item.tier > TIER_DIRECT:
            dropped.append(item.path)
            continue
        if used + add > budget_chars and item.tier >= TIER_DEPS:
            # Compress to summary only.
            item.content = item.content[:800]
            add = len(item.content) + 80
            if used + add > budget_chars:
                dropped.append(item.path)
                continue
        packed.append(item)
        used += add

    prompt = pinned + "\n".join(
        f"\n### TIER {item.tier} {item.path} ({item.reason})\n{item.content}" for item in packed
    )
    return {
        "prompt": prompt,
        "items": [i.to_dict() for i in packed],
        "dropped": dropped,
        "chars": used,
        "budget_chars": budget_chars,
        "cache": _CACHE.stats(),
        "deduped": True,
        "protected_kept": ["task_contract", "failures", "diff", "direct_code"],
    }


def _tier0_blob(contract: dict[str, Any], failures: list[dict[str, Any]], diff_text: str) -> str:
    slim_failures = [
        {
            "type": f.get("failure_type"),
            "file": f.get("file"),
            "line": f.get("line"),
            "symbol": f.get("symbol"),
            "message": f.get("message"),
            "owner": f.get("probable_owner"),
        }
        for f in failures[:8]
    ]
    payload = {
        "task_id": contract.get("task_id"),
        "goal": contract.get("goal"),
        "requirements": contract.get("requirements"),
        "acceptance_criteria": contract.get("acceptance_criteria"),
        "constraints": contract.get("constraints"),
        "non_goals": contract.get("non_goals"),
        "unknowns": contract.get("unknowns"),
        "protected_paths": contract.get("protected_paths"),
    }
    parts = ["### TIER 0 task_contract\n", json.dumps(payload, ensure_ascii=False, indent=2)[:8000], "\n"]
    if slim_failures:
        parts.append("### TIER 0 unresolved_failures\n")
        parts.append(json.dumps(slim_failures, ensure_ascii=False, indent=2)[:4000])
        parts.append("\n")
    if diff_text.strip():
        parts.append("### TIER 0 current_diff\n")
        parts.append(diff_text[:8000])
        parts.append("\n")
    return "".join(parts)
