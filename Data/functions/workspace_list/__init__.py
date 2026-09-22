from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.coding.workspace import list_entries, resolve_root


def run(
    path: str | None = None,
    *,
    recursive: bool = False,
    max_entries: int = 200,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    """List workspace entries (READ). Paths are confined by the caller/gateway args."""
    # When path is absolute it is treated as the listing root; otherwise use workspace.
    if path and Path(path).is_absolute():
        root = Path(path)
        rel = None
        # If workspace_root given, list relative under it.
        if workspace_root:
            root = Path(workspace_root)
            rel = path
            entries = list_entries(root, path=None, recursive=recursive, max_entries=max_entries)
            # Re-list with relative if path was under workspace — handled below.
        entries = list_entries(root, path=None, recursive=recursive, max_entries=max_entries)
        return {"entries": entries, "path": str(root), "recursive": recursive}

    root = Path(workspace_root) if workspace_root else resolve_root()
    # If `path` looks like a directory that exists as absolute under common usage
    # from the coding loop (already confined absolute), list that directory's parent root.
    if path:
        candidate = Path(path)
        if candidate.exists():
            # Treat absolute confined path as the base to list.
            parent_root = candidate if candidate.is_dir() else candidate.parent
            # Prefer workspace_root when provided for relative display.
            display_root = Path(workspace_root) if workspace_root else parent_root
            if workspace_root:
                entries = list_entries(
                    Path(workspace_root),
                    path=str(candidate.relative_to(Path(workspace_root))) if _is_relative_to(candidate, Path(workspace_root)) else ".",
                    recursive=recursive,
                    max_entries=max_entries,
                )
            else:
                entries = list_entries(parent_root, path=None, recursive=recursive, max_entries=max_entries)
            return {"entries": entries, "path": path, "recursive": recursive}

    entries = list_entries(root, path=path, recursive=recursive, max_entries=max_entries)
    return {"entries": entries, "path": path or ".", "recursive": recursive}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
