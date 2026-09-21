#!/usr/bin/env python3
"""Local codebase memory for HADES: index + query without the upstream C MCP binary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".hades",
    "target",
    ".next",
    ".turbo",
}
TEXT_SUFFIXES = {
    ".py",
    ".pyw",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".cpp",
    ".cc",
    ".c",
    ".h",
    ".hpp",
    ".rb",
    ".php",
    ".swift",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".sql",
}
SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|fn|func|interface|type|struct|enum)\s+([A-Za-z_][\w]*)",
    re.M,
)


def _db_path(path: str) -> Path:
    target = Path(path).expanduser() if path else Path("codebase-memory.sqlite")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path(path)))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            sha TEXT NOT NULL,
            bytes INTEGER NOT NULL,
            language TEXT NOT NULL,
            symbols TEXT NOT NULL,
            preview TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(path, symbols, preview)")
    return conn


def _language(path: Path) -> str:
    return path.suffix.lower().lstrip(".") or "text"


def _iter_files(root: Path, limit: int) -> list[Path]:
    rows: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > 1_500_000:
                continue
        except OSError:
            continue
        rows.append(path)
        if len(rows) >= limit:
            break
    return rows


def index_root(root: str, db: str, limit: int) -> dict:
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        return {"ok": False, "error": "root_not_found", "root": str(base)}
    conn = _connect(db)
    indexed = 0
    symbols_total = 0
    conn.execute("DELETE FROM files")
    try:
        conn.execute("DELETE FROM files_fts")
    except sqlite3.OperationalError:
        pass
    for path in _iter_files(base, limit):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(base).as_posix()
        symbols = SYMBOL_RE.findall(text)
        sha = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        preview = "\n".join(text.splitlines()[:40])[:4000]
        conn.execute(
            "INSERT OR REPLACE INTO files(path, sha, bytes, language, symbols, preview) VALUES (?,?,?,?,?,?)",
            (rel, sha, len(text.encode("utf-8", errors="replace")), _language(path), json.dumps(symbols), preview),
        )
        conn.execute(
            "INSERT INTO files_fts(path, symbols, preview) VALUES (?,?,?)",
            (rel, " ".join(symbols), preview),
        )
        indexed += 1
        symbols_total += len(symbols)
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "root": str(base),
        "db": str(_db_path(db).resolve()),
        "files": indexed,
        "symbols": symbols_total,
        "note": "HADES-native lexical/symbol index. Upstream C MCP is optional and not required.",
    }


def query_index(db: str, query: str, limit: int) -> dict:
    needle = query.strip()
    if not needle:
        return {"ok": False, "error": "query_required"}
    path = _db_path(db)
    if not path.is_file():
        return {"ok": False, "error": "index_missing", "hint": "Run index first.", "db": str(path)}
    conn = sqlite3.connect(str(path))
    hits = []
    try:
        rows = conn.execute(
            "SELECT path, snippet(files_fts, 2, '[', ']', '…', 18) FROM files_fts WHERE files_fts MATCH ? LIMIT ?",
            (needle, limit),
        ).fetchall()
        for path_rel, snippet in rows:
            hits.append({"path": path_rel, "snippet": snippet})
    except sqlite3.OperationalError:
        like = f"%{needle.lower()}%"
        rows = conn.execute(
            "SELECT path, symbols, preview FROM files WHERE lower(path) LIKE ? OR lower(symbols) LIKE ? OR lower(preview) LIKE ? LIMIT ?",
            (like, like, like, limit),
        ).fetchall()
        for path_rel, symbols, preview in rows:
            hits.append({"path": path_rel, "symbols": json.loads(symbols), "snippet": preview[:240]})
    conn.close()
    return {"ok": bool(hits), "query": needle, "count": len(hits), "hits": hits, **({} if hits else {"error": "no_hits"})}


def outline(root: str, limit: int) -> dict:
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        return {"ok": False, "error": "root_not_found", "root": str(base)}
    files = _iter_files(base, limit)
    return {
        "ok": True,
        "root": str(base),
        "count": len(files),
        "files": [path.relative_to(base).as_posix() for path in files],
    }


def doctor() -> dict:
    return {
        "ok": True,
        "python": sys.executable,
        "cwd": os.getcwd(),
        "sqlite": sqlite3.sqlite_version,
        "notes": [
            "Indexes local source into SQLite FTS (no network).",
            "Does not require the upstream C MCP binary.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES codebase memory")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    idx = sub.add_parser("index")
    idx.add_argument("--root", required=True)
    idx.add_argument("--db", default="codebase-memory.sqlite")
    idx.add_argument("--limit", type=int, default=4000)
    q = sub.add_parser("query")
    q.add_argument("--query", required=True)
    q.add_argument("--db", default="codebase-memory.sqlite")
    q.add_argument("--limit", type=int, default=20)
    o = sub.add_parser("outline")
    o.add_argument("--root", required=True)
    o.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    elif args.cmd == "index":
        payload = index_root(args.root, args.db, args.limit)
    elif args.cmd == "query":
        payload = query_index(args.db, args.query, args.limit)
    else:
        payload = outline(args.root, args.limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.cmd == "query":
        return 0 if payload.get("ok") else 2
    return 0 if payload.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
