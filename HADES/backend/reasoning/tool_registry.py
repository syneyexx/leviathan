"""Capability discovery + schema validation for the shared tool engine."""

from __future__ import annotations

import re
from typing import Any, Callable

from plugin_runtime_v2 import eligible_for_autonomous

from .tool_protocol import encode_provider_function_name, openai_tool_schemas
from .tools import DISCOVER_PLUGIN_ID, DISCOVER_TOOL_NAME, _diverse_by_plugin, discover_tools, score_tool_candidate


def validate_against_schema(instance: Any, schema: dict[str, Any] | None) -> list[str]:
    """Minimal JSON-Schema subset validator for tool arguments (no external dep)."""
    if not schema or not isinstance(schema, dict):
        return []
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(instance, dict):
            return ["expected object"]
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if key not in instance:
                errors.append(f"missing required field: {key}")
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in props and isinstance(props[key], dict):
                errors.extend(f"{key}: {err}" for err in validate_against_schema(value, props[key]))
            elif additional is False:
                errors.append(f"unexpected field: {key}")
        return errors
    if expected_type == "array":
        if not isinstance(instance, list):
            return ["expected array"]
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else None
        if item_schema:
            for index, value in enumerate(instance):
                errors.extend(f"[{index}]: {err}" for err in validate_against_schema(value, item_schema))
        return errors
    if expected_type == "string" and not isinstance(instance, str):
        return ["expected string"]
    if expected_type == "integer" and not (isinstance(instance, int) and not isinstance(instance, bool)):
        return ["expected integer"]
    if expected_type == "number":
        if isinstance(instance, bool) or not isinstance(instance, (int, float)):
            return ["expected number"]
    if expected_type == "boolean" and not isinstance(instance, bool):
        return ["expected boolean"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"value not in enum: {schema['enum']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"above maximum {schema['maximum']}")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < int(schema["minLength"]):
            errors.append(f"shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > int(schema["maxLength"]):
            errors.append(f"longer than maxLength {schema['maxLength']}")
    return errors


def exact_tool_mentions(query: str, plugins: list[dict[str, Any]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer tools/plugins the user named explicitly (id, name, aliases, tool name)."""
    lower = (query or "").lower()
    if not lower.strip():
        return []
    plugins_by_id = {item["id"]: item for item in plugins}
    hits: list[dict[str, Any]] = []
    for tool in tools:
        plugin = plugins_by_id.get(tool.get("plugin_id"))
        if not plugin or not tool.get("enabled"):
            continue
        ok, _reason = eligible_for_autonomous(plugin, tool)
        if not ok:
            continue
        names = {
            str(plugin.get("id") or "").lower(),
            str(plugin.get("name") or "").lower(),
            str(tool.get("name") or "").lower(),
        }
        aliases = plugin.get("manifest", {}).get("aliases") if isinstance(plugin.get("manifest"), dict) else None
        if isinstance(aliases, list):
            names.update(str(item).lower() for item in aliases if item)
        labels = plugin.get("labels") if isinstance(plugin.get("labels"), list) else []
        names.update(str(item).lower() for item in labels if item)
        matched = False
        for name in names:
            if not name or len(name) < 3:
                continue
            if re.search(rf"(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])", lower):
                matched = True
                break
        if matched:
            hits.append({**tool, "plugin": plugin, "_exact_mention": True})
    hits.sort(key=lambda item: (str(item.get("plugin_id")), str(item.get("name"))))
    return hits


def shortlist_with_exact_priority(
    *,
    query: str,
    plugins: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    permission_ok: Callable[[dict[str, Any], dict[str, Any]], bool] | None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Exact named tools first, then ranked discovery fill."""
    exact = exact_tool_mentions(query, plugins, tools)
    if permission_ok is not None:
        exact = [item for item in exact if permission_ok(item["plugin"], item)]
    page = discover_tools(
        query=query,
        plugins=plugins,
        tools=tools,
        permission_ok=permission_ok,
        limit=max(limit, 1),
        offset=0,
        include_unscored=False,
    )
    fill_page = page
    if len(page.get("tools") or []) < limit:
        fill_page = discover_tools(
            query=query,
            plugins=plugins,
            tools=tools,
            permission_ok=permission_ok,
            limit=max(limit * 4, 16),
            offset=0,
            include_unscored=True,
        )
    plugins_by_id = {item["id"]: item for item in plugins}

    def _hydrate(plugin_id: str, tool_name: str, source: dict[str, Any] | None = None) -> dict[str, Any] | None:
        plugin = (source or {}).get("plugin") if source else None
        plugin = plugin or plugins_by_id.get(plugin_id)
        tool = next((t for t in tools if t.get("plugin_id") == plugin_id and t.get("name") == tool_name), None)
        if source and source.get("name") and source.get("plugin_id") == plugin_id:
            tool = {**tool, **{k: v for k, v in source.items() if k != "plugin"}} if tool else source
        if not plugin or not tool:
            return None
        return {**tool, "plugin": plugin}

    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for item in exact:
        row = _hydrate(str(item["plugin_id"]), str(item["name"]), item)
        if row:
            by_key[(str(item["plugin_id"]), str(item["name"]))] = row
    for row in page.get("tools") or []:
        key = (str(row["plugin_id"]), str(row["tool_name"]))
        if key in by_key:
            continue
        hydrated = _hydrate(str(row["plugin_id"]), str(row["tool_name"]))
        if hydrated:
            by_key[key] = hydrated

    fill_rows: list[dict[str, Any]] = []
    for row in fill_page.get("tools") or []:
        key = (str(row["plugin_id"]), str(row["tool_name"]))
        if key in by_key:
            continue
        hydrated = _hydrate(str(row["plugin_id"]), str(row["tool_name"]))
        if hydrated:
            fill_rows.append(hydrated)
    for item in _diverse_by_plugin(fill_rows, max(0, limit - len(by_key))):
        by_key[(str(item["plugin_id"]), str(item["name"]))] = item
    ordered: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in exact:
        key = (str(item["plugin_id"]), str(item["name"]))
        if key in by_key and key not in seen:
            ordered.append(by_key[key])
            seen.add(key)
    for row in page.get("tools") or []:
        key = (str(row["plugin_id"]), str(row["tool_name"]))
        if key in by_key and key not in seen:
            ordered.append(by_key[key])
            seen.add(key)
    for item in by_key.values():
        key = (str(item["plugin_id"]), str(item["name"]))
        if key not in seen:
            ordered.append(item)
            seen.add(key)
    return ordered[:limit]


def build_native_tools_payload(
    tools: list[dict[str, Any]],
    *,
    include_discover: bool = True,
    query: str = "",
) -> list[dict[str, Any]]:
    """Build OpenAI-compatible tool schemas for the model.

    First-party Tool Kernel rows must stay bounded but complete. Do not apply
    plugin shortlist truncation (`bound_tools_for_model`) to core-only catalogs —
    that path historically capped at 8 and would drop capability broker tools.
    """
    rows = list(tools)
    try:
        from core_tools.catalog import MAX_MODEL_VISIBLE_TOOLS, is_core_tool
    except Exception:  # pragma: no cover
        MAX_MODEL_VISIBLE_TOOLS = 12

        def is_core_tool(name: str) -> bool:  # type: ignore[misc]
            return str(name or "").startswith("hades.")

    all_core = bool(rows) and all(is_core_tool(str(item.get("name") or "")) for item in rows)
    if not all_core and len(rows) > MAX_MODEL_VISIBLE_TOOLS:
        # Legacy mixed shortlists (should be rare after Tool Kernel migration).
        try:
            from hades_brain.tool_context import bound_tools_for_model

            rows = list(
                bound_tools_for_model(rows, query=query).get("tools")
                or rows[:MAX_MODEL_VISIBLE_TOOLS]
            )
        except Exception:
            rows = rows[:MAX_MODEL_VISIBLE_TOOLS]
    elif len(rows) > MAX_MODEL_VISIBLE_TOOLS:
        rows = rows[:MAX_MODEL_VISIBLE_TOOLS]

    if include_discover:
        search_names = {
            "hades.capabilities.search",
            DISCOVER_TOOL_NAME,
            "hades.discover_tools",
            "hades.discover_plugins",
        }
        already = any(
            str(item.get("plugin_id")) == DISCOVER_PLUGIN_ID and str(item.get("name")) in search_names
            for item in rows
        )
        if not already and len(rows) < MAX_MODEL_VISIBLE_TOOLS:
            rows.append(
                {
                    "plugin_id": DISCOVER_PLUGIN_ID,
                    "name": "hades.capabilities.search",
                    "description": (
                        "Search optional plugin/MCP capabilities by task meaning. "
                        "Then invoke via hades.capabilities.invoke."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                        },
                        "required": ["query"],
                    },
                }
            )
    return openai_tool_schemas(rows)


def resolve_tool_row(
    *,
    plugin_id: str,
    tool_name: str,
    tools: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in tools:
        if item.get("plugin_id") == plugin_id and item.get("name") == tool_name:
            return item
    # Allow lookup via provider function name stored on the row.
    provider = encode_provider_function_name(plugin_id, tool_name)
    for item in tools:
        if encode_provider_function_name(str(item.get("plugin_id")), str(item.get("name"))) == provider:
            return item
    return None


# Re-export score helper for callers that already import registry helpers.
score_candidate = score_tool_candidate
