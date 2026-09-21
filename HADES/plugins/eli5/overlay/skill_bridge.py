#!/usr/bin/env python3
"""List and read agent-skill style packages for HADES plugin tools."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
SKILL_NAMES = {"skill.md", "skills.md", "agents.md", "claude.md", "readme.md"}


def iter_skill_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        name = path.name.lower()
        if name in SKILL_NAMES or path.parent.name.lower() in {"skills", "skill", "agents", "commands"}:
            if path.suffix.lower() in {".md", ".mdc", ".txt", ".json", ".yaml", ".yml"} or name in SKILL_NAMES:
                yield path


def skill_id(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    return rel.replace("/", "::")


def list_skills(limit: int = 200) -> list[dict]:
    rows = []
    for path in sorted(iter_skill_files(ROOT)):
        rel = path.relative_to(ROOT).as_posix()
        title = path.stem
        try:
            first = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in first[:20]:
                if line.strip().startswith("#"):
                    title = line.lstrip("#").strip() or title
                    break
        except OSError:
            pass
        rows.append({"id": skill_id(path), "path": rel, "title": title})
        if len(rows) >= limit:
            break
    return rows


def _skill_payload(path: Path, max_chars: int) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "id": skill_id(path),
        "path": path.relative_to(ROOT).as_posix(),
        "truncated": len(text) > max_chars,
        "content": text[:max_chars],
    }


def get_skill(skill: str, max_chars: int = 16000) -> dict:
    needle = skill.strip()
    paths = list(iter_skill_files(ROOT))
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        if needle in {skill_id(path), rel, path.stem, path.name}:
            return _skill_payload(path, max_chars)

    # Prefer SKILL.md whose parent directory matches the requested skill id.
    lowered = needle.lower().replace("\\", "/").rstrip("/")
    preferred: list[Path] = []
    fuzzy: list[Path] = []
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        parent = path.parent.name.lower()
        if lowered in {parent, rel.lower(), path.stem.lower()} or lowered in rel.lower():
            if path.name.lower() == "skill.md" and (parent == lowered or f"/{lowered}/" in f"/{rel.lower()}/"):
                preferred.append(path)
            else:
                fuzzy.append(path)
    for path in preferred + fuzzy:
        return _skill_payload(path, max_chars)
    raise SystemExit(f"skill not found: {skill}")


def search_skills(query: str, limit: int = 20) -> list[dict]:
    needle = query.strip().lower()
    if not needle:
        raise SystemExit("query is required")
    hits = []
    for path in iter_skill_files(ROOT):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if needle not in text.lower() and needle not in path.as_posix().lower():
            continue
        idx = text.lower().find(needle)
        start = max(0, idx - 60)
        end = min(len(text), idx + len(needle) + 140)
        snippet = re.sub(r"\s+", " ", text[start:end]).strip()
        hits.append({"id": skill_id(path), "path": path.relative_to(ROOT).as_posix(), "snippet": snippet})
        if len(hits) >= limit:
            break
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES skill bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--limit", type=int, default=200)

    p_get = sub.add_parser("get")
    p_get.add_argument("--skill", required=True)
    p_get.add_argument("--max-chars", type=int, default=16000)

    p_search = sub.add_parser("search")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    if args.cmd == "list":
        payload = {"skills": list_skills(args.limit), "count": None}
        payload["count"] = len(payload["skills"])
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        # Empty skill package is not a successful catalog list for autonomous tools.
        return 0 if payload["count"] else 2
    if args.cmd == "get":
        payload = get_skill(args.skill, args.max_chars)
        content = str(payload.get("content") or "")
        if not content.strip():
            payload = {**payload, "ok": False, "error": "skill content empty or unreadable"}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    hits = search_skills(args.query, args.limit)
    payload = {"query": args.query, "hits": hits, "count": len(hits), "ok": bool(hits)}
    if not hits:
        payload["error"] = "no_skill_hits"
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # Empty search is not a successful retrieval for autonomous tools.
    return 0 if hits else 2


if __name__ == "__main__":
    raise SystemExit(main())
