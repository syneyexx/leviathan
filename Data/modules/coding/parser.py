"""XML + schema-constrained native capability-call parser (U201).

Ordinary prose containing JSON examples MUST NOT execute.
Prefer explicit execute envelopes or capability XML tags.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .types import ParsedCapability


_CAP_RE = re.compile(
    r"<capability\s+id=[\"'](?P<id>[^\"']+)[\"']\s*>(?P<body>.*?)</capability>",
    re.IGNORECASE | re.DOTALL,
)
_ARG_RE = re.compile(
    r"<arg\s+name=[\"'](?P<name>[^\"']+)[\"']\s*>(?P<value>.*?)</arg>",
    re.IGNORECASE | re.DOTALL,
)
_ARG_ATTR_RE = re.compile(
    r"<arg\s+name=[\"'](?P<name>[^\"']+)[\"']\s+value=[\"'](?P<value>.*?)[\"']\s*/>",
    re.IGNORECASE | re.DOTALL,
)

_DISCLAIMER_RE = re.compile(
    r"(do\s+not\s+execute|don't\s+execute|example\s*[:;]|for\s+illustration|"
    r"here\s+is\s+an\s+example|sample\s+payload|pseudo[- ]?code)",
    re.IGNORECASE,
)

_EXECUTE_ENVELOPE_KEYS = frozenset(
    {
        "leviathan_tool_call",
        "leviathan_capability_call",
        "execute",
    }
)


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


def _from_json_obj(obj: dict[str, Any], *, require_execute_flag: bool) -> ParsedCapability | None:
    if require_execute_flag:
        # Explicit envelope: execute:true OR leviathan_*_call:true
        flagged = False
        if obj.get("execute") is True:
            flagged = True
        for key in ("leviathan_tool_call", "leviathan_capability_call"):
            if obj.get(key) is True:
                flagged = True
        if not flagged:
            return None
    cap_id = obj.get("capability_id") or obj.get("capability") or obj.get("tool") or obj.get("name")
    if not cap_id:
        return None
    args = obj.get("arguments") or obj.get("args") or obj.get("input") or {}
    if not isinstance(args, dict):
        return None
    return ParsedCapability(
        capability_id=str(cap_id).strip(),
        arguments=dict(args),
        raw="",
        source="json",
    )


def _has_disclaimer_before(text: str, pos: int, *, window: int = 240) -> bool:
    start = max(0, pos - window)
    return bool(_DISCLAIMER_RE.search(text[start:pos]))


def extract_structured_capabilities(text: str) -> list[ParsedCapability]:
    """Parse schema-constrained JSON capability calls (native path).

    Rules:
    - Fenced ```json blocks with capability_id/tool are accepted UNLESS preceded
      by an explicit non-execution disclaimer ("do not execute", "example:", …).
    - Objects inside fences that set execute:false are skipped.
    - Bare inline JSON in prose is NEVER executable (no regex side effects).
    - Explicit envelopes (execute:true / leviathan_tool_call:true) always win
      inside fences even alongside disclaimers only when execute is true and
      no disclaimer is present.
    """
    found: list[ParsedCapability] = []
    raw = text or ""
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE):
        if _has_disclaimer_before(raw, match.start()):
            continue
        body = match.group(1).strip()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("execute") is False:
                continue
            if "calls" in item or "capabilities" in item:
                for sub in item.get("calls") or item.get("capabilities") or []:
                    if isinstance(sub, dict):
                        # Nested calls inherit fence trust unless execute:false.
                        if sub.get("execute") is False:
                            continue
                        parsed = _from_json_obj(sub, require_execute_flag=False)
                        if parsed:
                            found.append(parsed)
            else:
                # Top-level fenced object: accept native capability shape.
                # If only "tool" without capability_id and without execute flag,
                # still accept inside fences (coding agent contract) unless
                # execute:false already handled.
                parsed = _from_json_obj(item, require_execute_flag=False)
                if parsed:
                    found.append(parsed)
    # Intentionally NO bare-prose JSON regex extraction — explanatory examples
    # like {"tool":"file.delete",...} in ordinary text must not execute.
    _ = _EXECUTE_ENVELOPE_KEYS  # documented contract surface
    return found


def extract_capabilities(text: str) -> list[ParsedCapability]:
    """Extract capability calls — prefer JSON native, fall back to XML (U201)."""
    structured = extract_structured_capabilities(text)
    if structured:
        return structured
    cleaned = (text or "").replace("```xml", "").replace("```", "")
    found: list[ParsedCapability] = []
    for match in _CAP_RE.finditer(cleaned):
        if _has_disclaimer_before(cleaned, match.start()):
            continue
        cap_id = match.group("id").strip()
        body = match.group("body")
        args: dict[str, Any] = {}
        for am in _ARG_ATTR_RE.finditer(body):
            args[am.group("name")] = _coerce(am.group("value"))
        for am in _ARG_RE.finditer(body):
            args[am.group("name")] = _coerce(am.group("value"))
        found.append(
            ParsedCapability(
                capability_id=cap_id,
                arguments=args,
                raw=match.group(0),
                source="xml",
            )
        )
    return found


def strip_capabilities(text: str) -> str:
    """Remove capability XML/JSON fences from user-visible assistant text."""
    cleaned = _CAP_RE.sub("", text or "")
    cleaned = re.sub(r"```(?:json)?\s*\{[\s\S]*?\}\s*```", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned
