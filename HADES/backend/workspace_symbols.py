"""Lightweight workspace symbol indexer (regex-based, no language-server required).

Supports an on-disk cache keyed by path/mtime/size so refresh is incremental.
Embeddings are intentionally not required: `@codebase` and Coding Agent search use
symbols + tree + cache. Vector embeddings remain an optional future enhancement.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

SYMBOL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][\w]*)", re.M)),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][\w]*)\s*=\s*(?:async\s*)?\(", re.M)),
    ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_][\w]*)", re.M)),
    ("function", re.compile(r"^\s*def\s+([A-Za-z_][\w]*)\s*\(", re.M)),
    ("class", re.compile(r"^\s*class\s+([A-Za-z_][\w]*)\s*[:\(]", re.M)),
    ("type", re.compile(r"^\s*(?:export\s+)?(?:type|interface)\s+([A-Za-z_][\w]*)", re.M)),
]

CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java"}
SKIP_DIRS = {"node_modules", ".git", ".venv", "dist", "build", "__pycache__", ".tox", ".next", "target"}


def _limit(setting_id: str, fallback: int) -> int | None:
    try:
        from control.service import resolve_setting

        value = resolve_setting(setting_id, default=fallback)
        return None if value is None else int(value)
    except Exception:
        return fallback


def extract_symbols_from_text(path: str, text: str, limit: int | None = None) -> list[dict[str, Any]]:
    if limit is None:
        resolved = _limit("codeindex.symbols_per_file", 80)
        limit = 10_000 if resolved is None else resolved
    symbols: list[dict[str, Any]] = []
    for kind, pattern in SYMBOL_PATTERNS:
        for match in pattern.finditer(text or ""):
            name = match.group(1)
            line = (text[: match.start()].count("\n") + 1) if text else 1
            symbols.append({"name": name, "kind": kind, "path": path, "line": line})
            if len(symbols) >= limit:
                return symbols
    return symbols


def _default_cache_path(root: Path) -> Path:
    return root / ".hades_symbol_index.json"


def _path_within_root(path: Path, root: Path) -> bool:
    """Fail closed when a workspace entry resolves outside the approved root."""
    try:
        resolved_root = root.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        resolved_path.relative_to(resolved_root)
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _file_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))), "size": int(stat.st_size)}


def _iter_code_files(root: Path, *, max_files: int, max_file_bytes: int) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if len(files) >= max_files:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in CODE_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not _path_within_root(path, root):
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                continue
        except OSError:
            continue
        files.append(path)
    return files


def build_tree_summary(root: Path, *, max_entries: int = 40) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    entries: list[dict[str, Any]] = []
    try:
        children = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return {"root": str(root), "entries": [], "truncated": False}
    for child in children:
        if child.name in SKIP_DIRS or child.name.startswith("."):
            continue
        if not _path_within_root(child, root):
            continue
        if child.is_dir():
            file_count = 0
            try:
                for path in child.rglob("*"):
                    if path.is_file() and path.suffix.lower() in CODE_EXTENSIONS:
                        if any(part in SKIP_DIRS for part in path.parts):
                            continue
                        if not _path_within_root(path, root):
                            continue
                        file_count += 1
                        if file_count >= 500:
                            break
            except OSError:
                file_count = 0
            entries.append({"name": child.name, "kind": "dir", "code_files": file_count})
        elif child.suffix.lower() in CODE_EXTENSIONS:
            entries.append({"name": child.name, "kind": "file", "code_files": 1})
        if len(entries) >= max_entries:
            return {"root": str(root), "entries": entries, "truncated": True}
    return {"root": str(root), "entries": entries, "truncated": False}


def load_symbol_cache(cache_path: Path) -> dict[str, Any]:
    if not cache_path.is_file():
        return {"version": 1, "files": {}, "symbols": []}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "files": {}, "symbols": []}
    if not isinstance(payload, dict):
        return {"version": 1, "files": {}, "symbols": []}
    payload.setdefault("version", 1)
    payload.setdefault("files", {})
    payload.setdefault("symbols", [])
    return payload


def save_symbol_cache(cache_path: Path, payload: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache_path)


def refresh_workspace_index(
    root: Path,
    *,
    cache_path: Path | None = None,
    max_files: int | None = None,
    max_file_bytes: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if max_files is None:
        resolved = _limit("codeindex.max_files", 400)
        max_files = 10_000_000 if resolved is None else resolved
    if max_file_bytes is None:
        resolved = _limit("codeindex.max_file_bytes", 400_000)
        max_file_bytes = 10_000_000_000 if resolved is None else resolved
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    cache_file = Path(cache_path) if cache_path else _default_cache_path(root)
    cache = {"version": 1, "files": {}, "symbols": []} if force else load_symbol_cache(cache_file)
    files_map: dict[str, Any] = dict(cache.get("files") or {})
    code_files = _iter_code_files(root, max_files=max_files, max_file_bytes=max_file_bytes)
    live_relpaths = {str(path.relative_to(root)).replace("\\", "/") for path in code_files}

    reused = 0
    rescanned = 0
    symbols: list[dict[str, Any]] = []
    for path in code_files:
        rel = str(path.relative_to(root)).replace("\\", "/")
        fingerprint = _file_fingerprint(path)
        cached = files_map.get(rel)
        if (
            not force
            and isinstance(cached, dict)
            and cached.get("mtime_ns") == fingerprint["mtime_ns"]
            and cached.get("size") == fingerprint["size"]
            and isinstance(cached.get("symbols"), list)
        ):
            file_symbols = cached["symbols"]
            reused += 1
        else:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            file_symbols = extract_symbols_from_text(rel, text, limit=80)
            files_map[rel] = {**fingerprint, "symbols": file_symbols}
            rescanned += 1
        symbols.extend(file_symbols)

    # Drop deleted / renamed-away files from cache.
    removed = 0
    for rel in list(files_map.keys()):
        if rel not in live_relpaths:
            files_map.pop(rel, None)
            removed += 1

    payload = {
        "version": 1,
        "root": str(root),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": files_map,
        "symbols": symbols,
        "files_scanned": len(code_files),
        "files_reused": reused,
        "files_rescanned": rescanned,
        "files_removed": removed,
        "force": force,
        "method": "regex_heuristic_incremental",
    }
    save_symbol_cache(cache_file, payload)
    tree = build_tree_summary(root)
    return {
        "root": str(root),
        "cache_path": str(cache_file),
        "files_scanned": len(code_files),
        "files_reused": reused,
        "files_rescanned": rescanned,
        "files_removed": removed,
        "symbol_count": len(symbols),
        "truncated": len(code_files) >= max_files,
        "refreshed": True,
        "force": force,
        "tree": tree,
        "updated_at": payload["updated_at"],
        "embeddings": False,
        "method": "regex_heuristic_incremental",
        "embeddings_note": "Symbol/tree/cache indexer only — embeddings are optional and not required for @codebase.",
    }


def index_workspace_symbols(
    root: Path,
    *,
    max_files: int = 400,
    max_file_bytes: int = 400_000,
    query: str = "",
    limit: int = 100,
    use_cache: bool = True,
    refresh: bool = False,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    needle = (query or "").strip().lower()
    cache_file = Path(cache_path) if cache_path else _default_cache_path(root)

    if refresh or (use_cache and not cache_file.is_file()):
        refresh_meta = refresh_workspace_index(
            root,
            cache_path=cache_file,
            max_files=max_files,
            max_file_bytes=max_file_bytes,
            force=refresh,
        )
    else:
        refresh_meta = None

    if use_cache and cache_file.is_file():
        cache = load_symbol_cache(cache_file)
        collected: list[dict[str, Any]] = []
        for symbol in cache.get("symbols") or []:
            if needle and needle not in f"{symbol.get('name', '')} {symbol.get('path', '')}".lower():
                continue
            collected.append(symbol)
            if len(collected) >= limit:
                return {
                    "root": str(root),
                    "files_scanned": int(cache.get("files_scanned") or len(cache.get("files") or {})),
                    "symbols": collected,
                    "truncated": True,
                    "from_cache": True,
                    "cache_path": str(cache_file),
                    "tree": build_tree_summary(root),
                    "index": refresh_meta,
                    "embeddings": False,
                    "embeddings_note": "Symbol/tree/cache indexer only — embeddings are optional and not required for @codebase.",
                }
        return {
            "root": str(root),
            "files_scanned": int(cache.get("files_scanned") or len(cache.get("files") or {})),
            "symbols": collected,
            "truncated": False,
            "from_cache": True,
            "cache_path": str(cache_file),
            "tree": build_tree_summary(root),
            "index": refresh_meta,
            "embeddings": False,
            "embeddings_note": "Symbol/tree/cache indexer only — embeddings are optional and not required for @codebase.",
        }

    # Live scan fallback (no cache write unless refresh was requested).
    collected = []
    files_scanned = 0
    for path in _iter_code_files(root, max_files=max_files, max_file_bytes=max_file_bytes):
        files_scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        for symbol in extract_symbols_from_text(rel, text, limit=80):
            if needle and needle not in f"{symbol['name']} {symbol['path']}".lower():
                continue
            collected.append(symbol)
            if len(collected) >= limit:
                return {
                    "root": str(root),
                    "files_scanned": files_scanned,
                    "symbols": collected,
                    "truncated": True,
                    "from_cache": False,
                    "tree": build_tree_summary(root),
                    "embeddings": False,
                    "embeddings_note": "Symbol/tree/cache indexer only — embeddings are optional and not required for @codebase.",
                }
    return {
        "root": str(root),
        "files_scanned": files_scanned,
        "symbols": collected,
        "truncated": False,
        "from_cache": False,
        "tree": build_tree_summary(root),
        "embeddings": False,
        "embeddings_note": "Symbol/tree/cache indexer only — embeddings are optional and not required for @codebase.",
    }


def list_workspace_tree(
    root: Path,
    *,
    relative: str = "",
    query: str = "",
    max_entries: int = 200,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """List one directory under an approved workspace root (symlink-safe)."""
    from path_boundary import join_within_root, path_within_root, resolve_root

    resolved_root = resolve_root(root)
    if not resolved_root.is_dir():
        raise FileNotFoundError(resolved_root)
    rel = str(relative or "").replace("\\", "/").strip().strip("/")
    current = resolved_root if not rel else join_within_root(resolved_root, rel)
    if not path_within_root(current, resolved_root):
        raise ValueError(f"Pad buiten scope: {relative}")
    if not current.is_dir():
        raise NotADirectoryError(str(current))
    cache_files: dict[str, Any] = {}
    if cache_path and Path(cache_path).is_file():
        try:
            cached = load_symbol_cache(Path(cache_path))
            if isinstance(cached.get("files"), dict):
                cache_files = cached["files"]
        except Exception:
            cache_files = {}
    needle = (query or "").strip().lower()
    entries: list[dict[str, Any]] = []
    truncated = False
    try:
        children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        raise FileNotFoundError(str(current)) from exc
    for child in children:
        if child.name in SKIP_DIRS or child.name.startswith("."):
            continue
        if not path_within_root(child, resolved_root):
            continue
        try:
            if child.is_symlink() and not path_within_root(child.resolve(strict=False), resolved_root):
                continue
            is_dir = child.is_dir() and not child.is_symlink()
            is_file = child.is_file() and path_within_root(child, resolved_root)
        except OSError:
            continue
        if not is_dir and not is_file:
            continue
        if needle and needle not in child.name.lower():
            continue
        child_rel = str(child.relative_to(resolved_root)).replace("\\", "/")
        dirty = False
        size = None
        if is_file:
            try:
                fingerprint = _file_fingerprint(child)
                size = fingerprint["size"]
                cached_fp = cache_files.get(child_rel)
                if isinstance(cached_fp, dict) and (
                    cached_fp.get("mtime_ns") != fingerprint["mtime_ns"]
                    or cached_fp.get("size") != fingerprint["size"]
                ):
                    dirty = True
            except OSError:
                pass
        entries.append(
            {
                "name": child.name,
                "path": child_rel,
                "kind": "dir" if is_dir else "file",
                "size": size,
                "dirty": dirty,
            }
        )
        if len(entries) >= max_entries:
            truncated = True
            break
    return {
        "root": str(resolved_root),
        "relative": rel,
        "entries": entries,
        "truncated": truncated,
        "query": query or "",
    }


def preview_workspace_file(
    root: Path,
    *,
    relative: str,
    max_chars: int = 20_000,
) -> dict[str, Any]:
    """Read a text preview of a file that stays inside the approved workspace root."""
    from path_boundary import join_within_root, path_within_root, resolve_root

    resolved_root = resolve_root(root)
    rel = str(relative or "").replace("\\", "/").strip().strip("/")
    if not rel:
        raise ValueError("relative path ontbreekt")
    target = join_within_root(resolved_root, rel)
    if not path_within_root(target, resolved_root):
        raise ValueError(f"Pad buiten scope: {relative}")
    if target.is_symlink() and not path_within_root(target.resolve(strict=False), resolved_root):
        raise ValueError(f"Pad buiten scope: {relative}")
    if not target.is_file():
        raise FileNotFoundError(rel)
    try:
        raw = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise FileNotFoundError(rel) from exc
    truncated = len(raw) > max_chars
    text = raw[:max_chars]
    return {
        "root": str(resolved_root),
        "path": rel,
        "content": text,
        "truncated": truncated,
        "chars": len(text),
        "total_chars": len(raw),
    }
