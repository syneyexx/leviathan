from __future__ import annotations

from pathlib import Path
from typing import Any

from Data.modules.common.secrets import redact_secrets


_BINARY_SAMPLE = 8192


def run(
    path: str,
    *,
    max_bytes: int = 1_000_000,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    """Read a local text file with optional line range.

    Output lines are always formatted as ``L{n}|{text}``.
    Binary files (NUL in sample) → FAILED-style error.
    Secret-looking content is redacted before return.
    """
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {target}")
    size = target.stat().st_size
    if size > max_bytes:
        raise ValueError(f"File exceeds max_bytes={max_bytes}: {size}")

    data = target.read_bytes()[:max_bytes]
    if b"\x00" in data[:_BINARY_SAMPLE]:
        raise ValueError(f"FAILED: binary file refused: {target}")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"FAILED: non-text file refused: {target}") from exc

    # Redact secrets for .env / token-like files and any secret-looking body.
    name_lower = target.name.lower()
    if (
        name_lower in {".env", ".env.local", ".env.example"}
        or "secret" in name_lower
        or "token" in name_lower
        or "api_key" in name_lower
    ):
        text = redact_secrets(text)
    else:
        text = redact_secrets(text)

    lines = text.splitlines()
    total = len(lines)
    start = 1 if start_line is None else max(1, int(start_line))
    end = total if end_line is None else min(total, int(end_line))
    if end < start - 1:
        end = start - 1

    selected = lines[start - 1 : end]
    numbered = [f"L{idx}|{line}" for idx, line in enumerate(selected, start=start)]
    content = "\n".join(numbered)
    if numbered:
        content += "\n" if text.endswith("\n") and end >= total else ""

    return {
        "path": str(target.resolve()) if target.exists() else str(target),
        "size_bytes": size,
        "encoding": "utf-8",
        "content": content,
        "line_count": total,
        "start_line": start,
        "end_line": end,
        "truncated": size > max_bytes,
    }
