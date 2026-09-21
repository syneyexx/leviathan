"""LSP-light: go-to-definition / find-references via the regex symbol index.

Not a full language server — honest local navigation without an LSP plugin.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from workspace_symbols import (
    CODE_EXTENSIONS,
    SKIP_DIRS,
    _path_within_root,
    extract_symbols_from_text,
    index_workspace_symbols,
)


def find_definition(root: Path, symbol_name: str, *, limit: int = 40) -> dict[str, Any]:
    name = (symbol_name or "").strip()
    if not name:
        raise ValueError("symbol_name is verplicht.")
    indexed = index_workspace_symbols(root, query=name, limit=max(limit * 3, 80), use_cache=True)
    exact = [item for item in indexed["symbols"] if item["name"] == name]
    fuzzy = [item for item in indexed["symbols"] if name.lower() in item["name"].lower() and item not in exact]
    defs = (exact + fuzzy)[:limit]
    return {
        "root": str(Path(root).resolve()),
        "symbol": name,
        "definitions": defs,
        "count": len(defs),
        "files_scanned": indexed["files_scanned"],
        "mode": "regex-index",
        "from_cache": bool(indexed.get("from_cache")),
        "note": "LSP-light gebruikt geen language server; resultaten zijn regex-gebaseerd.",
    }


def find_references(root: Path, symbol_name: str, *, limit: int = 80) -> dict[str, Any]:
    name = (symbol_name or "").strip()
    if not name:
        raise ValueError("symbol_name is verplicht.")
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    # Word-boundary-ish match to reduce substring noise (add vs additional).
    pattern = re.compile(rf"(?<![\w]){re.escape(name)}(?![\w])")
    refs: list[dict[str, Any]] = []
    files_scanned = 0
    for path in root.rglob("*"):
        if files_scanned >= 400 or len(refs) >= limit:
            break
        if not path.is_file() or path.suffix.lower() not in CODE_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not _path_within_root(path, root):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files_scanned += 1
        rel = str(path.relative_to(root)).replace("\\", "/")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not pattern.search(line):
                continue
            kind = "reference"
            # Prefer marking definition-like lines distinctly when the symbol index would.
            stripped = line.strip()
            if stripped.startswith("def ") or stripped.startswith("class ") or "function " in stripped:
                kind = "definition_or_reference"
            refs.append(
                {
                    "name": name,
                    "kind": kind,
                    "path": rel,
                    "line": lineno,
                    "snippet": stripped[:240],
                }
            )
            if len(refs) >= limit:
                break
    return {
        "root": str(root),
        "symbol": name,
        "references": refs,
        "count": len(refs),
        "files_scanned": files_scanned,
        "mode": "text-scan-word-boundary",
        "note": "Referenties zijn woordgrens-tekstmatches, geen type-aware LSP-resolutie.",
        "truncated": len(refs) >= limit,
    }


def outline_file(path: Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    symbols = extract_symbols_from_text(path.name, text, limit=200)
    for item in symbols:
        item["path"] = str(path)
    return {"path": str(path), "symbols": symbols, "count": len(symbols), "mode": "regex-index"}
