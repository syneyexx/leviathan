"""Incremental repository intelligence: symbols, imports, and relationship graph.

Deterministic parsing first (Python AST, then existing heuristic parsers).
Does not write into the user's source repository unless an explicit cache path is given.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from path_boundary import path_within_root
from workspace_symbols import CODE_EXTENSIONS, SKIP_DIRS, extract_symbols_from_text

INDEX_VERSION = 2
MAX_FILE_BYTES = 400_000
MAX_FILES = 800
MAX_CACHE_BYTES = 8_000_000


def _codeindex_limit(name: str, fallback: int) -> int:
    """Resolve a Control Plane codeindex ceiling; keep module constant as fallback."""
    try:
        from control.service import resolve_setting

        value = resolve_setting(name, default=fallback)
        if value is None:
            return fallback
        return int(value)
    except Exception:
        return fallback


def max_file_bytes() -> int:
    return _codeindex_limit("codeindex.max_file_bytes", MAX_FILE_BYTES)

_ROUTE_DECO = re.compile(
    r"@(?:app|router|api|bp)\.(?:get|post|put|patch|delete|head|options)\(\s*['\"]([^'\"]+)",
    re.I,
)
_TS_IMPLEMENTS = re.compile(r"class\s+(\w+)\s+implements\s+([^{]+)")
_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".h": "c_header",
    ".hpp": "cpp_header",
    ".java": "java",
    ".rs": "rust",
    ".go": "go",
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".less": "css",
    ".html": "html",
    ".htm": "html",
    ".vue": "vue",
    ".svelte": "svelte",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
}

BUILD_MARKERS = (
    ("pytest.ini", "pytest"),
    ("pyproject.toml", "pytest"),
    ("package.json", "npm"),
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("CMakeLists.txt", "cmake"),
    ("Cargo.toml", "cargo"),
    ("go.mod", "go"),
    ("pom.xml", "maven"),
    ("build.gradle", "gradle"),
    ("build.gradle.kts", "gradle"),
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_languages_and_build(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    languages: set[str] = set()
    try:
        for path in root.rglob("*"):
            if not path.is_file() or any(p in SKIP_DIRS for p in path.parts):
                continue
            lang = _LANG.get(path.suffix.lower())
            if lang:
                languages.add(lang)
    except OSError:
        pass
    build: list[str] = []
    for name, label in BUILD_MARKERS:
        if (root / name).exists() and label not in build:
            build.append(label)
    if (root / "vite.config.ts").exists() or (root / "vite.config.js").exists():
        build.append("vite")
    if (root / "webpack.config.js").exists():
        build.append("webpack")
    if (root / "tsconfig.json").exists():
        build.append("tsc")
    return {
        "languages": sorted(languages),
        "build_systems": build,
        "method": "marker_and_extension",
        "semantic": False,
    }


def parse_python_ast(path: str, text: str) -> dict[str, Any] | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    imports: list[dict[str, str]] = []
    symbols: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    bases: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []

    def add_symbol(name: str, kind: str, node: ast.AST, parent: str | None = None) -> None:
        symbols.append(
            {
                "name": name,
                "kind": kind,
                "path": path,
                "line": int(getattr(node, "lineno", 1)),
                "end_line": int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                "parent": parent,
            }
        )

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({"module": alias.name, "names": alias.asname or "", "kind": "import"})
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names = ", ".join(a.name for a in node.names)
            imports.append({"module": mod, "names": names, "kind": "from"})
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            add_symbol(node.name, "function", node)
            for deco in node.decorator_list:
                raw = ast.unparse(deco) if hasattr(ast, "unparse") else ""
                match = _ROUTE_DECO.search("@" + raw)
                if match:
                    routes.append({"path": match.group(1), "handler": node.name, "line": node.lineno})
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    calls.append({"caller": node.name, "callee": _call_name(child), "line": getattr(child, "lineno", node.lineno)})
        elif isinstance(node, ast.ClassDef):
            add_symbol(node.name, "class", node)
            for base in node.bases:
                bases.append({"class": node.name, "base": _call_name(base)})
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    add_symbol(item.name, "method", item, parent=node.name)
                    for child in ast.walk(item):
                        if isinstance(child, ast.Call):
                            calls.append(
                                {
                                    "caller": f"{node.name}.{item.name}",
                                    "callee": _call_name(child),
                                    "line": getattr(child, "lineno", item.lineno),
                                }
                            )

    for match in _ROUTE_DECO.finditer(text):
        if not any(r.get("path") == match.group(1) for r in routes):
            routes.append({"path": match.group(1), "handler": None, "line": text[: match.start()].count("\n") + 1})

    return {
        "path": path,
        "language": "python",
        "method": "python_ast",
        "imports": imports,
        "exports": [s for s in symbols if s.get("kind") in {"function", "class"}],
        "outline": symbols,
        "calls": calls[:200],
        "inheritance": bases,
        "routes": routes,
    }


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    try:
        return ast.unparse(node)[:80]
    except Exception:
        return type(node).__name__


def analyze_source(rel: str, text: str) -> dict[str, Any]:
    suffix = Path(rel).suffix.lower()
    if suffix == ".py":
        parsed = parse_python_ast(rel, text)
        if parsed:
            return parsed
        symbols = extract_symbols_from_text(rel, text or "", limit=120)
        imports: list[dict[str, str]] = []
        for match in re.finditer(
            r"^\s*(?:from\s+([\w\.]+)\s+import\s+([^\n]+)|import\s+([\w\.]+))",
            text or "",
            re.M,
        ):
            if match.group(1):
                imports.append({"module": match.group(1), "names": match.group(2).strip(), "kind": "from"})
            elif match.group(3):
                imports.append({"module": match.group(3).strip(), "names": "", "kind": "import"})
        return {
            "path": rel,
            "language": "python",
            "method": "heuristic_parser",
            "imports": imports,
            "exports": [s for s in symbols if s.get("kind") in {"function", "class"}],
            "outline": symbols,
            "calls": [],
            "inheritance": [],
            "routes": [],
        }
    if suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        from code_intel import parse_typescript_module

        payload = parse_typescript_module(rel, text)
        implements = []
        for match in _TS_IMPLEMENTS.finditer(text or ""):
            implements.append({"class": match.group(1), "interface": match.group(2).strip()})
        payload["implements"] = implements
        payload["calls"] = []
        payload["routes"] = []
        return payload
    symbols = extract_symbols_from_text(rel, text or "", limit=80)
    return {
        "path": rel,
        "language": _LANG.get(suffix, "unknown"),
        "method": "lexical_fallback",
        "imports": [],
        "exports": symbols,
        "outline": symbols,
        "calls": [],
        "inheritance": [],
        "routes": [],
        "note": "No semantic parser for this language; symbols only.",
    }


def _iter_files(root: Path, *, max_files: int, max_file_bytes: int) -> list[Path]:
    extra_ext = set(CODE_EXTENSIONS) | {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            break
        if not path.is_file() or path.suffix.lower() not in extra_ext:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path_within_root(path, root):
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                continue
        except OSError:
            continue
        files.append(path)
    return files


def _resolve_import(module: str, *, from_path: str, files: set[str]) -> str | None:
    if not module:
        return None
    rel_from = str(Path(from_path).parent).replace("\\", "/")
    candidates = [
        module.replace(".", "/") + ".py",
        module.replace(".", "/") + "/__init__.py",
        (rel_from + "/" + module.replace(".", "/") + ".py").lstrip("./"),
    ]
    if module.startswith("."):
        return None
    for cand in candidates:
        norm = cand.replace("\\", "/").lstrip("./")
        if norm in files:
            return norm
    return None


def index_repository(
    root: Path,
    *,
    cache_path: Path | None = None,
    max_files: int = MAX_FILES,
    persist: bool = True,
    git_revision: str | None = None,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    cache: dict[str, Any] = {"version": INDEX_VERSION, "files": {}, "edges": []}
    if cache_path and cache_path.is_file():
        try:
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and int(loaded.get("version") or 0) == INDEX_VERSION:
                cache = loaded
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            cache = {"version": INDEX_VERSION, "files": {}, "edges": []}

    files_map: dict[str, Any] = dict(cache.get("files") or {})
    live_files = _iter_files(root, max_files=max_files, max_file_bytes=max_file_bytes())
    live_rels = {path.relative_to(root).as_posix() for path in live_files}
    reused = 0
    rescanned = 0
    for path in live_files:
        rel = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
        except OSError:
            continue
        digest = _sha256_bytes(data)
        cached = files_map.get(rel)
        if isinstance(cached, dict) and cached.get("hash") == digest and cached.get("index_version") == INDEX_VERSION:
            reused += 1
            continue
        text = data.decode("utf-8", errors="replace")
        parsed = analyze_source(rel, text)
        files_map[rel] = {
            "path": rel,
            "hash": digest,
            "language": parsed.get("language"),
            "method": parsed.get("method"),
            "symbols": parsed.get("outline") or parsed.get("exports") or [],
            "imports": parsed.get("imports") or [],
            "exports": parsed.get("exports") or [],
            "calls": parsed.get("calls") or [],
            "inheritance": parsed.get("inheritance") or [],
            "implements": parsed.get("implements") or [],
            "routes": parsed.get("routes") or [],
            "index_version": INDEX_VERSION,
            "bytes": len(data),
        }
        rescanned += 1

    for rel in list(files_map.keys()):
        if rel not in live_rels:
            files_map.pop(rel, None)

    edges = _build_edges(files_map)
    meta = detect_languages_and_build(root)
    payload = {
        "version": INDEX_VERSION,
        "root": str(root),
        "git_revision": git_revision,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": files_map,
        "edges": edges,
        "languages": meta["languages"],
        "build_systems": meta["build_systems"],
        "files_reused": reused,
        "files_rescanned": rescanned,
        "file_count": len(files_map),
        "method": "incremental_hash_index",
    }
    if persist and cache_path is not None:
        _save_cache(cache_path, payload)
        payload["cache_path"] = str(cache_path)
    elif persist:
        payload["cache_path"] = None
        payload["persist_skipped"] = "no_cache_path_source_unmodified"
    return payload


def intel_cache_path_for(root: Path, store_root: Path | None) -> Path | None:
    """Place cache under HADES workspace, never the user's source tree by default."""
    if store_root is None:
        return None
    key = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:16]
    return Path(store_root) / "repo_intel" / f"{key}.json"


