"""Deterministic edit/diff helpers for the coding agent.

Does not own worktrees — BuildAgentService remains the workspace manager.
Produces and consumes standards-compliant unified diffs.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import Path
from typing import Any

from path_boundary import join_within_root, path_within_root

UNIFIED_HEADER_RE = re.compile(r"^---[ \t]+(?P<old>.+?)(?:\t.*)?$")
PLUS_HEADER_RE = re.compile(r"^\+\+\+[ \t]+(?P<new>.+?)(?:\t.*)?$")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _split_keepends(text: str) -> list[str]:
    if text == "":
        return []
    return text.splitlines(keepends=True)


def make_unified_diff(
    *,
    old_text: str | None,
    new_text: str | None,
    rel: str,
    from_path: str | None = None,
    n: int = 3,
) -> str:
    """Return a unified diff for one file, including new/deleted files and EOF newlines."""
    rel = rel.replace("\\", "/").lstrip("./")
    old_name = f"a/{from_path or rel}" if old_text is not None else "/dev/null"
    new_name = f"b/{rel}" if new_text is not None else "/dev/null"
    old_lines = _split_keepends(old_text or "")
    new_lines = _split_keepends(new_text or "")
    if old_text is None:
        old_name = "/dev/null"
    if new_text is None:
        new_name = "/dev/null"
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=old_name,
        tofile=new_name,
        n=n,
        lineterm="\n",
    )
    body = "".join(diff)
    if not body.strip():
        return ""
    # difflib omits a trailing newline marker; preserve "no newline at eof" when needed.
    parts = [body if body.endswith("\n") else body + "\n"]
    if new_text is not None and new_text != "" and not new_text.endswith("\n"):
        parts.append("\\ No newline at end of file\n")
    elif old_text is not None and new_text is None and old_text != "" and not old_text.endswith("\n"):
        parts.append("\\ No newline at end of file\n")
    return "".join(parts)


def make_worktree_unified_diff(
    work_root: Path,
    *,
    baseline_hashes: dict[str, str],
    source_root: Path | None = None,
    renamed: list[tuple[str, str]] | None = None,
) -> str:
    """Build a multi-file unified diff between baseline (source or hashes) and worktree."""
    work = Path(work_root).resolve()
    source = Path(source_root).resolve() if source_root else None
    chunks: list[str] = []
    seen: set[str] = set()
    rename_from = {dst: src for src, dst in (renamed or [])}

    for path in sorted(work.rglob("*")):
        if not path.is_file() or not path_within_root(path, work):
            continue
        rel = path.relative_to(work).as_posix()
        if _skip_rel(rel):
            continue
        seen.add(rel)
        try:
            new_text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        old_text: str | None = None
        from_rel = rename_from.get(rel)
        baseline_rel = from_rel or rel
        if source is not None and (source / baseline_rel).is_file():
            try:
                old_text = (source / baseline_rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                old_text = ""
        elif rel not in baseline_hashes and not from_rel:
            old_text = None
        elif source is None:
            old_text = None
        if old_text is not None and sha256_text(old_text) == sha256_text(new_text) and not from_rel:
            continue
        chunk = make_unified_diff(old_text=old_text, new_text=new_text, rel=rel, from_path=from_rel)
        if chunk:
            chunks.append(chunk.rstrip("\n"))

    for rel, _old_hash in sorted(baseline_hashes.items()):
        if rel in seen or _skip_rel(rel):
            continue
        work_file = work / rel
        if work_file.exists():
            continue
        old_text = ""
        if source is not None and (source / rel).is_file():
            try:
                old_text = (source / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                old_text = ""
        chunk = make_unified_diff(old_text=old_text, new_text=None, rel=rel)
        if chunk:
            chunks.append(chunk.rstrip("\n"))
    return "\n".join(chunks) + ("\n" if chunks else "")


def _skip_rel(rel: str) -> bool:
    parts = Path(rel).parts
    skip = {".git", "__pycache__", "node_modules", ".venv", ".tox", "dist", "build", ".next"}
    if any(part in skip for part in parts):
        return True
    return Path(rel).suffix.lower() in {".pyc", ".pyo", ".pyd"}


def apply_unified_diff_to_text(original: str, diff_text: str) -> str:
    """Apply a single-file unified diff to ``original``. Raises ValueError on mismatch."""
    lines = original.splitlines(keepends=True)
    hunks = list(_parse_hunks(diff_text))
    if not hunks:
        raise ValueError("unified_diff_has_no_hunks")
    # Apply from bottom to top so line numbers stay valid.
    for old_start, old_count, payload in reversed(hunks):
        start = max(0, old_start - 1)
        end = start + old_count
        expected_old = [row[1] for row in payload if row[0] in {" ", "-"}]
        actual = lines[start:end]
        if not _lines_match(actual, expected_old):
            raise ValueError(
                f"unified_diff_context_mismatch: expected {len(expected_old)} line(s) at {old_start}"
            )
        replacement = [row[1] for row in payload if row[0] in {" ", "+"}]
        lines[start:end] = replacement
    return "".join(lines)


def _lines_match(actual: list[str], expected: list[str]) -> bool:
    if len(actual) != len(expected):
        return False
    for left, right in zip(actual, expected, strict=True):
        if left == right:
            continue
        if left.rstrip("\n") == right.rstrip("\n"):
            continue
        return False
    return True


def _parse_hunks(diff_text: str) -> list[tuple[int, int, list[tuple[str, str]]]]:
    raw_lines = diff_text.splitlines()
    hunks: list[tuple[int, int, list[tuple[str, str]]]] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        match = HUNK_RE.match(line)
        if not match:
            i += 1
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        payload: list[tuple[str, str]] = []
        i += 1
        while i < len(raw_lines):
            row = raw_lines[i]
            if row.startswith("@@") or UNIFIED_HEADER_RE.match(row) or PLUS_HEADER_RE.match(row):
                break
            if row.startswith("\\"):
                i += 1
                continue
            if not row:
                payload.append((" ", "\n"))
                i += 1
                continue
            tag = row[0]
            if tag not in {" ", "+", "-"}:
                break
            text = row[1:] + "\n"
            payload.append((tag, text))
            i += 1
        hunks.append((old_start, old_count, payload))
    return hunks


def check_edit_preconditions(
    work_root: Path,
    rel: str,
    *,
    action: str,
    expected_old: str | None = None,
    expected_hash: str | None = None,
    protected_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Verify an edit is still valid against the isolated worktree."""
    work = Path(work_root).resolve()
    target = join_within_root(work, rel)
    protected = {p.replace("\\", "/").lstrip("./") for p in (protected_paths or [])}
    rel_norm = rel.replace("\\", "/").lstrip("./")
    if rel_norm in protected or any(rel_norm.startswith(p.rstrip("/") + "/") for p in protected):
        return {"ok": False, "reason": "protected_path", "path": rel_norm}
    exists = target.is_file()
    if action == "create" and exists:
        return {"ok": False, "reason": "already_exists", "path": rel_norm}
    if action in {"replace", "patch_lines", "unified_diff"} and not exists and action != "create":
        if action != "unified_diff":
            return {"ok": False, "reason": "target_missing", "path": rel_norm}
    current = ""
    if exists:
        current = target.read_text(encoding="utf-8")
        digest = sha256_text(current)
        if expected_hash and digest != expected_hash:
            return {"ok": False, "reason": "stale_hash", "path": rel_norm, "actual_hash": digest}
        if expected_old is not None and current != expected_old:
            return {"ok": False, "reason": "baseline_changed", "path": rel_norm}
    return {"ok": True, "path": rel_norm, "exists": exists}


def patch_lines(original: str, start_line: int, end_line: int, block: str) -> str:
    lines = original.splitlines(keepends=True) if original else []
    start = max(1, start_line) - 1
    end = max(start, end_line)
    new_block = block.splitlines(keepends=True)
    if new_block and not new_block[-1].endswith(("\n", "\r")):
        new_block[-1] = new_block[-1] + "\n"
    lines[start:end] = new_block
    return "".join(lines)


def symbol_replace_python(original: str, symbol: str, new_source: str) -> str | None:
    """Replace a top-level Python function/class body by AST range. None if unavailable."""
    import ast

    try:
        tree = ast.parse(original)
    except SyntaxError:
        return None
    lines = original.splitlines(keepends=True)
    for node in tree.body:
        name = getattr(node, "name", None)
        if name != symbol:
            continue
        start = int(getattr(node, "lineno", 1)) - 1
        end = int(getattr(node, "end_lineno", start + 1))
        replacement = new_source.splitlines(keepends=True)
        if replacement and not replacement[-1].endswith(("\n", "\r")):
            replacement[-1] = replacement[-1] + "\n"
        lines[start:end] = replacement
        return "".join(lines)
    return None
