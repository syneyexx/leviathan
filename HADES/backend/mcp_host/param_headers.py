"""SEP-2243 / MCP 2026-07-28 Mcp-Param-* encoding from x-mcp-header annotations.

Normative encoding (Streamable HTTP transport):
- Visible ASCII (0x20-0x7E) without leading/trailing whitespace → plain
- Non-ASCII, controls, leading/trailing whitespace, or sentinel-shaped values
  → =?base64?{b64(utf-8)}?=
- Only string / integer / boolean primitives; number is forbidden
- Nested annotations reachable only through properties keys
"""

from __future__ import annotations

import base64
import re
from typing import Any

# RFC 9110 tchar for the suffix after Mcp-Param-
_TCHAR_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_JS_SAFE_INT_MIN = -(2**53) + 1
_JS_SAFE_INT_MAX = (2**53) - 1
_SENTINEL_PREFIX = "=?base64?"
_SENTINEL_SUFFIX = "?="
_RESERVED_HEADER_PREFIXES = ("mcp-", "authorization", "content-", "host", "connection")


class McpParamError(ValueError):
    """Invalid x-mcp-header annotation or encoding failure."""


def _is_safe_ascii_header_value(text: str) -> bool:
    if not text:
        return True
    if text[0] in " \t" or text[-1] in " \t":
        return False
    for ch in text:
        code = ord(ch)
        if code < 0x20 or code > 0x7E:
            return False
    return True


def _matches_sentinel_pattern(text: str) -> bool:
    return text.startswith(_SENTINEL_PREFIX) and text.endswith(_SENTINEL_SUFFIX)


def encode_mcp_param_value(value: Any) -> str:
    """Encode a primitive tool argument for an Mcp-Param-* header."""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, int) and not isinstance(value, bool):
        if value < _JS_SAFE_INT_MIN or value > _JS_SAFE_INT_MAX:
            raise McpParamError("integer outside JavaScript safe integer range")
        text = str(value)
    elif isinstance(value, str):
        text = value
    elif isinstance(value, float):
        raise McpParamError("number type is not permitted for x-mcp-header parameters")
    else:
        raise McpParamError(f"unsupported x-mcp-header value type: {type(value).__name__}")

    if _is_safe_ascii_header_value(text) and not _matches_sentinel_pattern(text):
        return text
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"{_SENTINEL_PREFIX}{encoded}{_SENTINEL_SUFFIX}"


def decode_mcp_param_value(header_value: str) -> str:
    """Decode a Mcp-Param header value (for fixtures / validation)."""
    if _matches_sentinel_pattern(header_value):
        raw = header_value[len(_SENTINEL_PREFIX) : -len(_SENTINEL_SUFFIX)]
        try:
            return base64.b64decode(raw.encode("ascii"), validate=True).decode("utf-8")
        except Exception as exc:
            raise McpParamError(f"invalid base64 sentinel: {exc}") from exc
    if not _is_safe_ascii_header_value(header_value):
        raise McpParamError("header value contains invalid characters")
    return header_value


def _validate_header_suffix(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise McpParamError("x-mcp-header must be a non-empty string")
    if any(ord(ch) < 0x20 for ch in name) or "\r" in name or "\n" in name:
        raise McpParamError("x-mcp-header contains control characters")
    if not _TCHAR_RE.match(name):
        raise McpParamError(f"x-mcp-header is not a valid HTTP token: {name!r}")
    return name


def _annotation_type_ok(schema: dict[str, Any]) -> bool:
    expected = schema.get("type")
    types = expected if isinstance(expected, list) else [expected]
    allowed = {"string", "integer", "boolean"}
    return any(t in allowed for t in types if t is not None)


def collect_x_mcp_header_paths(schema: Any) -> list[dict[str, Any]]:
    """Walk inputSchema properties-only paths and collect valid x-mcp-header annotations.

    Returns list of {path: tuple[str,...], header_suffix: str, schema: dict}.
    Raises McpParamError on invalid annotations (caller excludes the tool).
    """
    if not isinstance(schema, dict):
        return []
    found: list[dict[str, Any]] = []
    seen_suffixes: dict[str, str] = {}

    def walk(node: dict[str, Any], path: tuple[str, ...]) -> None:
        props = node.get("properties")
        if not isinstance(props, dict):
            return
        for key, child in props.items():
            if not isinstance(child, dict):
                continue
            child_path = path + (str(key),)
            if "x-mcp-header" in child:
                suffix = _validate_header_suffix(child.get("x-mcp-header"))
                if not _annotation_type_ok(child):
                    raise McpParamError(
                        f"x-mcp-header at {'.'.join(child_path)} must be string|integer|boolean"
                    )
                lower = suffix.lower()
                if lower in seen_suffixes and seen_suffixes[lower] != suffix:
                    raise McpParamError(f"case-colliding x-mcp-header values: {seen_suffixes[lower]!r} vs {suffix!r}")
                if lower in seen_suffixes:
                    raise McpParamError(f"duplicate x-mcp-header value: {suffix!r}")
                seen_suffixes[lower] = suffix
                found.append({"path": child_path, "header_suffix": suffix, "schema": child})
            # Only descend through properties (not items/oneOf/$ref/etc.)
            walk(child, child_path)

    walk(schema, ())
    return found


def value_at_path(arguments: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = arguments
    for part in path:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def build_mcp_param_headers(
    input_schema: Any,
    arguments: dict[str, Any] | None,
    *,
    max_header_bytes: int = 8_000,
) -> dict[str, str]:
    """Build Mcp-Param-* headers for a tools/call from schema annotations + arguments.

    Omits headers when the argument is absent or null.
    """
    args = arguments if isinstance(arguments, dict) else {}
    annotations = collect_x_mcp_header_paths(input_schema)
    headers: dict[str, str] = {}
    for item in annotations:
        raw = value_at_path(args, item["path"])
        if raw is None:
            continue
        suffix = item["header_suffix"]
        header_name = f"Mcp-Param-{suffix}"
        # Prevent override of reserved MCP/protocol headers via crafted suffixes.
        lower = header_name.lower()
        if lower in {"mcp-method", "mcp-name", "mcp-protocol-version", "mcp-session-id", "authorization"}:
            raise McpParamError(f"x-mcp-header collides with reserved header: {header_name}")
        encoded = encode_mcp_param_value(raw)
        if len(encoded.encode("utf-8")) > max_header_bytes:
            raise McpParamError(f"Mcp-Param header too large: {header_name}")
        # Case-insensitive collision check among emitted headers.
        for existing in headers:
            if existing.lower() == lower:
                raise McpParamError(f"duplicate Mcp-Param header after case fold: {header_name}")
        headers[header_name] = encoded
    return headers


def filter_tools_for_http_headers(tools: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Exclude tools with invalid x-mcp-header annotations (HTTP client MUST)."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        schema = tool.get("inputSchema") or tool.get("input_schema")
        try:
            collect_x_mcp_header_paths(schema)
        except McpParamError as exc:
            rejected.append({"name": str(tool.get("name") or ""), "reason": str(exc)})
            continue
        kept.append(tool)
    return kept, rejected
