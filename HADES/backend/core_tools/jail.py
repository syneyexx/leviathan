"""Path jail helpers for HADES core filesystem tools."""

from __future__ import annotations

from pathlib import Path

try:
    from gen2.sandbox import path_is_within
except Exception:  # pragma: no cover
    def path_is_within(candidate: Path, root: Path) -> bool:  # type: ignore[misc]
        try:
            candidate.resolve().relative_to(root.resolve())
            return True
        except Exception:
            return False


def resolve_jail_root(data_root: Path | str, *, workspace: Path | str | None = None) -> Path:
    root = Path(data_root).expanduser().resolve(strict=False)
    if workspace:
        ws = Path(workspace).expanduser().resolve(strict=False)
        if path_is_within(ws, root) or ws == root:
            return ws
    return root


def resolve_inside_jail(
    raw_path: str | None,
    *,
    data_root: Path,
    workspace: Path | None = None,
    default_relative: str = ".",
) -> tuple[Path | None, str | None]:
    """Return (resolved_path, error_reason_code)."""
    jail = resolve_jail_root(data_root, workspace=workspace)
    text = (raw_path or default_relative).strip() or default_relative
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = jail / candidate
    try:
        resolved = candidate.expanduser().resolve(strict=False)
    except OSError:
        return None, "path_outside_jail"
    if not path_is_within(resolved, jail):
        return None, "path_outside_jail"
    return resolved, None
