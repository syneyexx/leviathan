#!/usr/bin/env python3
"""Search and read markdown/text catalogs packaged inside a HADES plugin."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}


def iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name.upper() in {"README", "LICENSE", "AGENTS.MD"}:
            yield path


def list_entries(limit: int = 100) -> list[dict]:
    rows = []
    for path in sorted(iter_files(ROOT)):
        rel = path.relative_to(ROOT).as_posix()
        rows.append({"path": rel, "bytes": path.stat().st_size})
        if len(rows) >= limit:
            break
    return rows


def search(query: str, limit: int = 20) -> list[dict]:
    needle = query.strip().lower()
    if not needle:
        raise SystemExit("query is required")
    hits: list[dict] = []
    for path in iter_files(ROOT):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lowered = text.lower()
        if needle not in lowered and needle not in path.as_posix().lower():
            continue
        idx = lowered.find(needle)
        start = max(0, idx - 80)
        end = min(len(text), idx + len(needle) + 160)
        snippet = re.sub(r"\s+", " ", text[start:end]).strip()
        hits.append({"path": path.relative_to(ROOT).as_posix(), "snippet": snippet})
        if len(hits) >= limit:
            break
    return hits


def read_path(relative: str, max_chars: int = 12000) -> dict:
    candidate = (ROOT / relative).resolve()
    if not str(candidate).startswith(str(ROOT)) or not candidate.is_file():
        raise SystemExit(f"file not found inside plugin: {relative}")
    text = candidate.read_text(encoding="utf-8", errors="ignore")
    truncated = len(text) > max_chars
    return {
        "path": relative,
        "truncated": truncated,
        "content": text[:max_chars],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES catalog bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List catalog files")
    p_list.add_argument("--limit", type=int, default=100)

    p_search = sub.add_parser("search", help="Search catalog text")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=20)

    p_read = sub.add_parser("read", help="Read one catalog file")
    p_read.add_argument("--path", required=True)
    p_read.add_argument("--max-chars", type=int, default=12000)

    args = parser.parse_args()
    if args.cmd == "list":
        payload = {"entries": list_entries(args.limit), "root": str(ROOT)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["entries"] else 2
    if args.cmd == "search":
        hits = search(args.query, args.limit)
        payload = {"query": args.query, "hits": hits, "count": len(hits), "ok": bool(hits)}
        if not hits:
            payload["error"] = "no_catalog_hits"
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if hits else 2
    payload = read_path(args.path, args.max_chars)
    content = str(payload.get("content") or "")
    if not content.strip():
        payload = {**payload, "ok": False, "error": "catalog content empty or unreadable"}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
