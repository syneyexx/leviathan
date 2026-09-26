"""Coding-loop capability enforcement (unread_file, must_patch, max writes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.common.paths import PathEscapeError

from .types import CodingError, Mission
from .workspace import confine, is_denied


# WRITE / EXECUTE capabilities that count against the per-round budget.
GATED_CAPS = frozenset(
    {
        "file.write",
        "file.patch",
        "file.delete",
        "coding.run_tests",
        "artifact.create_text",
        "knowledge.ingest_scan",
    }
)

READ_CAPS = frozenset(
    {
        "file.read",
        "workspace.list",
        "workspace.search",
        "file.inspect_csv",
        "file.parse_pdf",
        "knowledge.search",
        "git.status",
        "git.diff",
    }
)

MUST_PATCH_LINE_THRESHOLD = 80
MAX_WRITES_PER_ROUND = 2


def enforce_capability(
    capability_id: str,
    arguments: dict[str, Any],
    *,
    workspace_root: Path,
    read_paths: set[str],
    mission: Mission,
    writes_this_round: int,
) -> dict[str, Any]:
    """Validate and normalize a capability call. Raises CodingError on reject.

    Returns possibly-rewritten arguments (absolute confined paths).
    """
    args = dict(arguments or {})

    if capability_id in GATED_CAPS and writes_this_round >= MAX_WRITES_PER_ROUND:
        raise CodingError(
            "MAX_WRITES",
            f"Max {MAX_WRITES_PER_ROUND} WRITE/EXECUTE capabilities per model round",
            http_status=409,
            details={"capability_id": capability_id},
        )

    path = args.get("path")
    if path is not None:
        try:
            confined = confine(workspace_root, str(path))
        except PathEscapeError as exc:
            raise CodingError(
                "PATH_DENIED",
                str(exc),
                http_status=403,
                details={"path": path, "reason": "escape_or_denied"},
            ) from exc
        if is_denied(confined, root=workspace_root):
            raise CodingError(
                "PATH_DENIED",
                f"Denied path: {path}",
                http_status=403,
                details={"path": path, "reason": "hades_or_deny"},
            )
        # Store absolute path for function providers; keep display relative in metadata.
        args["path"] = str(confined)
        args["_rel_path"] = _rel(workspace_root, confined)

    if capability_id in {"file.write", "file.patch", "file.delete"}:
        rel = args.get("_rel_path") or str(args.get("path") or "")
        target = Path(args["path"]) if args.get("path") else None
        exists = bool(target and target.exists())
        # ENFORCE-1: must have read the file first (except new files on SCAFFOLD).
        if capability_id in {"file.write", "file.patch"}:
            unread_ok = (
                capability_id == "file.write"
                and not exists
                and mission == Mission.SCAFFOLD
            )
            normalized_reads = {_norm(p) for p in read_paths}
            if not unread_ok and _norm(rel) not in normalized_reads and _norm(str(target)) not in normalized_reads:
                # Also accept if any read_paths basename matches confined path.
                if not _path_was_read(rel, str(target or ""), read_paths):
                    raise CodingError(
                        "unread_file",
                        f"WRITE/PATCH refused for unread path: {rel}",
                        http_status=409,
                        details={"path": rel, "reason": "unread_file"},
                    )

        # ENFORCE-2: existing files > 80 lines must use file.patch.
        if capability_id == "file.write" and exists and target is not None:
            try:
                line_count = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                line_count = 0
            if line_count > MUST_PATCH_LINE_THRESHOLD:
                raise CodingError(
                    "must_patch",
                    f"file.write refused for existing file with {line_count} lines; use file.patch",
                    http_status=409,
                    details={"path": rel, "lines": line_count, "reason": "must_patch"},
                )

    # Reject shell-string / invented command capabilities honestly (not catalogued).
    if capability_id in {"coding.run_command", "git.commit"}:
        raise CodingError(
            "UNKNOWN_CAPABILITY",
            f"Capability {capability_id!r} is not in the CapabilityCatalog",
            http_status=422,
            details={"capability_id": capability_id},
        )

    return args


def mark_read(read_paths: set[str], path: str) -> None:
    read_paths.add(_norm(path))


def _path_was_read(rel: str, absolute: str, read_paths: set[str]) -> bool:
    norms = {_norm(p) for p in read_paths}
    if _norm(rel) in norms or _norm(absolute) in norms:
        return True
    # Match by trailing path suffix.
    for item in norms:
        if item.endswith("/" + _norm(rel)) or _norm(rel).endswith(item):
            return True
    return False


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _norm(path: str) -> str:
    return str(path or "").replace("\\", "/").lstrip("./")
