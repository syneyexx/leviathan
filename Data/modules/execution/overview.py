"""Bounded Tools overview projection — composes canonical authorities.

No state ownership. No second CapabilityCatalog / receipt store.
"""

from __future__ import annotations

from typing import Any

from .presentation import (
    category_key,
    category_label,
    list_item_projection,
    resolve_origin,
    source_label,
    tool_version,
)


def plugin_bound_capability_ids(plugin_registry: Any) -> set[str]:
    ids: set[str] = set()
    if plugin_registry is None:
        return ids
    try:
        plugins = plugin_registry.list()
    except Exception:  # noqa: BLE001
        return ids
    for plugin in plugins:
        for binding in getattr(plugin, "bindings", ()) or ():
            cap_id = getattr(binding, "capability_id", None)
            if cap_id:
                ids.add(str(cap_id))
    return ids


def build_tools_overview(
    *,
    capability_catalog: Any,
    capability_receipts: Any,
    plugin_registry: Any = None,
    mcp_bridge: Any = None,
    function_registry: Any = None,
    period_days: int = 7,
) -> dict[str, Any]:
    items = capability_catalog.list() if capability_catalog is not None else []
    plugin_ids = plugin_bound_capability_ids(plugin_registry)
    categories: set[str] = set()
    origin_counts: dict[str, int] = {
        "core": 0,
        "plugin": 0,
        "mcp": 0,
        "function": 0,
        "module": 0,
        "external": 0,
        "custom": 0,
        "other": 0,
    }
    active = 0
    inactive = 0
    unavailable = 0

    version_fallbacks: dict[str, str] = {}
    if function_registry is not None:
        try:
            for fn in function_registry.list():
                version_fallbacks[str(fn.id)] = str(fn.version)
        except Exception:  # noqa: BLE001
            pass

    for item in items:
        meta = item.normalized_metadata()
        categories.add(category_key(meta, capability_id=item.id))
        provider_kind = item.provider_kind.value
        origin = resolve_origin(
            meta,
            provider_kind=provider_kind,
            in_plugin_bindings=item.id in plugin_ids,
        )
        if origin in origin_counts:
            origin_counts[origin] += 1
        else:
            origin_counts["other"] += 1
        if item.available and item.enabled:
            active += 1
        elif not item.enabled:
            inactive += 1
        else:
            unavailable += 1

    # MCP tools: durable bridge records (dedupe on capability_id).
    mcp_tools_total = 0
    mcp_tools_available = 0
    mcp_servers: list[dict[str, Any]] = []
    mcp_stale = False
    mcp_error: str | None = None
    if mcp_bridge is not None:
        try:
            tools = mcp_bridge.list_tools() if hasattr(mcp_bridge, "list_tools") else []
            seen: set[str] = set()
            for tool in tools:
                cap_id = str(getattr(tool, "capability_id", "") or "")
                key = cap_id or f"{getattr(tool, 'server_id', '')}:{getattr(tool, 'external_name', '')}"
                if key in seen:
                    continue
                seen.add(key)
                mcp_tools_total += 1
                availability = str(getattr(tool, "availability", "") or "").lower()
                if availability in {"available", "AVAILABLE".lower()}:
                    mcp_tools_available += 1
            servers = mcp_bridge.list_servers() if hasattr(mcp_bridge, "list_servers") else []
            for server in servers:
                public = server.public_dict() if hasattr(server, "public_dict") else dict(server)
                runtime = public.get("runtime") or {}
                mcp_servers.append(
                    {
                        "server_id": public.get("server_id"),
                        "display_name": public.get("display_name") or public.get("server_id"),
                        "enabled": public.get("enabled"),
                        "transport": public.get("transport"),
                        "connection": runtime.get("state") or public.get("state") or "unknown",
                        "tool_count": runtime.get("tool_count", public.get("tool_count", 0)),
                        "last_seen_at": runtime.get("last_seen_at") or public.get("last_seen_at"),
                        "last_error_message": runtime.get("last_error_message"),
                        "url": public.get("url"),
                        "command": public.get("command"),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            mcp_stale = True
            mcp_error = str(exc)

    # Plugin panel projection.
    plugins: list[dict[str, Any]] = []
    plugins_stale = False
    plugins_error: str | None = None
    plugin_tool_count = len(plugin_ids)
    if plugin_registry is not None:
        try:
            for plugin in plugin_registry.list():
                bindings = list(getattr(plugin, "bindings", ()) or ())
                status = getattr(getattr(plugin, "status", None), "value", getattr(plugin, "status", None))
                plugins.append(
                    {
                        "plugin_id": plugin.plugin_id,
                        "name": plugin.name,
                        "status": status,
                        "status_label": _plugin_status_label(str(status or "")),
                        "tool_count": len(bindings),
                        "version": plugin.version,
                        "kind": getattr(getattr(plugin, "kind", None), "value", None),
                        "error": getattr(plugin, "error", None),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            plugins_stale = True
            plugins_error = str(exc)
            plugin_tool_count = 0 if not plugin_ids else len(plugin_ids)

    # Custom tools: explicit origin only (never inferred remainder).
    custom_tool_count = origin_counts.get("custom", 0)

    # Receipt success ratio + spark.
    ratio = {"unmeasured": True, "success_ratio": None, "delta_pp": None, "spark_buckets": []}
    receipts_stale = False
    receipts_error: str | None = None
    recent_calls: list[dict[str, Any]] = []
    if capability_receipts is not None:
        try:
            ratio = capability_receipts.success_ratio_periods(days=period_days)
            for receipt in capability_receipts.recent(limit=25):
                recent_calls.append(_recent_call_row(receipt, capability_catalog))
        except Exception as exc:  # noqa: BLE001
            receipts_stale = True
            receipts_error = str(exc)

    success_ratio = ratio.get("success_ratio")
    success_display = None if success_ratio is None else round(float(success_ratio) * 100, 1)
    delta_pp = ratio.get("delta_pp")

    # Category spark / counts for KPI cards — truthful, not fabricated history.
    spark_success = [
        int(bucket.get("completed") or 0)
        for bucket in (ratio.get("current", {}) or {}).get("spark_buckets")
        or ratio.get("spark_buckets")
        or []
    ]

    return {
        "total_capabilities": len(items),
        "active_capabilities": active,
        "inactive_capabilities": inactive,
        "unavailable_capabilities": unavailable,
        "category_count": len(categories),
        "categories": sorted(
            [{"key": key, "label": category_label(key)} for key in categories],
            key=lambda row: row["label"],
        ),
        "plugin_tool_count": plugin_tool_count,
        "mcp_tool_count": mcp_tools_total,
        "mcp_tools_available": mcp_tools_available,
        "custom_tool_count": custom_tool_count,
        "origin_counts": origin_counts,
        "success_ratio": success_ratio,
        "success_ratio_pct": success_display,
        "success_ratio_delta_pp": delta_pp,
        "success_ratio_unmeasured": bool(ratio.get("unmeasured") or success_ratio is None),
        "spark": {
            "success": spark_success,
            "total_tools": [],  # no durable registration history
            "plugin": [],
            "mcp": [],
            "custom": [],
            "categories": [],
        },
        "mcp_servers": mcp_servers,
        "plugins": plugins,
        "recent_calls": recent_calls,
        "period_days": period_days,
        "coverage": {
            "mcp_stale": mcp_stale,
            "mcp_error": mcp_error,
            "plugins_stale": plugins_stale,
            "plugins_error": plugins_error,
            "receipts_stale": receipts_stale,
            "receipts_error": receipts_error,
            "registration_history_unmeasured": True,
        },
        "truth": {
            "overview_composes_canonical_authorities": True,
            "custom_is_explicit_origin_only": True,
            "plugin_count_from_bindings": True,
            "mcp_count_from_bridge": True,
            "success_excludes_rejected_cancelled": True,
            "no_fixture_fallback": True,
        },
    }


def build_tools_library(
    *,
    capability_catalog: Any,
    capability_receipts: Any = None,
    plugin_registry: Any = None,
    function_registry: Any = None,
    q: str | None = None,
    category: str | None = None,
    source: str | None = None,
    sort: str = "name",
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    plugin_ids = plugin_bound_capability_ids(plugin_registry)
    if q and str(q).strip():
        items = capability_catalog.search(str(q).strip(), limit=max(limit + offset, limit))
    else:
        items = capability_catalog.list()

    version_fallbacks: dict[str, str] = {}
    if function_registry is not None:
        try:
            for fn in function_registry.list():
                version_fallbacks[str(getattr(fn, "provider_ref", None) or fn.id)] = str(fn.version)
                version_fallbacks[str(fn.id)] = str(fn.version)
        except Exception:  # noqa: BLE001
            pass

    last_used: dict[str, str] = {}
    if capability_receipts is not None:
        try:
            last_used = capability_receipts.latest_by_capability([item.id for item in items])
        except Exception:  # noqa: BLE001
            last_used = {}

    rows = []
    for item in items:
        meta = item.normalized_metadata()
        provider_kind = item.provider_kind.value
        origin = resolve_origin(meta, provider_kind=provider_kind, in_plugin_bindings=item.id in plugin_ids)
        cat = category_key(meta, capability_id=item.id)
        if category and category not in {"all", "", "*"} and cat != category.lower():
            # Also allow label match.
            if category_label(cat).lower() != category.lower():
                continue
        if source and source not in {"all", "", "*"} and origin != source.lower():
            continue
        fb = None
        if item.provider_kind.value == "function":
            fb = version_fallbacks.get(str(item.provider_ref)) or version_fallbacks.get(item.id)
        rows.append(
            list_item_projection(
                item,
                plugin_capability_ids=plugin_ids,
                last_used_at=last_used.get(item.id),
                version_fallback=fb,
            )
        )

    reverse = sort.startswith("-")
    key = sort[1:] if reverse else sort
    sort_key_map = {
        "name": lambda r: (r.get("name") or r.get("id") or "").lower(),
        "category": lambda r: (r.get("category_label") or "").lower(),
        "source": lambda r: (r.get("source_label") or "").lower(),
        "status": lambda r: (r.get("status_label") or "").lower(),
        "version": lambda r: (r.get("version") or ""),
        "last_used": lambda r: r.get("last_used_at") or "",
    }
    rows.sort(key=sort_key_map.get(key, sort_key_map["name"]), reverse=reverse)

    total = len(rows)
    sliced = rows[offset : offset + limit]
    return {
        "tools": sliced,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
        "filters": {
            "q": q,
            "category": category,
            "source": source,
            "sort": sort,
        },
        "truth": {
            "bounded_projection": True,
            "last_used_from_receipts": True,
        },
    }


def build_capability_detail_projection(
    *,
    definition: Any,
    capability_receipts: Any = None,
    plugin_registry: Any = None,
    mcp_bridge: Any = None,
    function_registry: Any = None,
    receipt_limit: int = 50,
) -> dict[str, Any]:
    plugin_ids = plugin_bound_capability_ids(plugin_registry)
    summary = list_item_projection(
        definition,
        plugin_capability_ids=plugin_ids,
        last_used_at=None,
    )
    usage = None
    recent = []
    if capability_receipts is not None:
        usage = capability_receipts.aggregate_for_capability(definition.id)
        latest = capability_receipts.latest_by_capability([definition.id])
        summary["last_used_at"] = latest.get(definition.id)
        recent = [
            _recent_call_row(item, None)
            for item in capability_receipts.recent_for_capability(definition.id, limit=receipt_limit)
        ]

    deps = _dependency_projection(
        definition,
        plugin_registry=plugin_registry,
        mcp_bridge=mcp_bridge,
        function_registry=function_registry,
    )
    providers = _provider_projection(definition, usage=usage, mcp_bridge=mcp_bridge)
    examples = _example_projection(definition)

    return {
        "capability": definition.public_dict(),
        "summary": summary,
        "usage": usage,
        "providers": providers,
        "recent_receipts": recent,
        "dependencies": deps,
        "examples": examples,
        "editability": _editability(definition, plugin_ids=plugin_ids),
        "testability": _testability(definition),
        "truth": {
            "detail_is_projection": True,
            "schemas_provider_owned": True,
        },
    }


def _plugin_status_label(status: str) -> str:
    s = status.upper()
    if s == "ENABLED":
        return "Actief"
    if s == "DISABLED":
        return "Inactief"
    if s == "ERROR":
        return "Fout"
    if s == "REGISTERED":
        return "Geregistreerd"
    return status or "—"


def _recent_call_row(receipt: Any, catalog: Any) -> dict[str, Any]:
    public = receipt.public_dict() if hasattr(receipt, "public_dict") else dict(receipt)
    cap_id = str(public.get("capability_id") or "")
    name = cap_id
    if catalog is not None:
        item = catalog.get(cap_id) if hasattr(catalog, "get") else None
        if item is not None:
            name = item.name or cap_id
    status = str(public.get("status") or "")
    return {
        "receipt_id": public.get("receipt_id"),
        "request_id": public.get("request_id"),
        "capability_id": cap_id,
        "tool_name": name,
        "status": status,
        "status_label": _receipt_status_label(status),
        "latency_ms": public.get("latency_ms"),
        "recorded_at": public.get("recorded_at"),
        "requested_by": public.get("requested_by") or (public.get("metadata") or {}).get("requested_by"),
        "provider_kind": public.get("provider_kind"),
        "provider_ref": public.get("provider_ref"),
        "error": public.get("error"),
        "run_id": public.get("run_id"),
        "job_id": public.get("job_id"),
    }


def _receipt_status_label(status: str) -> str:
    s = status.upper()
    if s == "COMPLETED":
        return "Succes"
    if s == "FAILED":
        return "Fout"
    if s == "TIMEOUT":
        return "Timeout"
    if s == "REJECTED":
        return "Afgewezen"
    if s == "CANCELLED":
        return "Geannuleerd"
    return status or "—"


def _dependency_projection(
    definition: Any,
    *,
    plugin_registry: Any,
    mcp_bridge: Any,
    function_registry: Any,
) -> dict[str, Any]:
    meta = definition.normalized_metadata()
    deps: list[dict[str, Any]] = [
        {
            "kind": "provider",
            "label": "Provider",
            "value": f"{definition.provider_kind.value}:{definition.provider_ref}",
        },
        {
            "kind": "execution_class",
            "label": "Execution class",
            "value": definition.execution_class(),
        },
    ]
    if definition.required_permissions:
        deps.append(
            {
                "kind": "permissions",
                "label": "Required permissions",
                "value": list(definition.required_permissions),
            }
        )
    if meta.get("worker_kind"):
        deps.append({"kind": "worker", "label": "Worker kind", "value": meta.get("worker_kind")})
    if meta.get("wraps_capability_id") or meta.get("delegates_to"):
        deps.append(
            {
                "kind": "wraps",
                "label": "Wraps capability",
                "value": meta.get("wraps_capability_id") or meta.get("delegates_to"),
            }
        )
    if definition.provider_kind.value == "mcp" and mcp_bridge is not None:
        try:
            tools = mcp_bridge.list_tools() if hasattr(mcp_bridge, "list_tools") else []
            for tool in tools:
                if getattr(tool, "capability_id", None) == definition.id:
                    deps.append(
                        {
                            "kind": "mcp_server",
                            "label": "MCP server",
                            "value": getattr(tool, "server_id", None),
                        }
                    )
                    deps.append(
                        {
                            "kind": "mcp_tool",
                            "label": "MCP tool",
                            "value": getattr(tool, "external_name", None),
                        }
                    )
                    break
        except Exception:  # noqa: BLE001
            pass
    if plugin_registry is not None:
        try:
            for plugin in plugin_registry.list():
                for binding in plugin.bindings:
                    if binding.capability_id == definition.id:
                        deps.append(
                            {
                                "kind": "plugin",
                                "label": "Plugin",
                                "value": plugin.plugin_id,
                                "version": plugin.version,
                                "status": plugin.status.value,
                            }
                        )
        except Exception:  # noqa: BLE001
            pass
    if definition.provider_kind.value == "function" and function_registry is not None:
        try:
            fn = function_registry.get(definition.provider_ref)
            if fn is not None:
                deps.append(
                    {
                        "kind": "function",
                        "label": "Function",
                        "value": fn.id,
                        "version": fn.version,
                        "entrypoint": fn.entrypoint,
                    }
                )
        except Exception:  # noqa: BLE001
            pass
    side = [e.value if hasattr(e, "value") else str(e) for e in definition.side_effects]
    deps.append({"kind": "side_effects", "label": "Side effects", "value": side})
    return {"items": deps, "side_effects": side}


def _provider_projection(
    definition: Any,
    *,
    usage: dict[str, Any] | None,
    mcp_bridge: Any,
) -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    if usage and usage.get("providers"):
        for row in usage["providers"]:
            providers.append(
                {
                    "name": row.get("provider"),
                    "calls": row.get("calls"),
                    "completed": row.get("completed"),
                    "state": "measured",
                }
            )
    if not providers:
        providers.append(
            {
                "name": definition.provider_ref or definition.provider_kind.value,
                "kind": definition.provider_kind.value,
                "calls": (usage or {}).get("total_calls"),
                "state": "available" if definition.available else "unavailable",
            }
        )
    return providers


def _example_projection(definition: Any) -> dict[str, Any]:
    meta = definition.normalized_metadata()
    examples = meta.get("examples")
    if examples:
        return {"source": "metadata", "label": "Provider-defined", "examples": examples}
    # Deterministic schema-derived example.
    schema = definition.input_schema or {}
    props = schema.get("properties") if isinstance(schema, dict) else None
    required = set(schema.get("required") or []) if isinstance(schema, dict) else set()
    args: dict[str, Any] = {}
    if isinstance(props, dict):
        for name, spec in props.items():
            if not isinstance(spec, dict):
                continue
            if "default" in spec:
                args[name] = spec["default"]
            elif name in required or len(args) < 3:
                args[name] = _example_value(spec)
    return {
        "source": "schema_derived",
        "label": "Gegenereerd uit schema",
        "examples": [
            {
                "arguments": args,
                "output_schema": definition.output_schema,
            }
        ],
    }


def _example_value(spec: dict[str, Any]) -> Any:
    if "enum" in spec and isinstance(spec["enum"], list) and spec["enum"]:
        return spec["enum"][0]
    t = spec.get("type")
    if t == "string":
        return spec.get("examples", ["example"])[0] if isinstance(spec.get("examples"), list) else "example"
    if t == "integer":
        return int(spec.get("minimum", 1) or 1)
    if t == "number":
        return float(spec.get("minimum", 1.0) or 1.0)
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        return {}
    return None


def _editability(definition: Any, *, plugin_ids: set[str]) -> dict[str, Any]:
    meta = definition.normalized_metadata()
    origin = resolve_origin(
        meta,
        provider_kind=definition.provider_kind.value,
        in_plugin_bindings=definition.id in plugin_ids,
    )
    if origin == "custom":
        return {
            "editable": True,
            "mode": "custom",
            "reason": None,
        }
    if definition.provider_kind.value == "mcp":
        return {
            "editable": False,
            "mode": "mcp",
            "reason": "Schema wordt beheerd door MCP",
            "navigate": "/mcp",
        }
    if origin == "plugin":
        return {
            "editable": False,
            "mode": "plugin",
            "reason": "Schema wordt beheerd door PluginRegistry",
            "navigate": "/modules",
        }
    if definition.provider_kind.value == "module":
        return {
            "editable": False,
            "mode": "module",
            "reason": "Schema wordt beheerd door ModuleManager",
            "navigate": "/modules",
        }
    return {
        "editable": False,
        "mode": "core",
        "reason": f"Schema wordt beheerd door {definition.provider_kind.value}",
    }


def _testability(definition: Any) -> dict[str, Any]:
    side = {e.value if hasattr(e, "value") else str(e) for e in definition.side_effects}
    dangerous = side & {"WRITE", "EXECUTE", "DELETE", "DESTRUCTIVE", "EXTERNAL_SIDE_EFFECT"}
    if not definition.available or not definition.enabled:
        return {
            "allowed": False,
            "mode": "blocked",
            "reason": definition.availability_reason or "Capability unavailable or disabled",
        }
    if dangerous:
        return {
            "allowed": False,
            "mode": "protected",
            "reason": (
                "Test geblokkeerd: capability heeft side effects "
                + ", ".join(sorted(dangerous))
                + ". Gebruik dry-run/approval of voer uit via een geautoriseerde flow."
            ),
            "side_effects": sorted(dangerous),
        }
    return {
        "allowed": True,
        "mode": "live",
        "reason": None,
        "side_effects": sorted(side),
    }
