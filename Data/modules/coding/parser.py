"""XML + schema-constrained native capability-call parser (U201)."""

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


def _from_json_obj(obj: dict[str, Any]) -> ParsedCapability | None:
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


def extract_structured_capabilities(text: str) -> list[ParsedCapability]:
    """Parse schema-constrained JSON capability calls (native path)."""
    found: list[ParsedCapability] = []
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text or "", re.IGNORECASE):
        body = match.group(1).strip()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and ("calls" in item or "capabilities" in item):
                for sub in item.get("calls") or item.get("capabilities") or []:
                    if isinstance(sub, dict):
                        parsed = _from_json_obj(sub)
                        if parsed:
                            found.append(parsed)
            elif isinstance(item, dict):
                parsed = _from_json_obj(item)
                if parsed:
                    found.append(parsed)
    if not found:
        for match in re.finditer(
            r"\{[^{}]*\"(?:capability_id|capability|tool)\"[^{}]*\}",
            text or "",
        ):
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                parsed = _from_json_obj(data)
                if parsed:
                    found.append(parsed)
    return found


def extract_capabilities(text: str) -> list[ParsedCapability]:
    """Extract capability calls — prefer JSON native, fall back to XML (U201)."""
    structured = extract_structured_capabilities(text)
    if structured:
        return structured
    cleaned = (text or "").replace("```xml", "").replace("```", "")
    found: list[ParsedCapability] = []
    for match in _CAP_RE.finditer(cleaned):
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