def _save_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, ensure_ascii=False)
    if len(blob.encode("utf-8")) > MAX_CACHE_BYTES:
        slim = dict(payload)
        files = dict(slim.get("files") or {})
        # Drop bulky call lists first to bound growth.
        for meta in files.values():
            if isinstance(meta, dict):
                meta["calls"] = (meta.get("calls") or [])[:20]
        blob = json.dumps(slim, ensure_ascii=False)
        payload.update(slim)
        payload["cache_truncated"] = True
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(blob, encoding="utf-8")
    tmp.replace(path)


def _build_edges(files_map: dict[str, Any]) -> list[dict[str, Any]]:
    rels = set(files_map.keys())
    edges: list[dict[str, Any]] = []
    symbol_owner: dict[str, str] = {}
    for rel, meta in files_map.items():
        for sym in meta.get("exports") or []:
            name = str(sym.get("name") or "")
            if name:
                symbol_owner.setdefault(name, rel)
    for rel, meta in files_map.items():
        for imp in meta.get("imports") or []:
            target = _resolve_import(str(imp.get("module") or ""), from_path=rel, files=rels)
            if target:
                edges.append({"kind": "imports", "from": rel, "to": target, "names": imp.get("names")})
        for call in meta.get("calls") or []:
            callee = str(call.get("callee") or "").split(".")[-1]
            owner = symbol_owner.get(callee)
            if owner:
                edges.append(
                    {
                        "kind": "calls",
                        "from_symbol": call.get("caller"),
                        "to_symbol": callee,
                        "from_file": rel,
                        "to_file": owner,
                    }
                )
        for item in meta.get("inheritance") or []:
            base = str(item.get("base") or "").split(".")[-1]
            owner = symbol_owner.get(base)
            if owner:
                edges.append({"kind": "implements", "from": rel, "from_symbol": item.get("class"), "to": owner, "to_symbol": base})
        for item in meta.get("implements") or []:
            iface = str(item.get("interface") or "").split(",")[0].strip()
            owner = symbol_owner.get(iface)
            if owner:
                edges.append({"kind": "implements", "from": rel, "from_symbol": item.get("class"), "to": owner, "to_symbol": iface})
        if _is_test_path(rel):
            for imp in meta.get("imports") or []:
                target = _resolve_import(str(imp.get("module") or ""), from_path=rel, files=rels)
                if target:
                    edges.append({"kind": "test_covers", "from": rel, "to": target})
        for route in meta.get("routes") or []:
            handler = route.get("handler")
            if handler:
                edges.append({"kind": "route_handler", "from": str(route.get("path")), "to_symbol": handler, "to_file": rel})
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for edge in edges:
        key = json.dumps(edge, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        unique.append(edge)
        if len(unique) >= 4000:
            break
    return unique


def _is_test_path(rel: str) -> bool:
    name = Path(rel).name.lower()
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{rel.lower()}"


def neighbors(index: dict[str, Any], rel: str, *, kinds: list[str] | None = None, depth: int = 1) -> list[str]:
    wanted = set(kinds or [])
    frontier = {rel}
    found: set[str] = set()
    for _ in range(max(1, depth)):
        nxt: set[str] = set()
        for edge in index.get("edges") or []:
            if wanted and edge.get("kind") not in wanted:
                continue
            left = str(edge.get("from") or edge.get("from_file") or "")
            right = str(edge.get("to") or edge.get("to_file") or "")
            if left in frontier and right:
                nxt.add(right)
            if right in frontier and left:
                nxt.add(left)
        nxt.discard(rel)
        found.update(nxt)
        frontier = nxt
        if not frontier:
            break
    return sorted(found)


def rank_files_for_goal(index: dict[str, Any], goal: str, *, limit: int = 12) -> list[dict[str, Any]]:
    tokens = [t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", goal or "")]
    scored: list[dict[str, Any]] = []
    for rel, meta in (index.get("files") or {}).items():
        score = 0.0
        reasons: list[str] = []
        name = Path(rel).name.lower()
        if any(tok in name for tok in tokens):
            score += 4.0
            reasons.append("filename")
        for sym in meta.get("symbols") or []:
            sname = str(sym.get("name") or "").lower()
            if sname in tokens:
                score += 3.5
                reasons.append(f"symbol:{sname}")
        if _is_test_path(rel) and any(tok in {"test", "fix", "bug", "fail"} for tok in tokens):
            score += 1.0
            reasons.append("test")
        if score > 0:
            scored.append({"path": rel, "score": score, "reason": ",".join(dict.fromkeys(reasons)), "hash": meta.get("hash")})
    scored.sort(key=lambda item: (-float(item["score"]), item["path"]))
    return scored[:limit]


def tests_covering(index: dict[str, Any], changed: list[str]) -> list[str]:
    changed_set = set(changed)
    tests: list[str] = []
    for edge in index.get("edges") or []:
        if edge.get("kind") != "test_covers":
            continue
        if edge.get("to") in changed_set:
            tests.append(str(edge.get("from")))
    for rel in index.get("files") or {}:
        if not _is_test_path(rel):
            continue
        stem = Path(rel).stem.replace("test_", "")
        for path in changed:
            if stem and stem in Path(path).stem:
                tests.append(rel)
    return list(dict.fromkeys(tests))
