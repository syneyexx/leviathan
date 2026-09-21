"""XML capability-call parser for CodingLoop (LM Studio–friendly)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_CAP_RE = re.compile(
    r"<capability\s+id=[\"'](?P<id>[^\"']+)[\"']\s*>(?P<body>.*?)</capability>",
    re.IGNORECASE | re.DOTALL,
)
_ARG_RE = re.compile(
    r"<arg\s+name=[\"'](?P<name>[^\"']+)[\"']\s*>(?P<value>.*?)</arg>",
    re.IGNORECASE | re.DOTALL,
)
# Also accept self-closing / JSON-ish arg forms lightly via name= content=
_ARG_ATTR_RE = re.compile(
    r"<arg\s+name=[\"'](?P<name>[^\"']+)[\"']\s+value=[\"'](?P<value>.*?)[\"']\s*/>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class ParsedCapability:
    capability_id: str
    arguments: dict[str, Any]


def _coerce(value: str) -> Any:
    text = value.strip()
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except ValueError:
            return text
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def extract_capabilities(text: str) -> list[ParsedCapability]:
    """Extract capability tags from assistant text (fenced or unfenced)."""
    # Strip markdown fences around tags without requiring them.
    cleaned = text.replace("```xml", "").replace("```", "")
    found: list[ParsedCapability] = []
    for match in _CAP_RE.finditer(cleaned):
        cap_id = match.group("id").strip()
        body = match.group("body")
        args: dict[str, Any] = {}
        for am in _ARG_ATTR_RE.finditer(body):
            args[am.group("name")] = _coerce(am.group("value"))
        for am in _ARG_RE.finditer(body):
            args[am.group("name")] = _coerce(am.group("value"))
        found.append(ParsedCapability(capability_id=cap_id, arguments=args))
    return found


def strip_capabilities(text: str) -> str:
    """Remove capability XML from user-visible assistant text."""
    cleaned = _CAP_RE.sub("", text)
    # Collapse excess blank lines left by removals.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned
