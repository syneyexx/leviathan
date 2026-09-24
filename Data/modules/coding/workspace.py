"""Workspace confinement for the Coding Agent."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from Data.modules.common.paths import PathEscapeError, safe_join, safe_relpath

_DENY_DIR_NAMES = frozenset(
    {
        ".venv",
        "node_modules",
        "__pycache__",
        ".git",
        "dist",
    }
)

_SEARCH_IGNORE_GLOBS = (
    ".venv",
    "node_modules",
    "dist",
    "__pycache__",
    "HADES",
    "*.db",
    "*.sqlite",
    "*.bin",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.pyc",
)

_DENY_SUFFIXES = (
    ".db-wal",
    ".db-shm",
    ".sqlite-wal",
    ".sqlite-shm",
)


def _is_windows_abs(text: str) -> bool:
    return len(text) >= 3 and text[0].isalpha() and text[1] == ":" and text[2] in {"/", "\\"}


def resolve_root(
    settings: Any | None = None,
    *,
    override: str | Path | None = None,
    project_root: Path | None = None,
    raw: str | Path | None = None,
) -> Path:
    """Resolve coding workspace root.

    Accepts either ``resolve_root(settings, override=...)`` or
    ``resolve_root(raw, project_root=...)`` for compatibility.
    Windows drive-letter roots are preserved on POSIX.
    """
    if raw is not None and override is None:
        override = raw
    if override is not None and str(override).strip():
        return _as_operator_path(str(override).strip(), project_root=project_root)
    if settings is not None:
        coding = getattr(settings, "coding", None)
        workspace = getattr(coding, "workspace", None) if coding is not None else None
        if workspace is not None and str(workspace).strip():
            return _as_operator_path(str(workspace), project_root=project_root)
    env = os.getenv("LEVIATHAN_CODING_WORKSPACE")
    if env and env.strip():
        return _as_operator_path(env.strip(), project_root=project_root)
    return _as_operator_path("codingworkspace", project_root=project_root)


def _as_operator_path(text: str, *, project_root: Path | None = None) -> Path:
    text = text.strip()
    if _is_windows_abs(text) or text.startswith("\\\\") or text.startswith("//"):
        return Path(text)
    path = Path(text)
    if not path.is_absolute():
        if project_root is None:
            from Data.backend.config import PROJECT_ROOT

            project_root = PROJECT_ROOT
        path = Path(project_root) / path
    return path


def is_hades_path(path: Path | str) -> bool:
    text = str(path).replace("\\", "/")
    parts = [p for p in text.split("/") if p]
    for part in parts:
        if part.upper() == "HADES":
            return True
    lowered = text.lower()
    if "/hades/" in lowered or lowered.endswith("/hades"):
        return True
    if lowered.startswith("hades/"):
        return True
    if "data/hades" in lowered:
        return True
    return False


def is_denied(path: Path | str, *, root: Path | None = None) -> bool:
    """Return True when the path touches a denied prefix (HADES, venv, …)."""
    if is_hades_path(path):
        return True
    text = str(path).replace("\\", "/")
    parts = set(Path(text).parts) | set(PureWindowsPath(str(path)).parts)
    if parts & _DENY_DIR_NAMES:
        return True
    for suffix in _DENY_SUFFIXES:
        if text.endswith(suffix):
            return True
    normalized = text.replace("\\", "/")
    if "/Data/frontend/dist" in normalized or normalized.endswith("/Data/frontend/dist"):
        return True
    if root is not None:
        try:
            rel = safe_relpath(Path(root), Path(path))
            if is_hades_path(rel) or (set(rel.parts) & _DENY_DIR_NAMES):
                return True
        except (PathEscapeError, OSError, ValueError):
            return True
    return False


def is_denied_write_target(rel_or_abs: Path | str) -> bool:
    return is_denied(rel_or_abs)


def confine(workspace_root: Path, user_path: str | Path | None = None) -> Path:
    """Resolve ``user_path`` under workspace; raise PathEscapeError on escape/deny."""
    root = Path(workspace_root)
    try:
        root_resolved = root.resolve() if root.exists() else root
    except OSError:
        root_resolved = root

    if user_path is None or str(user_path).strip() in {"", ".", "./"}:
        if is_denied(root_resolved, root=root_resolved):
            raise PathEscapeError("Workspace root is denied")
        return root_resolved

    raw = str(user_path).strip()
    if "\x00" in raw:
        raise PathEscapeError("Null byte in path")

    pure = PureWindowsPath(raw) if ("\\" in raw or _is_windows_abs(raw)) else PurePosixPath(raw)
    if pure.is_absolute() or getattr(pure, "drive", ""):
        candidate = Path(raw)
        try:
            candidate_res = candidate.resolve() if candidate.exists() else candidate
        except OSError:
            candidate_res = candidate
        try:
            safe_relpath(root_resolved, candidate_res)
        except PathEscapeError as exc:
            raise PathEscapeError(f"Path escapes workspace: {raw}") from exc
        if is_denied(candidate_res, root=root_resolved) or is_hades_path(raw):
            raise PathEscapeError(f"Denied path: {raw}")
        return candidate_res

    if is_hades_path(raw):
        raise PathEscapeError(f"Denied path: {raw}")

    parts = [p for p in raw.replace("\\", "/").split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        raise PathEscapeError(f"Parent traversal refused: {raw!r}")
    try:
        joined = safe_join(root_resolved, *parts) if parts else root_resolved
    except PathEscapeError:
        joined = root_resolved.joinpath(*parts)
        try:
            safe_relpath(root_resolved, joined)
        except PathEscapeError as exc:
            raise PathEscapeError(f"Path escapes workspace: {raw}") from exc
    if is_denied(joined, root=root_resolved):
        raise PathEscapeError(f"Denied path: {raw}")
    return joined


def ensure_workspace(root: Path) -> Path:
    return ensure_workspace_dir(root)


def ensure_workspace_dir(root: Path) -> Path:
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return root


def should_skip_search_path(rel_path: str) -> bool:
    lowered = rel_path.replace("\\", "/").lower()
    if is_hades_path(rel_path):
        return True
    parts = lowered.split("/")
    for part in parts:
        if part in {n.lower() for n in _DENY_DIR_NAMES}:
            return True
    for pattern in _SEARCH_IGNORE_GLOBS:
        if fnmatch.fnmatch(Path(lowered).name, pattern.lower()):
            return True
        if any(fnmatch.fnmatch(p, pattern.lower()) for p in parts):
            return True
    return False


def list_entries(
    root: Path,
    *,
    path: str | None = None,
    recursive: bool = False,
    max_entries: int = 200,
) -> list[dict[str, Any]]:
    base = confine(root, path)
    if not base.exists():
        return []
    if base.is_file():
        return [{"path": _rel_display(root, base), "type": "file", "size": base.stat().st_size}]

    entries: list[dict[str, Any]] = []
    walker: Iterable[Path] = base.rglob("*") if recursive else base.iterdir()
    for item in sorted(walker, key=lambda p: str(p).lower()):
        if len(entries) >= max_entries:
            break
        try:
            if is_denied(item, root=root):
                continue
            confine(root, _rel_display(root, item))
        except (PathEscapeError, OSError, ValueError):
            continue
        if item.is_symlink():
            try:
                target = item.resolve()
                safe_relpath(Path(root).resolve() if Path(root).exists() else Path(root), target)
            except (PathEscapeError, OSError, ValueError):
                continue
        kind = "dir" if item.is_dir() else "file"
        size = item.stat().st_size if item.is_file() else 0
        entries.append({"path": _rel_display(root, item), "type": kind, "size": size})
    return entries


def search_files(
    root: Path,
    query: str,
    *,
    path: str | None = None,
    glob: str | None = None,
    max_hits: int = 50,
) -> dict[str, Any]:
    base = confine(root, path)
    if not query:
        return {"hits": [], "method": "python", "query": query}

    method = "python"
    hits: list[dict[str, Any]] = []
    from shutil import which

    rg = which("rg")
    if rg:
        import subprocess

        cmd = [rg, "--line-number", "--no-heading", "--color", "never", "-F", query]
        if glob:
            cmd.extend(["--glob", glob])
        for pattern in _SEARCH_IGNORE_GLOBS:
            cmd.extend(["--glob", f"!{pattern}"])
        cmd.append(str(base))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
            method = "ripgrep"
            for line in proc.stdout.splitlines():
                if len(hits) >= max_hits:
                    break
                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue
                path_str, line_no, text = parts
                try:
                    number = int(line_no)
                    confined = confine(root, path_str)
                    rel = _rel_display(root, confined)
                except (PathEscapeError, ValueError):
                    continue
                hits.append({"path": rel, "line": number, "text": text[:500]})
            return {"hits": hits, "method": method, "query": query}
        except (OSError, subprocess.TimeoutExpired):
            method = "python"

    for file_path in _iter_searchable(base, root=root, glob=glob):
        if len(hits) >= max_hits:
            break
        try:
            data = file_path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if query in line:
                hits.append({"path": _rel_display(root, file_path), "line": idx, "text": line[:500]})
                if len(hits) >= max_hits:
                    break
    return {"hits": hits, "method": method, "query": query}


def _iter_searchable(base: Path, *, root: Path, glob: str | None) -> Iterable[Path]:
    if base.is_file():
        yield base
        return
    for item in base.rglob("*"):
        if not item.is_file():
            continue
        if is_denied(item, root=root):
            continue
        rel = _rel_display(root, item)
        if should_skip_search_path(rel):
            continue
        if glob and not fnmatch.fnmatch(item.name, glob) and not fnmatch.fnmatch(rel, glob):
            continue
        yield item


def _rel_display(root: Path, path: Path) -> str:
    try:
        return str(safe_relpath(root, path)).replace("\\", "/")
    except PathEscapeError:
        try:
            return str(Path(path).relative_to(root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")


def env_workspace_override() -> str | None:
    return os.getenv("LEVIATHAN_CODING_WORKSPACE")
