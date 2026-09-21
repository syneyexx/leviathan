"""Parse @-mentions from chat messages for budgeted context injection.

Mentions are retrieval hints, not system authority.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

MENTION_RE = re.compile(
    r"@(?P<kind>file|memory|agent|plugin|research|knowledge|task|codebase)\b(?:[:#](?P<ref>[^\s]+))?",
    re.IGNORECASE,
)


def _limit(setting_id: str, fallback: int) -> int | None:
    try:
        from control.service import resolve_setting

        value = resolve_setting(setting_id, default=fallback)
        return None if value is None else int(value)
    except Exception:
        return fallback


def parse_mentions(text: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for match in MENTION_RE.finditer(text or ""):
        kind = match.group("kind").lower()
        ref = (match.group("ref") or "").strip()
        found.append({"kind": kind, "ref": ref, "raw": match.group(0)})
    # Deduplicate while preserving order.
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for item in found:
        key = (item["kind"], item["ref"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def resolve_mention_context(
    mentions: list[dict[str, str]],
    *,
    database: Any,
    platform_db: Any,
    max_chars: int = 12_000,
) -> list[dict[str, Any]]:
    """Return plain context blobs for assemble/retrieval (trusted=False)."""
    items: list[dict[str, Any]] = []
    remaining = max_chars
    for mention in mentions:
        if remaining <= 200:
            break
        kind = mention["kind"]
        ref = mention["ref"]
        content = ""
        provenance = f"mention:{kind}:{ref or '*'}"
        try:
            if kind == "memory":
                mem_limit = _limit("chat.mentions_memory_limit", 40)
                memories = database.list_memories(limit=40 if mem_limit is None else mem_limit)
                if ref:
                    memories = [m for m in memories if ref.lower() in f"{m.get('id','')} {m.get('title','')}".lower()]
                content = "\n\n".join(
                    f"{m.get('title')}: {m.get('summary') or m.get('content')}" for m in memories[:5]
                )
            elif kind in {"knowledge", "file"}:
                query = ref or kind
                matches = platform_db.search_knowledge(query, 6) if hasattr(platform_db, "search_knowledge") else []
                content = "\n\n".join(
                    f"{m.get('title') or m.get('source_id')}: {(m.get('content') or m.get('snippet') or '')[:800]}"
                    for m in matches
                )
            elif kind == "codebase":
                query = ref or ""
                symbol_bits: list[str] = []
                try:
                    from workspace_symbols import index_workspace_symbols

                    workspaces = platform_db.list_workspaces() if hasattr(platform_db, "list_workspaces") else []
                    sym_limit = _limit("chat.mentions_symbols_limit", 20)
                    for workspace in (workspaces or [])[:2]:
                        root = Path(str(workspace.get("path") or ""))
                        if not root.is_dir():
                            continue
                        indexed = index_workspace_symbols(
                            root, query=query, limit=20 if sym_limit is None else sym_limit
                        )
                        for sym in indexed.get("symbols") or []:
                            symbol_bits.append(f"{sym.get('kind')} {sym.get('name')} @ {sym.get('path')}:{sym.get('line')}")
                except Exception as exc:
                    symbol_bits.append(f"Symboolindex niet beschikbaar: {exc}")
                matches = platform_db.search_knowledge(query or "code", 4) if hasattr(platform_db, "search_knowledge") else []
                knowledge_bits = [
                    f"{m.get('title') or m.get('source_id')}: {(m.get('content') or m.get('snippet') or '')[:500]}"
                    for m in matches
                ]
                content = "\n".join(symbol_bits[:20] + knowledge_bits[:4]) or f"Geen codebase-treffers voor {query or '*'}"
                provenance = f"mention:codebase:{ref or '*'}"
            elif kind == "research":
                projects = platform_db.list_research_projects() if hasattr(platform_db, "list_research_projects") else []
                if ref:
                    projects = [p for p in projects if ref.lower() in f"{p.get('id','')} {p.get('title','')} {p.get('topic','')}".lower()]
                content = "\n\n".join(
                    f"{p.get('title')}: {(p.get('findings') or p.get('report') or p.get('topic') or '')[:900]}"
                    for p in projects[:4]
                )
            elif kind == "task":
                tasks = database.list_tasks()[:40]
                if ref:
                    tasks = [t for t in tasks if ref.lower() in f"{t.get('id','')} {t.get('title','')}".lower()]
                content = "\n\n".join(
                    f"{t.get('title')} [{t.get('status')}]: {(t.get('prompt') or '')[:500]}"
                    for t in tasks[:5]
                )
            elif kind == "agent":
                content = f"Gevraagde agent-context: {ref or 'auto'}. Gebruik alleen agents die in de runtime beschikbaar zijn."
            elif kind == "plugin":
                content = f"Gevraagde plugin-context: {ref or 'enabled tools'}. Alleen enabled/Ready tools zijn aanroepbaar."
        except Exception as exc:
            content = f"Mention-resolutie mislukt voor @{kind}: {exc}"
        content = (content or "").strip()
        if not content:
            content = f"Geen lokale treffers voor @{kind}" + (f":{ref}" if ref else "")
        clipped = content[: min(len(content), remaining)]
        remaining -= len(clipped)
        items.append(
            {
                "kind": "mention",
                "mention_kind": kind,
                "ref": ref,
                "content": clipped,
                "provenance": provenance,
                "trusted": False,
            }
        )
    return items
