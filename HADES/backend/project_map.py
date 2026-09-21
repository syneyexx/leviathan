"""Compact renewably derived project map for coding/research context (Phase D5).

Not a second source of truth: rebuild from the repo + symbol index when stale.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from workspace_symbols import SKIP_DIRS, refresh_workspace_index, _default_cache_path, load_symbol_cache

ENTRYPOINT_CANDIDATES = (
    "main.py",
    "app.py",
    "server.py",
    "index.ts",
    "index.tsx",
    "main.tsx",
    "main.ts",
    "HADES_LAUNCHER.py",
    "package.json",
    "pyproject.toml",
    "setup.py",
)


def _detect_test_commands(root: Path) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    if (root / "package.json").is_file():
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
            scripts = pkg.get("scripts") or {}
            if isinstance(scripts, dict):
                for key in ("test", "typecheck", "lint", "build"):
                    if key in scripts:
                        commands.append({"id": f"npm_{key}", "command": f"npm run {key}", "source": "package.json"})
        except (OSError, json.JSONDecodeError):
            pass
    if (root / "pytest.ini").is_file() or (root / "pyproject.toml").is_file():
        commands.append({"id": "pytest", "command": "python -m pytest", "source": "python"})
    if any(root.rglob("test_*.py")):
        commands.append({"id": "unittest", "command": "python -m unittest", "source": "test_*.py"})
    return commands


def _subsystem_guess(root: Path) -> list[dict[str, Any]]:
    subs: list[dict[str, Any]] = []
    for name in ("backend", "components", "lib", "docs", "plugins", "tests"):
        path = root / name
        if path.is_dir():
            count = 0
            try:
                for child in path.rglob("*"):
                    if child.is_file() and not any(p in SKIP_DIRS for p in child.parts):
                        count += 1
                        if count >= 200:
                            break
            except OSError:
                count = 0
            subs.append({"id": name, "path": name, "approx_files": count})
    return subs


def build_project_map(root: Path, *, refresh_symbols: bool = True) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    symbol_meta = None
    if refresh_symbols:
        try:
            symbol_meta = refresh_workspace_index(root)
        except Exception as exc:
            symbol_meta = {"error": str(exc)}
    cache = load_symbol_cache(_default_cache_path(root))
    entrypoints = [name for name in ENTRYPOINT_CANDIDATES if (root / name).exists()]
    # Also pick top-level Python/TS modules.
    try:
        for child in sorted(root.iterdir()):
            if child.is_file() and child.suffix in {".py", ".ts", ".tsx"} and child.name not in entrypoints:
                if child.name in {"main.py", "app.py", "index.ts", "main.tsx"}:
                    entrypoints.append(child.name)
    except OSError:
        pass
    payload = {
        "version": 1,
        "root": str(root),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entrypoints": entrypoints,
        "subsystems": _subsystem_guess(root),
        "test_commands": _detect_test_commands(root),
        "symbol_index": {
            "files": len(cache.get("files") or {}),
            "symbols": len(cache.get("symbols") or []),
            "updated_at": cache.get("updated_at") or (symbol_meta or {}).get("updated_at"),
            "method": "regex_heuristic",
        },
        "relations_note": "Derived map; rebuild after repo changes. Not semantic dependency analysis.",
        "stale_policy": "Compare symbol_index.updated_at / file mtimes before trusting conclusions.",
    }
    out = root / ".hades_project_map.json"
    try:
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        payload["path"] = str(out)
    except OSError:
        payload["path"] = None
    return payload


def find_change_impact(
    root: Path,
    *,
    symbol: str | None = None,
    path: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Find callers/tests/related files before a change (heuristic references)."""
    from lsp_light import find_references, find_definition

    root = Path(root).expanduser().resolve()
    results: dict[str, Any] = {
        "root": str(root),
        "symbol": symbol,
        "path": path,
        "method": "regex_heuristic",
        "definitions": [],
        "references": [],
        "tests": [],
        "evidence": [],
    }
    name = (symbol or "").strip()
    if not name and path:
        # Use basename stem as weak symbol hint.
        name = Path(path).stem
    if not name:
        results["note"] = "symbol_or_path_required"
        return results
    defs = find_definition(root, name, limit=min(20, limit))
    refs = find_references(root, name, limit=limit)
    results["definitions"] = defs.get("definitions") or []
    results["references"] = refs.get("references") or []
    for item in results["references"]:
        rel = str(item.get("path") or "")
        evidence = {
            "path": rel,
            "line": item.get("line"),
            "snippet": item.get("snippet"),
            "kind": item.get("kind"),
            "source_version": "workspace_live",
        }
        results["evidence"].append(evidence)
        if re.search(r"(^|/)(test_|.*\.test\.|.*_test\.|tests/)", rel):
            results["tests"].append(evidence)
    results["counts"] = {
        "definitions": len(results["definitions"]),
        "references": len(results["references"]),
        "tests": len(results["tests"]),
    }
    return results
