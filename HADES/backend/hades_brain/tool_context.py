"""MCP tool/schema context discipline: metadata first, full schemas for a shortlist only."""

from __future__ import annotations

import hashlib
import re
from typing import Any

_TOKEN = re.compile(r"[a-zA-Z0-9_.-]+")

DEFAULT_MAX_FULL_SCHEMAS = 8
DEFAULT_MAX_METADATA = 24

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in _TOKEN.findall(text or "") if len(item) > 1}


def metadata_row(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    return {
        "plugin_id": tool.get("plugin_id") or tool.get("server_id"),
        "name": tool.get("name") or tool.get("remote_name") or tool.get("tool_name"),
        "description": str(tool.get("description") or "")[:240],
        "property_names": sorted(str(key) for key in props.keys())[:12],
        "full_schema": False,
    }


def score_tool(query: str, tool: dict[str, Any]) -> float:
    q = _tokens(query)
    hay = _tokens(" ".join(str(tool.get(key) or "") for key in ("name", "tool_name", "remote_name", "description", "plugin_id")))
    if not q:
        return 0.01
    overlap = len(q & hay)
    if overlap:
        return overlap / max(len(q), 1)
    return 0.0


def cache_key(*, server_id: str, version: str, session: str, tool_name: str) -> str:
    raw = f"{server_id}|{version}|{session}|{tool_name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def cache_schema(key: str, schema: dict[str, Any]) -> None:
    _SCHEMA_CACHE[key] = dict(schema)


def get_cached_schema(key: str) -> dict[str, Any] | None:
    item = _SCHEMA_CACHE.get(key)
    return dict(item) if item else None


def reset_schema_cache() -> None:
    _SCHEMA_CACHE.clear()


def bound_tools_for_model(
    tools: list[dict[str, Any]],
    *,
    query: str = "",
    max_full_schemas: int = DEFAULT_MAX_FULL_SCHEMAS,
    max_metadata: int = DEFAULT_MAX_METADATA,
) -> dict[str, Any]:
    """Return a bounded tool context for a model.

    Full input schemas are attached only to the shortlisted candidates.
    Remaining tools are omitted (not dumped as metadata-only catalogs) so a
    200-tool MCP server cannot fill the prompt.
    """
    ranked = sorted(((score_tool(query, item), index, item) for index, item in enumerate(tools)), key=lambda row: (-row[0], row[1]))
    if query.strip():
        matched = [row for row in ranked if row[0] > 0]
        if len(matched) < max(1, max_full_schemas):
            seen = {id(row[2]) for row in matched}
            fillers = [row for row in ranked if id(row[2]) not in seen]
            ranked = (matched + fillers)[: max(1, max_full_schemas)]
        else:
            ranked = matched
    shortlist = [item for _score, _idx, item in ranked[: max(1, max_full_schemas)]]
    metadata_pool = [metadata_row(item) for _score, _idx, item in ranked[:max_metadata]]
    hydrated: list[dict[str, Any]] = []
    for item in shortlist:
        row = dict(item)
        schema = row.get("input_schema") if isinstance(row.get("input_schema"), dict) else {"type": "object", "properties": {}}
        server_id = str(row.get("plugin_id") or row.get("server_id") or "")
        version = str(row.get("version") or row.get("server_version") or "")
        session = str(row.get("session_id") or "")
        name = str(row.get("name") or row.get("tool_name") or "")
        key = cache_key(server_id=server_id, version=version, session=session, tool_name=name)
        cached = get_cached_schema(key)
        if cached is None:
            cache_schema(key, schema)
            cached = schema
        row["input_schema"] = cached
        row["full_schema"] = True
        hydrated.append(row)
    return {
        "tools": hydrated,
        "shortlist_count": len(hydrated),
        "considered": len(tools),
        "omitted": max(0, len(tools) - len(hydrated)),
        "metadata_candidates": metadata_pool[:max_full_schemas],
        "full_schema_limit": max_full_schemas,
        "model_called": False,
        "tool_schema_load_count": len(hydrated),
    }
