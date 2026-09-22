from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.coding.workspace import resolve_root, search_files


def run(
    query: str,
    *,
    path: str | None = None,
    glob: str | None = None,
    max_hits: int = 50,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    """Search workspace file contents. Reports method=ripgrep|python."""
    if path and Path(path).is_absolute() and Path(path).exists():
        # Absolute confined directory/file from coding loop.
        base = Path(path)
        root = Path(workspace_root) if workspace_root else (base if base.is_dir() else base.parent)
        rel = None
        if workspace_root and _is_relative_to(base, Path(workspace_root)):
            root = Path(workspace_root)
            rel = str(base.relative_to(root))
            return search_files(root, query, path=rel, glob=glob, max_hits=max_hits)
        # Search under the absolute path as root.
        return search_files(base if base.is_dir() else base.parent, query, path=None, glob=glob, max_hits=max_hits)

    root = Path(workspace_root) if workspace_root else resolve_root()
    return search_files(root, query, path=path, glob=glob, max_hits=max_hits)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
