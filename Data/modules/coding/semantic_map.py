"""Repository semantic map — symbols, imports, refs, tests, build metadata (U202–U203)."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


@dataclass(frozen=True)
class SymbolRecord:
    name: str
    kind: str  # function | class | method | import | test
    file: str
    line: int
    end_line: int | None = None
    references: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "end_line": self.end_line,
            "references": list(self.references),
        }


@dataclass
class FileIndexEntry:
    path: str
    content_hash: str
    mtime_ns: int
    language: str
    symbols: list[SymbolRecord] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "mtime_ns": self.mtime_ns,
            "language": self.language,
            "symbols": [s.public_dict() for s in self.symbols],
            "imports": list(self.imports),
            "exports": list(self.exports),
        }


@dataclass
class RepoSemanticMap:
    workspace_root: str
    generated_at: str
    files: dict[str, FileIndexEntry] = field(default_factory=dict)
    tests: list[str] = field(default_factory=list)
    build_metadata: dict[str, Any] = field(default_factory=dict)
    call_edges: list[tuple[str, str]] = field(default_factory=list)
    incremental: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "generated_at": self.generated_at,
            "file_count": len(self.files),
            "symbol_count": sum(len(f.symbols) for f in self.files.values()),
            "test_files": list(self.tests),
            "build_metadata": dict(self.build_metadata),
            "call_edges": [{"from": a, "to": b} for a, b in self.call_edges[:500]],
            "files": {k: v.public_dict() for k, v in sorted(self.files.items())},
            "incremental": self.incremental,
            "truth": {
                "map_is_not_authorization": True,
                "incremental_updates_only_changed_files": True,
            },
        }

    def symbols_for(self, name: str) -> list[SymbolRecord]:
        needle = name.lower()
        out: list[SymbolRecord] = []
        for entry in self.files.values():
            for sym in entry.symbols:
                if needle in sym.name.lower():
                    out.append(sym)
        return out


class SemanticMapBuilder:
    """Build / incrementally refresh a repository semantic map."""

    def __init__(self, workspace_root: Path, *, max_files: int = 2000) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.max_files = max_files

    def build(self, previous: RepoSemanticMap | None = None) -> RepoSemanticMap:
        prev_files = dict(previous.files) if previous else {}
        files: dict[str, FileIndexEntry] = {}
        tests: list[str] = []
        call_edges: list[tuple[str, str]] = []
        scanned = 0
        reused = 0

        for path in self._iter_source_files():
            scanned += 1
            if scanned > self.max_files:
                break
            rel = self._rel(path)
            try:
                st = path.stat()
                digest = _file_hash(path)
            except OSError:
                continue
            cached = prev_files.get(rel)
            if cached and cached.content_hash == digest and cached.mtime_ns == st.st_mtime_ns:
                files[rel] = cached
                reused += 1
                if self._is_test_path(rel):
                    tests.append(rel)
                continue
            entry = self._index_file(path, rel, digest, st.st_mtime_ns)
            files[rel] = entry
            if self._is_test_path(rel):
                tests.append(rel)
            for sym in entry.symbols:
                for ref in sym.references:
                    call_edges.append((f"{rel}:{sym.name}", ref))

        build_meta = self._detect_build_metadata()
        return RepoSemanticMap(
            workspace_root=str(self.workspace_root),
            generated_at=_utc_now(),
            files=files,
            tests=sorted(set(tests)),
            build_metadata=build_meta,
            call_edges=call_edges,
            incremental=bool(previous) and reused > 0,
        )

    def _iter_source_files(self) -> Iterable[Path]:
        for path in sorted(self.workspace_root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}:
                yield path
            elif path.name in {"package.json", "pyproject.toml", "setup.cfg", "Cargo.toml", "go.mod"}:
                yield path

    def _index_file(self, path: Path, rel: str, digest: str, mtime_ns: int) -> FileIndexEntry:
        language = path.suffix.lstrip(".").lower() or path.name
        symbols: list[SymbolRecord] = []
        imports: list[str] = []
        exports: list[str] = []
        if path.suffix == ".py":
            symbols, imports, exports = self._index_python(path, rel)
        elif path.name in {"package.json", "pyproject.toml"}:
            exports = [path.name]
        return FileIndexEntry(
            path=rel,
            content_hash=digest,
            mtime_ns=mtime_ns,
            language=language,
            symbols=symbols,
            imports=imports,
            exports=exports,
        )

    def _index_python(
        self, path: Path, rel: str
    ) -> tuple[list[SymbolRecord], list[str], list[str]]:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError):
            return [], [], []
        symbols: list[SymbolRecord] = []
        imports: list[str] = []
        exports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "test" if node.name.startswith("test_") else "function"
                refs = tuple(
                    sorted(
                        {
                            n.id
                            for n in ast.walk(node)
                            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                        }
                    )[:20]
                )
                symbols.append(
                    SymbolRecord(
                        name=node.name,
                        kind=kind,
                        file=rel,
                        line=getattr(node, "lineno", 1),
                        end_line=getattr(node, "end_lineno", None),
                        references=refs,
                    )
                )
                if kind != "test":
                    exports.append(node.name)
            elif isinstance(node, ast.ClassDef):
                symbols.append(
                    SymbolRecord(
                        name=node.name,
                        kind="class",
                        file=rel,
                        line=getattr(node, "lineno", 1),
                        end_line=getattr(node, "end_lineno", None),
                    )
                )
                exports.append(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    imports.append(f"{mod}.{alias.name}" if mod else alias.name)
        return symbols, imports, exports

    def _detect_build_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {"tools": []}
        root = self.workspace_root
        if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists() or any(
            root.glob("test_*.py")
        ):
            meta["tools"].append({"name": "pytest", "kind": "test", "status": "detected"})
        if (root / "package.json").exists():
            meta["tools"].append({"name": "npm", "kind": "build", "status": "detected"})
            try:
                data = json.loads((root / "package.json").read_text(encoding="utf-8"))
                scripts = data.get("scripts") or {}
                meta["npm_scripts"] = sorted(scripts.keys())
                if "test" in scripts:
                    meta["tools"].append({"name": "npm-test", "kind": "test", "status": "detected"})
            except (OSError, json.JSONDecodeError):
                pass
        if (root / "Cargo.toml").exists():
            meta["tools"].append({"name": "cargo", "kind": "build", "status": "detected"})
        if (root / "go.mod").exists():
            meta["tools"].append({"name": "go", "kind": "build", "status": "detected"})
        # git history presence (not a private coding DB)
        meta["git_present"] = (root / ".git").exists()
        return meta

    @staticmethod
    def _is_test_path(rel: str) -> bool:
        name = Path(rel).name.lower()
        return (
            name.startswith("test_")
            or name.endswith("_test.py")
            or "/tests/" in rel.replace("\\", "/")
            or rel.replace("\\", "/").startswith("tests/")
        )

    def _rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.workspace_root)).replace("\\", "/")
        except ValueError:
            return str(path)
