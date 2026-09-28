"""Repository semantic map — symbols, imports, refs, tests, build metadata (U202–U203).

Heavy builds belong on the coding worker. Cached reads may remain inline.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from Data.modules.coding.workspace_gen import capture_workspace_generation


MAX_SEMANTIC_FILES = 8_000
MAX_SEMANTIC_FILE_BYTES = 2 * 1024 * 1024

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
    "HADES",
    "editor",
}

# Index algorithm version — bump when output semantics change.
INDEX_ALGORITHM_VERSION = "coding.semantic_map.v2"

# Languages with real AST semantic indexing vs metadata-only.
LANGUAGE_SUPPORT = {
    "python": "ast",
    "py": "ast",
    "ts": "metadata",
    "tsx": "metadata",
    "js": "metadata",
    "jsx": "metadata",
    "go": "metadata",
    "rs": "metadata",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_hash(path: Path, *, max_bytes: int = 2_000_000) -> str:
    """Hash file contents with a size guard; huge files use size+mtime only."""
    h = hashlib.sha256()
    try:
        st = path.stat()
        if st.st_size > max_bytes:
            h.update(b"stat|")
            h.update(str(st.st_size).encode("ascii"))
            h.update(str(st.st_mtime_ns).encode("ascii"))
            return h.hexdigest()[:16]
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return "unreadable"
    return h.hexdigest()[:16]


def _cheap_reuse_key(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
        return int(st.st_size), int(st.st_mtime_ns)
    except OSError:
        return None


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
    size: int = 0
    language: str = ""
    symbols: list[SymbolRecord] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    semantic_level: str = "metadata"  # ast | metadata

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "mtime_ns": self.mtime_ns,
            "size": self.size,
            "language": self.language,
            "semantic_level": self.semantic_level,
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
    limits: dict[str, Any] = field(default_factory=dict)
    generation: dict[str, Any] = field(default_factory=dict)
    language_support: dict[str, str] = field(default_factory=lambda: dict(LANGUAGE_SUPPORT))

    def content_fingerprint(self) -> str:
        h = hashlib.sha256()
        h.update(INDEX_ALGORITHM_VERSION.encode("utf-8"))
        h.update(self.workspace_root.encode("utf-8", errors="replace"))
        for path in sorted(self.files):
            entry = self.files[path]
            h.update(path.encode("utf-8", errors="replace"))
            h.update(entry.content_hash.encode("ascii", errors="replace"))
        return h.hexdigest()[:32]

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
            "limits": dict(self.limits),
            "generation": dict(self.generation),
            "language_support": dict(self.language_support),
            "algorithm_version": INDEX_ALGORITHM_VERSION,
            "content_fingerprint": self.content_fingerprint(),
            "truth": {
                "map_is_not_authorization": True,
                "incremental_updates_only_changed_files": True,
                "python_ast_only": True,
                "partial_map_is_truthful": bool(self.limits.get("truncated")),
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


def map_from_public_dict(payload: dict[str, Any]) -> RepoSemanticMap:
    """Rehydrate a previous map for incremental reuse (symbols optional)."""
    files: dict[str, FileIndexEntry] = {}
    for path, raw in (payload.get("files") or {}).items():
        if not isinstance(raw, dict):
            continue
        symbols = [
            SymbolRecord(
                name=str(s.get("name") or ""),
                kind=str(s.get("kind") or "function"),
                file=str(s.get("file") or path),
                line=int(s.get("line") or 1),
                end_line=s.get("end_line"),
                references=tuple(s.get("references") or ()),
            )
            for s in (raw.get("symbols") or [])
            if isinstance(s, dict)
        ]
        files[str(path)] = FileIndexEntry(
            path=str(path),
            content_hash=str(raw.get("content_hash") or ""),
            mtime_ns=int(raw.get("mtime_ns") or 0),
            size=int(raw.get("size") or 0),
            language=str(raw.get("language") or ""),
            symbols=symbols,
            imports=list(raw.get("imports") or []),
            exports=list(raw.get("exports") or []),
            semantic_level=str(raw.get("semantic_level") or "metadata"),
        )
    return RepoSemanticMap(
        workspace_root=str(payload.get("workspace_root") or ""),
        generated_at=str(payload.get("generated_at") or ""),
        files=files,
        tests=list(payload.get("test_files") or []),
        build_metadata=dict(payload.get("build_metadata") or {}),
        incremental=bool(payload.get("incremental")),
        limits=dict(payload.get("limits") or {}),
        generation=dict(payload.get("generation") or {}),
    )


class SemanticMapBuilder:
    """Build / incrementally refresh a repository semantic map."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        max_files: int = 2000,
        cancel_check: Callable[[], bool] | None = None,
        prefer_git_ls_files: bool = True,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.max_files = max_files
        self.cancel_check = cancel_check
        self.prefer_git_ls_files = prefer_git_ls_files

    def build(self, previous: RepoSemanticMap | None = None) -> RepoSemanticMap:
        prev_files = dict(previous.files) if previous else {}
        files: dict[str, FileIndexEntry] = {}
        tests: list[str] = []
        call_edges: list[tuple[str, str]] = []
        scanned = 0
        reused = 0
        discovered = 0
        skipped = 0
        truncated = False
        enumeration = "rglob"

        for path in self._iter_source_files():
            if callable(self.cancel_check) and self.cancel_check():
                truncated = True
                break
            discovered += 1
            if scanned >= self.max_files:
                truncated = True
                skipped += 1
                continue
            scanned += 1
            rel = self._rel(path)
            cheap = _cheap_reuse_key(path)
            if cheap is None:
                skipped += 1
                continue
            size, mtime_ns = cheap
            cached = prev_files.get(rel)
            # Prefer cheap reuse when size+mtime match prior entry; still verify hash if missing.
            if (
                cached
                and cached.mtime_ns == mtime_ns
                and getattr(cached, "size", 0) == size
                and cached.content_hash
            ):
                # Stat evidence matches — reuse without re-hashing enormous files.
                files[rel] = cached
                reused += 1
                if self._is_test_path(rel):
                    tests.append(rel)
                continue
            try:
                digest = _file_hash(path)
            except OSError:
                skipped += 1
                continue
            if cached and cached.content_hash == digest and cached.mtime_ns == mtime_ns:
                # Update size on reused entry for future cheap checks.
                cached.size = size
                files[rel] = cached
                reused += 1
                if self._is_test_path(rel):
                    tests.append(rel)
                continue
            entry = self._index_file(path, rel, digest, mtime_ns, size)
            files[rel] = entry
            if self._is_test_path(rel):
                tests.append(rel)
            for sym in entry.symbols:
                for ref in sym.references:
                    call_edges.append((f"{rel}:{sym.name}", ref))

        # Detect enumeration method for docs/truth.
        if self.prefer_git_ls_files and (self.workspace_root / ".git").exists():
            enumeration = "git_ls_files+untracked"

        build_meta = self._detect_build_metadata()
        try:
            gen = capture_workspace_generation(self.workspace_root).public_dict()
        except Exception:  # noqa: BLE001
            gen = {}

        return RepoSemanticMap(
            workspace_root=str(self.workspace_root),
            generated_at=_utc_now(),
            files=files,
            tests=sorted(set(tests)),
            build_metadata=build_meta,
            call_edges=call_edges,
            incremental=bool(previous) and reused > 0,
            limits={
                "max_files": self.max_files,
                "discovered_files": discovered,
                "indexed_files": len(files),
                "reused_files": reused,
                "skipped_files": skipped + max(0, discovered - scanned) if truncated else skipped,
                "truncated": truncated,
                "truncation_reason": "max_files" if truncated else None,
                "enumeration": enumeration,
            },
            generation=gen,
        )

    def _iter_source_files(self) -> Iterable[Path]:
        """Walk source files without descending into dependency/cache dirs.

        Prefer ``git ls-files`` (+ untracked) when available; otherwise a bounded
        ``os.walk``. Stays inside the coding worker — no per-file microjobs.
        """
        if self.prefer_git_ls_files and (self.workspace_root / ".git").exists():
            yielded = False
            for path in self._iter_git_files():
                yielded = True
                yield path
            if yielded:
                return

        count = 0
        root = self.workspace_root
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            for name in filenames:
                if count >= MAX_SEMANTIC_FILES:
                    return
                path = Path(dirpath) / name
                if path.is_symlink():
                    continue
                interesting = path.suffix.lower() in {
                    ".py",
                    ".ts",
                    ".tsx",
                    ".js",
                    ".jsx",
                    ".go",
                    ".rs",
                } or path.name in {
                    "package.json",
                    "pyproject.toml",
                    "setup.cfg",
                    "Cargo.toml",
                    "go.mod",
                }
                if not interesting:
                    continue
                try:
                    if path.stat().st_size > MAX_SEMANTIC_FILE_BYTES:
                        continue
                except OSError:
                    continue
                count += 1
                yield path

    def _iter_git_files(self) -> Iterable[Path]:
        """Prefer git ls-files; include untracked (non-ignored) coding sources.

        Behavior:
        - Enumerates tracked files via ``git ls-files -z``
        - Adds untracked via ``git ls-files -z --others --exclude-standard``
        - Still filters by source suffixes / denied dirs
        - Does not recurse ``.git/objects``
        """
        try:
            tracked = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=str(self.workspace_root),
                capture_output=True,
                timeout=60,
                check=False,
            )
            others = subprocess.run(
                ["git", "ls-files", "-z", "--others", "--exclude-standard"],
                cwd=str(self.workspace_root),
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        names: list[str] = []
        for blob in (tracked.stdout or b"", others.stdout or b""):
            for part in blob.split(b"\x00"):
                if not part:
                    continue
                try:
                    names.append(part.decode("utf-8"))
                except UnicodeDecodeError:
                    continue
        for name in sorted(set(names)):
            path = self.workspace_root / name
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in Path(name).parts):
                continue
            try:
                if path.stat().st_size > MAX_SEMANTIC_FILE_BYTES:
                    continue
            except OSError:
                continue
            if path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}:
                yield path
            elif path.name in {"package.json", "pyproject.toml", "setup.cfg", "Cargo.toml", "go.mod"}:
                yield path

    def _index_file(
        self, path: Path, rel: str, digest: str, mtime_ns: int, size: int
    ) -> FileIndexEntry:
        language = path.suffix.lstrip(".").lower() or path.name
        symbols: list[SymbolRecord] = []
        imports: list[str] = []
        exports: list[str] = []
        semantic_level = LANGUAGE_SUPPORT.get(language, "metadata")
        if path.suffix == ".py":
            symbols, imports, exports = self._index_python(path, rel)
            semantic_level = "ast"
        elif path.name in {"package.json", "pyproject.toml"}:
            exports = [path.name]
            semantic_level = "metadata"
        return FileIndexEntry(
            path=rel,
            content_hash=digest,
            mtime_ns=mtime_ns,
            size=size,
            language=language,
            symbols=symbols,
            imports=imports,
            exports=exports,
            semantic_level=semantic_level,
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
        if (root / "ruff.toml").exists() or (root / "pyproject.toml").exists():
            meta["tools"].append({"name": "ruff", "kind": "lint", "status": "detected"})
        if (root / "package.json").exists():
            meta["tools"].append({"name": "npm", "kind": "build", "status": "detected"})
            try:
                data = json.loads((root / "package.json").read_text(encoding="utf-8"))
                scripts = data.get("scripts") or {}
                meta["npm_scripts"] = sorted(scripts.keys())
                if "test" in scripts:
                    meta["tools"].append({"name": "npm-test", "kind": "test", "status": "detected"})
                if "lint" in scripts:
                    meta["tools"].append({"name": "eslint", "kind": "lint", "status": "detected"})
            except (OSError, json.JSONDecodeError):
                pass
        if (root / "tsconfig.json").exists():
            meta["tools"].append({"name": "tsc", "kind": "typecheck", "status": "detected"})
        if (root / "Cargo.toml").exists():
            meta["tools"].append({"name": "cargo", "kind": "build", "status": "detected"})
        if (root / "go.mod").exists():
            meta["tools"].append({"name": "go", "kind": "build", "status": "detected"})
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
