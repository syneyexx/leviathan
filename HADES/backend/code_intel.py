"""Language-aware code outline helpers (heuristic parsers for Python + TS/JS).

Results are labeled heuristic unless a real language server is attached.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from workspace_symbols import extract_symbols_from_text

_PY_IMPORT = re.compile(
    r"^\s*(?:from\s+([\w\.]+)\s+import\s+([^\n]+)|import\s+([\w\.]+)(?:\s+as\s+\w+)?)",
    re.M,
)
_TS_IMPORT = re.compile(
    r"""^\s*import\s+(?:type\s+)?(?:([\w*\s{},]+)\s+from\s+)?['\"]([^'\"]+)['\"]""",
    re.M,
)
_TS_EXPORT = re.compile(
    r"""^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var|type|interface|enum)\s+([A-Za-z_][\w]*)""",
    re.M,
)
_TS_EXPORT_LIST = re.compile(r"""^\s*export\s+\{([^}]+)\}""", re.M)


def parse_python_module(path: str, text: str) -> dict[str, Any]:
    try:
        from repo_intelligence import parse_python_ast

        parsed = parse_python_ast(path, text)
        if parsed:
            return parsed
    except Exception:
        pass
    imports: list[dict[str, str]] = []
    for match in _PY_IMPORT.finditer(text or ""):
        if match.group(1):
            imports.append({"module": match.group(1), "names": match.group(2).strip(), "kind": "from"})
        elif match.group(3):
            imports.append({"module": match.group(3).strip(), "names": "", "kind": "import"})
    symbols = extract_symbols_from_text(path, text or "", limit=120)
    return {
        "path": path,
        "language": "python",
        "method": "heuristic_parser",
        "imports": imports,
        "exports": [s for s in symbols if s.get("kind") in {"function", "class"}],
        "outline": symbols,
    }


def parse_typescript_module(path: str, text: str) -> dict[str, Any]:
    imports: list[dict[str, str]] = []
    for match in _TS_IMPORT.finditer(text or ""):
        imports.append(
            {
                "names": (match.group(1) or "").strip(),
                "module": match.group(2),
                "kind": "import",
            }
        )
    exports: list[dict[str, Any]] = []
    for match in _TS_EXPORT.finditer(text or ""):
        exports.append({"name": match.group(1), "kind": "export"})
    for match in _TS_EXPORT_LIST.finditer(text or ""):
        for part in match.group(1).split(","):
            name = part.strip().split(" as ")[0].strip()
            if name:
                exports.append({"name": name, "kind": "export_list"})
    symbols = extract_symbols_from_text(path, text or "", limit=120)
    return {
        "path": path,
        "language": "typescript",
        "method": "heuristic_parser",
        "imports": imports,
        "exports": exports,
        "outline": symbols,
    }


def analyze_file(root: Path, rel_path: str) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    path = (root / rel_path).resolve()
    if root.resolve() not in path.parents and path != root:
        # allow file directly under root
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"path_outside_root:{rel_path}") from exc
    text = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    rel = str(path.relative_to(root)).replace("\\", "/")
    if suffix == ".py":
        return parse_python_module(rel, text)
    if suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        return parse_typescript_module(rel, text)
    return {
        "path": rel,
        "language": "unknown",
        "method": "heuristic_parser",
        "imports": [],
        "exports": [],
        "outline": extract_symbols_from_text(rel, text, limit=80),
        "note": "Unsupported extension for language-aware parse; symbols only.",
    }



