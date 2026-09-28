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


# Recursive listings above this cap are not inline-safe. file_io is not on
# this build, so the control plane fails closed instead of walking the tree.
RECURSIVE_INLINE_MAX_ENTRIES = 500
SEARCH_INLINE_MAX_HITS = 200
SEARCH_FILE_BYTE_CAP = 8 * 1024 * 1024
SEARCH_CONTROL_PLANE_FILE_BUDGET = 4_000


class WorkspaceScanExternalRequired(RuntimeError):
    """Large workspace scan must not run inside FastAPI."""

    code = "WORKSPACE_SCAN_EXTERNAL_REQUIRED"


def _scan_allowed_inline() -> bool:
    """Coding/dataset workers may scan with budgets. The API process may not."""
    try:
        from Data.modules.execution.workload import running_in_worker_process

        return bool(running_in_worker_process())
    except Exception:  # noqa: BLE001
        return False


def _is_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            if is_junction():
                return True
        except OSError:
            return True
    return False


def _reparse_escapes(root: Path, item: Path) -> bool:
    if not _is_reparse(item):
        return False
    try:
        target = item.resolve()
        safe_relpath(Path(root).resolve() if Path(root).exists() else Path(root), target)
    except (PathEscapeError, OSError, ValueError):
        return True
    return False


def list_entries(
    root: Path,
    *,
    path: str | None = None,
    recursive: bool = False,
    max_entries: int = 200,
) -> list[dict[str, Any]]:
    if recursive and max_entries > RECURSIVE_INLINE_MAX_ENTRIES and not _scan_allowed_inline():
        raise WorkspaceScanExternalRequired(
            "recursive workspace.list above the inline cap requires file_io; "
            "refusing to scan inside the control plane"
        )
    base = confine(root, path)
    if not base.exists():
        return []
    if base.is_file():
        return [{"path": _rel_display(root, base), "type": "file", "size": base.stat().st_size}]

    entries: list[dict[str, Any]] = []

    def _accept(item: Path) -> None:
        if len(entries) >= max_entries:
            return
        try:
            if is_denied(item, root=root):
                return
            confine(root, _rel_display(root, item))
        except (PathEscapeError, OSError, ValueError):
            return
        if _reparse_escapes(root, item):
            return
        try:
            kind = "dir" if item.is_dir() and not item.is_file() else "file"
            size = item.stat().st_size if item.is_file() else 0
        except OSError:
            return
        entries.append({"path": _rel_display(root, item), "type": kind, "size": size})

    if not recursive:
        try:
            children = sorted(base.iterdir(), key=lambda p: str(p).lower())
        except OSError:
            return []
        for item in children:
            if len(entries) >= max_entries:
                break
            _accept(item)
        return entries

    # Bounded walk. Do not sort(rglob("*")) — that materializes the whole tree.
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        kept_dirs: list[str] = []
        for name in dirnames:
            child = Path(dirpath) / name
            if _reparse_escapes(root, child) or is_denied(child, root=root):
                continue
            kept_dirs.append(name)
            _accept(child)
            if len(entries) >= max_entries:
                return entries
        dirnames[:] = kept_dirs
        for name in filenames:
            if len(entries) >= max_entries:
                return entries
            _accept(Path(dirpath) / name)
    return entries


def search_files(
    root: Path,
    query: str,
    *,
    path: str | None = None,
    glob: str | None = None,
    max_hits: int = 50,
    cancel_check: Any | None = None,
) -> dict[str, Any]:
    if max_hits > SEARCH_INLINE_MAX_HITS and not _scan_allowed_inline():
        raise WorkspaceScanExternalRequired(
            "large workspace.search must not run inside the control plane"
        )
    base = confine(root, path)
    if not query:
        return {
            "hits": [],
            "method": "python",
            "query": query,
            "truncated": False,
            "scannedFiles": 0,
            "skippedFiles": 0,
        }

    method = "python"
    hits: list[dict[str, Any]] = []
    from shutil import which

    rg = which("rg")
    use_rg = bool(rg) and (_scan_allowed_inline() or max_hits <= SEARCH_INLINE_MAX_HITS)
    if use_rg:
        import subprocess

        cmd = [
            rg,
            "--line-number",
            "--no-heading",
            "--color",
            "never",
            "-F",
            "--max-filesize",
            "8M",
            query,
        ]
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
            return {
                "hits": hits,
                "method": method,
                "query": query,
                "truncated": len(proc.stdout.splitlines()) > len(hits),
                "limitsReached": len(hits) >= max_hits,
            }
        except (OSError, subprocess.TimeoutExpired):
            method = "python"

    scanned = 0
    skipped = 0
    bytes_scanned = 0
    file_budget = SEARCH_CONTROL_PLANE_FILE_BUDGET if not _scan_allowed_inline() else 100_000
    limits_reached = False
    for file_path in _iter_searchable(base, root=root, glob=glob):
        if cancel_check is not None and cancel_check():
            limits_reached = True
            break
        if len(hits) >= max_hits or scanned >= file_budget:
            limits_reached = True
            break
        scanned += 1
        try:
            file_hits, consumed, binary = _scan_file_lines(
                file_path,
                query,
                root=root,
                max_hits=max_hits - len(hits),
                byte_cap=SEARCH_FILE_BYTE_CAP,
            )
        except OSError:
            skipped += 1
            continue
        bytes_scanned += consumed
        if binary:
            skipped += 1
            continue
        hits.extend(file_hits)
    return {
        "hits": hits,
        "method": method,
        "query": query,
        "truncated": limits_reached,
        "scannedFiles": scanned,
        "skippedFiles": skipped,
        "bytesScanned": bytes_scanned,
        "scanned_files": scanned,
        "scanned_bytes": bytes_scanned,
        "limitsReached": limits_reached,
    }


def _scan_file_lines(
    file_path: Path,
    query: str,
    *,
    root: Path,
    max_hits: int,
    byte_cap: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Stream a file. Never read_bytes() the whole object."""
    hits: list[dict[str, Any]] = []
    scanned = 0
    line_no = 0
    with file_path.open("rb") as handle:
        head = handle.read(min(8192, byte_cap))
        scanned += len(head)
        if b"\x00" in head:
            return [], scanned, True
        pending = head
        while True:
            while b"\n" in pending:
                raw, pending = pending.split(b"\n", 1)
                line_no += 1
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("utf-8", errors="replace")
                if query in text and len(hits) < max_hits:
                    hits.append(
                        {
                            "path": _rel_display(root, file_path),
                            "line": line_no,
                            "text": text[:500],
                        }
                    )
                if len(hits) >= max_hits:
                    return hits, scanned, False
            if scanned >= byte_cap:
                break
            chunk = handle.read(min(65536, byte_cap - scanned))
            if not chunk:
                if pending:
                    line_no += 1
                    try:
                        text = pending.decode("utf-8")
                    except UnicodeDecodeError:
                        text = pending.decode("utf-8", errors="replace")
                    if query in text and len(hits) < max_hits:
                        hits.append(
                            {
                                "path": _rel_display(root, file_path),
                                "line": line_no,
                                "text": text[:500],
                            }
                        )
                break
            scanned += len(chunk)
            pending += chunk
    return hits, scanned, False


def _iter_searchable(base: Path, *, root: Path, glob: str | None) -> Iterable[Path]:
    if base.is_file():
        yield base
        return
    for item in base.rglob("*"):
        if not item.is_file():
            continue
        if _reparse_escapes(root, item):
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
