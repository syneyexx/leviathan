"""Bounded JSON repair for local-model tool/critic/classifier output.

Strict ``json.loads`` first. Only apply small, documented repairs when that
fails. Never invent object keys or success flags.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_PY_TRUE = re.compile(r"\bTrue\b")
_PY_FALSE = re.compile(r"\bFalse\b")
_PY_NONE = re.compile(r"\bNone\b")
_SMART_QUOTES = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "‘": "'",
        "’": "'",
    }
)
# Unquoted object keys immediately after { or , — not applied inside strings
# because we only run this after json.loads already failed.
_UNQUOTED_KEY = re.compile(r'([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)')


def extract_json_candidates(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    candidates: list[str] = []
    fenced = re.findall(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.S | re.I)
    candidates.extend(item.strip() for item in fenced if item and item.strip())
    candidates.append(raw)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start >= 0 and end > start:
            snippet = raw[start : end + 1].strip()
            if snippet not in candidates:
                candidates.append(snippet)
    # Preserve order, drop empties / duplicates.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _strip_trailing_commas(text: str) -> str:
    previous = text
    for _ in range(4):
        updated = _TRAILING_COMMA.sub(r"\1", previous)
        if updated == previous:
            return updated
        previous = updated
    return previous


def _python_literals_to_json(text: str) -> str:
    return _PY_NONE.sub("null", _PY_FALSE.sub("false", _PY_TRUE.sub("true", text)))


def _quote_simple_keys(text: str) -> str:
    return _UNQUOTED_KEY.sub(r'\1"\2"\3', text)


def _repair_variants(text: str) -> list[str]:
    smart = text.translate(_SMART_QUOTES)
    variants = [text]
    if smart != text:
        variants.append(smart)
    out: list[str] = []
    seen: set[str] = set()
    for base in variants:
        for candidate in (
            base,
            _strip_trailing_commas(base),
            _python_literals_to_json(base),
            _strip_trailing_commas(_python_literals_to_json(base)),
            _quote_simple_keys(base),
            _strip_trailing_commas(_quote_simple_keys(_python_literals_to_json(base))),
        ):
            if candidate and candidate not in seen:
                seen.add(candidate)
                out.append(candidate)
    return out


def loads_json_value(text: str) -> Any | None:
    """Parse a JSON value with bounded repairs. Returns None when unsalvageable."""
    for candidate in extract_json_candidates(text):
        for variant in _repair_variants(candidate):
            try:
                return json.loads(variant)
            except Exception:
                continue
        # Last resort: Python literal dict/list (single quotes, True/False/None).
        for variant in _repair_variants(candidate):
            try:
                parsed = ast.literal_eval(variant)
            except Exception:
                continue
            if isinstance(parsed, (dict, list, str, int, float, bool)) or parsed is None:
                return parsed
    return None


def loads_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object. Unwraps one extra JSON-encoded string layer."""
    parsed = loads_json_value(text)
    if isinstance(parsed, str):
        inner = loads_json_value(parsed)
        parsed = inner
    if isinstance(parsed, dict):
        return parsed
    return None
