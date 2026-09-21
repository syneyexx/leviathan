"""Convert assistant markdown/plain text into speakable speech text.

Preserves meaning: numbers, negations, and uncertainty markers stay intact.
Does not invent facts. Code/tables are announced rather than fully read by default.
"""

from __future__ import annotations

import re
from typing import Literal

SpeakStyle = Literal["compact", "full"]


_CODE_FENCE = re.compile(r"```(\w+)?\n([\s\S]*?)```", re.MULTILINE)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_URL = re.compile(r"https?://[^\s)>\]]+")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BOLD = re.compile(r"(\*\*|__)(.*?)\1")
_ITALIC = re.compile(r"(\*|_)(.*?)\1")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_BULLET = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)
_NUMBERED = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)
_MULTI_NL = re.compile(r"\n{3,}")


def assistant_to_speakable(text: str, *, style: SpeakStyle = "compact", language: str = "nl") -> str:
    raw = (text or "").strip()
    if not raw:
        return ""

    code_blocks: list[tuple[str, str]] = []

    def _replace_code(match: re.Match[str]) -> str:
        lang = (match.group(1) or "").strip()
        body = match.group(2) or ""
        code_blocks.append((lang, body))
        lines = [line for line in body.splitlines() if line.strip()]
        if style == "full" and len(lines) <= 8 and len(body) <= 400:
            label = _code_label(lang, language)
            return f"\n{label}: {body.strip()}\n"
        return f"\n{_code_announce(lang, len(lines), language)}\n"

    out = _CODE_FENCE.sub(_replace_code, raw)

    # Collapse markdown tables
    if style == "compact":
        out = _collapse_tables(out, language)
    else:
        out = _TABLE_LINE.sub(lambda m: m.group(0).replace("|", ", "), out)

    out = _LINK.sub(lambda m: f"{m.group(1)} ({_friendly_url(m.group(2), language)})", out)
    out = _URL.sub(lambda m: _friendly_url(m.group(0), language), out)
    out = _INLINE_CODE.sub(lambda m: _speak_tech_name(m.group(1)), out)
    out = _HEADING.sub("", out)
    out = _BOLD.sub(r"\2", out)
    out = _ITALIC.sub(r"\2", out)
    out = _BULLET.sub("", out)
    out = _NUMBERED.sub("", out)
    out = out.replace("**", "").replace("__", "")
    out = _MULTI_NL.sub("\n\n", out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r" *\n *", "\n", out).strip()

    if style == "compact":
        out = _compact_trim(out)

    return out.strip()


def split_speakable_segments(text: str, *, max_chars: int = 280) -> list[str]:
    """Split speakable text into ordered sentence-ish segments for queued TTS."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?…])\s+|\n+", cleaned)
    segments: list[str] = []
    buf = ""
    for part in parts:
        piece = part.strip()
        if not piece:
            continue
        if not buf:
            buf = piece
        elif len(buf) + 1 + len(piece) <= max_chars:
            buf = f"{buf} {piece}"
        else:
            segments.append(buf)
            buf = piece
    if buf:
        segments.append(buf)
    return segments


def is_speakable_payload(payload: dict) -> bool:
    """Explicit contract: only payloads marked speakable may be voiced.

    Provisional stream_delta events must NOT pass this check.
    """
    if not isinstance(payload, dict):
        return False
    if payload.get("provisional") is True:
        return False
    if payload.get("speakable") is True:
        return True
    if payload.get("type") in {"final_answer", "speakable_segment", "assistant_final"}:
        return True
    return False


def _code_label(lang: str, language: str) -> str:
    if language.startswith("en"):
        return f"Code block{f' in {lang}' if lang else ''}"
    return f"Codeblok{f' in {lang}' if lang else ''}"


def _code_announce(lang: str, line_count: int, language: str) -> str:
    if language.startswith("en"):
        if lang:
            return f"There is a {lang} code block of about {line_count} lines. I am skipping the full listing."
        return f"There is a code block of about {line_count} lines. I am skipping the full listing."
    if lang:
        return f"Er staat een {lang}-codeblok van ongeveer {line_count} regels. Ik lees de volledige listing niet voor."
    return f"Er staat een codeblok van ongeveer {line_count} regels. Ik lees de volledige listing niet voor."


def _collapse_tables(text: str, language: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_table = False
    rows = 0
    for line in lines:
        if _TABLE_LINE.match(line):
            if not in_table:
                in_table = True
                rows = 0
            rows += 1
            continue
        if in_table:
            in_table = False
            if language.startswith("en"):
                out.append(f"There is a table with about {max(0, rows - 1)} data rows. I am summarizing instead of reading every cell.")
            else:
                out.append(f"Er staat een tabel met ongeveer {max(0, rows - 1)} rijen. Ik lees niet elke cel voor.")
        out.append(line)
    if in_table:
        if language.startswith("en"):
            out.append(f"There is a table with about {max(0, rows - 1)} data rows.")
        else:
            out.append(f"Er staat een tabel met ongeveer {max(0, rows - 1)} rijen.")
    return "\n".join(out)


def _friendly_url(url: str, language: str) -> str:
    clean = url.strip().rstrip(".,;")
    host = clean
    host = re.sub(r"^https?://", "", host)
    host = host.split("/")[0]
    if language.startswith("en"):
        return f"link to {host}"
    return f"link naar {host}"


def _speak_tech_name(name: str) -> str:
    text = name.strip()
    # Keep short identifiers; expand common separators for clarity.
    text = text.replace("_", " ").replace("/", " ")
    return text


def _compact_trim(text: str) -> str:
    # Keep uncertainty / negation markers; only trim excessive length.
    if len(text) <= 1200:
        return text
    cut = text[:1200]
    # Prefer ending on sentence boundary.
    for sep in (". ", "! ", "? ", ".\n"):
        idx = cut.rfind(sep)
        if idx > 600:
            return cut[: idx + 1].strip()
    return cut.rstrip() + "…"
