#!/usr/bin/env python3
"""Import/symbol graph for HADES coding agents (Graft-inspired, stdlib only)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target"}
PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
JS_IMPORT = re.compile(r"""(?:import\s+(?:.+?\s+from\s+)?|require\()\s*['\"]([^'\"]+)['\"]""", re.M)


def _iter_files(root: Path, limit: int) -> list[Path]:
    rows = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs"}:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rows.append(path)
        if len(rows) >= limit:
            break
    return rows


def _edges(path: Path, text: str) -> list[str]:
    if path.suffix.lower() == ".py":
        found = []
        for match in PY_IMPORT.finditer(text):
            found.append(match.group(1) or match.group(2))
        return found
    return JS_IMPORT.findall(text)


def index_root(root: str, output: str, limit: int) -> dict:
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        return {"ok": False, "error": "root_not_found", "root": str(base)}
    graph: dict[str, list[str]] = {}
    for path in _iter_files(base, limit):
        rel = path.relative_to(base).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        graph[rel] = sorted(set(_edges(path, text)))
    dest = Path(output).expanduser() if output else Path("graft-graph.json")
    dest.write_text(json.dumps({"root": str(base), "nodes": len(graph), "graph": graph}, indent=2), encoding="utf-8")
    return {"ok": True, "root": str(base), "nodes": len(graph), "output": str(dest.resolve())}


def _load(graph_path: str) -> dict:
    path = Path(graph_path).expanduser()
    if not path.is_file():
        return {"ok": False, "error": "graph_missing", "hint": "Run index first.", "path": str(path)}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"ok": True, "data": data, "path": str(path)}


def neighbors(graph_path: str, file: str, limit: int) -> dict:
    loaded = _load(graph_path)
    if not loaded.get("ok"):
        return loaded
    graph = loaded["data"].get("graph") or {}
    key = file.replace("\\", "/")
    if key not in graph:
        matches = [name for name in graph if key in name]
        if not matches:
            return {"ok": False, "error": "file_not_in_graph", "file": file}
        key = matches[0]
    inbound = [name for name, edges in graph.items() if key in edges or Path(key).stem in " ".join(edges)]
    return {
        "ok": True,
        "file": key,
        "imports": graph.get(key, [])[:limit],
        "imported_by": inbound[:limit],
    }


def search(graph_path: str, query: str, limit: int) -> dict:
    loaded = _load(graph_path)
    if not loaded.get("ok"):
        return loaded
    needle = query.strip().lower()
    if not needle:
        return {"ok": False, "error": "query_required"}
    graph = loaded["data"].get("graph") or {}
    hits = []
    for name, edges in graph.items():
        blob = f"{name} {' '.join(edges)}".lower()
        if needle in blob:
            hits.append({"file": name, "imports": edges[:12]})
        if len(hits) >= limit:
            break
    return {"ok": bool(hits), "query": query, "count": len(hits), "hits": hits, **({} if hits else {"error": "no_hits"})}


def doctor() -> dict:
    return {"ok": True, "python": sys.executable, "notes": ["Builds a local import graph. No Graft cloud service."]}


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES graft graph")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    idx = sub.add_parser("index")
    idx.add_argument("--root", required=True)
    idx.add_argument("--output", default="graft-graph.json")
    idx.add_argument("--limit", type=int, default=4000)
    n = sub.add_parser("neighbors")
    n.add_argument("--graph", default="graft-graph.json")
    n.add_argument("--file", required=True)
    n.add_argument("--limit", type=int, default=40)
    s = sub.add_parser("search")
    s.add_argument("--graph", default="graft-graph.json")
    s.add_argument("--query", required=True)
    s.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    elif args.cmd == "index":
        payload = index_root(args.root, args.output, args.limit)
    elif args.cmd == "neighbors":
        payload = neighbors(args.graph, args.file, args.limit)
    else:
        payload = search(args.graph, args.query, args.limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.cmd == "search":
        return 0 if payload.get("ok") else 2
    return 0 if payload.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
