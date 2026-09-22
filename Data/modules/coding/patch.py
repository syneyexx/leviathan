"""Unified diff apply — fail-closed, no fuzzy matching."""

from __future__ import annotations

from dataclasses import dataclass


class PatchApplyError(ValueError):
    def __init__(self, message: str, *, reason: str = "hunk_mismatch") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class _Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]  # includes leading ' ', '+', '-'


def _parse_hunk_header(line: str) -> tuple[int, int, int, int]:
    # @@ -l,s +l,s @@
    if not line.startswith("@@"):
        raise PatchApplyError(f"Invalid hunk header: {line!r}", reason="bad_hunk")
    try:
        body = line.split("@@")[1].strip()
        old_part, new_part = body.split(" ")[0], body.split(" ")[1]
        def parse_range(part: str) -> tuple[int, int]:
            part = part[1:]  # drop +/- 
            if "," in part:
                start_s, count_s = part.split(",", 1)
                return int(start_s), int(count_s)
            return int(part), 1

        old_start, old_count = parse_range(old_part)
        new_start, new_count = parse_range(new_part)
        return old_start, old_count, new_start, new_count
    except (IndexError, ValueError) as exc:
        raise PatchApplyError(f"Invalid hunk header: {line!r}", reason="bad_hunk") from exc


def parse_unified_diff(diff: str) -> list[_Hunk]:
    lines = diff.splitlines()
    hunks: list[_Hunk] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("@@"):
            old_start, old_count, new_start, new_count = _parse_hunk_header(line)
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].startswith("@@"):
                if lines[i].startswith("---") or lines[i].startswith("+++"):
                    break
                if lines[i].startswith("diff ") or lines[i].startswith("index "):
                    break
                body.append(lines[i])
                i += 1
            hunks.append(
                _Hunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=tuple(body),
                )
            )
            continue
        i += 1
    if not hunks:
        raise PatchApplyError("Diff contains no hunks", reason="empty_diff")
    return hunks


def apply_unified_diff(original: str, diff: str) -> str:
    """Apply unified diff to ``original`` text. Fail closed on context mismatch."""
    # Normalize to lines without keeping a trailing empty from final newline ambiguity.
    src_lines = original.splitlines(keepends=True)
    # Work on newline-stripped for matching; reconstruct with \n.
    src = original.splitlines()
    hunks = parse_unified_diff(diff)

    # Apply from bottom to top so line numbers stay valid.
    for hunk in reversed(hunks):
        start = hunk.old_start - 1  # 0-based
        if start < 0:
            raise PatchApplyError("Hunk old_start < 1", reason="bad_hunk")
        old_slice: list[str] = []
        new_slice: list[str] = []
        for raw in hunk.lines:
            if raw.startswith("\\"):  # "\ No newline at end of file"
                continue
            if not raw:
                # empty line in diff is rare; treat as context empty
                prefix, text = " ", ""
            else:
                prefix, text = raw[0], raw[1:]
            if prefix == " ":
                old_slice.append(text)
                new_slice.append(text)
            elif prefix == "-":
                old_slice.append(text)
            elif prefix == "+":
                new_slice.append(text)
            else:
                raise PatchApplyError(f"Invalid hunk line prefix: {raw!r}", reason="bad_hunk")

        end = start + len(old_slice)
        if end > len(src):
            raise PatchApplyError(
                f"Hunk extends past end of file (need lines {start + 1}-{end}, file has {len(src)})",
                reason="hunk_mismatch",
            )
        actual = src[start:end]
        if actual != old_slice:
            raise PatchApplyError(
                "Hunk context does not match file (shifted or modified)",
                reason="hunk_mismatch",
            )
        src = src[:start] + new_slice + src[end:]

    # Preserve trailing newline if original had one.
    result = "\n".join(src)
    if original.endswith("\n") or (not original and src_lines):
        if result and not result.endswith("\n"):
            result += "\n"
    elif original.endswith("\n"):
        result += "\n"
    if original.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result
