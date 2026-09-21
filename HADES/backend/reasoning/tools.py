from __future__ import annotations

import json
import re
from typing import Any, Callable

from plugin_runtime_v2 import (
    build_capability_contract,
    eligible_for_autonomous,
    score_agent_tool,
)

from .contracts import ToolCallRequest, ToolObservation

TOOL_CALL_KEY = "hades_tool_call"
DISCOVER_TOOL_NAME = "hades.discover_plugins"
CAPABILITIES_SEARCH_TOOL = "hades.capabilities.search"
CAPABILITIES_INSPECT_TOOL = "hades.capabilities.inspect"
CAPABILITIES_INVOKE_TOOL = "hades.capabilities.invoke"
DISCOVER_TOOL_ALIASES = frozenset(
    {
        "hades.discover_plugins",
        "hades.discover_tools",
        CAPABILITIES_SEARCH_TOOL,
    }
)
DISCOVER_PLUGIN_ID = "hades"


def parse_tool_choice(content: str) -> dict[str, Any] | None:
    from .json_util import loads_json_object

    parsed = loads_json_object(content)
    if isinstance(parsed, dict) and isinstance(parsed.get(TOOL_CALL_KEY), dict):
        return parsed[TOOL_CALL_KEY]
    return None


def tool_call_request_from_choice(choice: dict[str, Any]) -> ToolCallRequest | None:
    plugin_id = str(choice.get("plugin_id") or "").strip()
    tool_name = str(choice.get("tool_name") or "").strip()
    arguments = choice.get("input") if isinstance(choice.get("input"), dict) else choice.get("arguments")
    if not plugin_id or not tool_name or not isinstance(arguments, dict):
        return None
    return ToolCallRequest(plugin_id=plugin_id, tool_name=tool_name, arguments=arguments)


def score_tool_candidate(query: str, plugin: dict[str, Any], tool: dict[str, Any]) -> float:
    contract = build_capability_contract(plugin, tool)
    return _capability_intel_boost(query, plugin, tool, score_agent_tool(query, plugin, tool, contract))


def _capability_intel_boost(query: str, plugin: dict[str, Any], tool: dict[str, Any], lexical: float) -> float:
    """Add domain/intent signal on top of lexical scoring. Never bypasses eligibility.

    Unrelated queries stay at 0 so historical shortlist hiding is preserved.
    """
    if lexical <= 0:
        return lexical
    try:
        from capability_intel.planner import plan_requirements
        from capability_intel.registry import get_registry
    except Exception:
        return lexical
    try:
        registry = get_registry()
        plan = plan_requirements(query)
        plugin_id = str(plugin.get("id") or "")
        tool_name = str(tool.get("name") or "").lower()
        boost = 0.0
        for record in registry.all():
            if record.plugin_id != plugin_id:
                continue
            if record.kind == "tool" and record.name.lower() != tool_name:
                continue
            if record.kind not in {"tool", "mcp_provider", "tool_provider"}:
                continue
            if any(item.kind_hint == "tool" or item.capability in record.intents for item in plan.requirements):
                boost += 2.0
            if plan.explicit_providers and any(
                needle.lower() in record.name.lower() or needle.lower() in (plugin.get("name") or "").lower()
                for needle in plan.explicit_providers
            ):
                boost += 8.0
        return lexical + boost
    except Exception:
        return lexical


def _mcp_catalog_identity(tool: dict[str, Any]) -> str | None:
    """Stable identity for MCP remote/managed tools so expand+host do not double-list."""
    meta = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
    remote = str(meta.get("mcp_tool") or meta.get("mcp_remote_name") or "").strip()
    if remote:
        return f"mcp:{remote.lower()}"
    name = str(tool.get("name") or "")
    if name.startswith("mcp__"):
        return f"mcp:{name[5:].lower()}"
    if name.startswith("mcp."):
        return f"mcp:{name[4:].lower()}"
    if meta.get("mcp_remote") or meta.get("mcp_managed") or meta.get("mcp"):
        return f"mcp:{name.lower()}"
    return None


def _mcp_catalog_rank(tool: dict[str, Any], plugin: dict[str, Any]) -> int:
    """Prefer host-mirrored managed tools over plugin-expand wrappers when deduping."""
    meta = tool.get("metadata") if isinstance(tool.get("metadata"), dict) else {}
    if meta.get("mcp_managed") or str(plugin.get("plugin_type") or "").lower() == "mcp-managed":
        return 2
    if meta.get("mcp_remote"):
        return 1
    return 0


def discover_tools(
    *,
    query: str,
    plugins: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    permission_ok: Callable[[dict[str, Any], dict[str, Any]], bool] | None,
    limit: int = 8,
    offset: int = 0,
    category: str | None = None,
    include_unscored: bool = False,
) -> dict[str, Any]:
    """Paged discovery over the full enabled/ready registry with capability-aware ranking."""
    plugins_by_id = {item["id"]: item for item in plugins}
    ranked: list[tuple[float, dict[str, Any]]] = []
    seen_mcp: dict[str, tuple[float, int, dict[str, Any]]] = {}
    for tool in tools:
        plugin = plugins_by_id.get(tool.get("plugin_id"))
        if not plugin or not tool.get("enabled"):
            continue
        ok, reason = eligible_for_autonomous(plugin, tool)
        if not ok:
            continue
        plugin_category = str(plugin.get("category") or plugin.get("manifest", {}).get("category", ""))
        if category and plugin_category.lower() != category.lower():
            continue
        if permission_ok is not None:
            try:
                if not permission_ok(plugin, tool):
                    continue
            except Exception:
                continue
        contract = build_capability_contract(plugin, tool)
        score = score_agent_tool(query, plugin, tool, contract)
        score = _capability_intel_boost(query, plugin, tool, score)
        # Keep first-shortlist lexical (score>0). Broader paging via include_unscored.
        if score <= 0:
            if not include_unscored:
                continue
            score = 0.01
        row = {
            "plugin_id": plugin["id"],
            "plugin": plugin["name"],
            "category": plugin_category or "Tool",
            "tool_name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool.get("input_schema", {}),
            "action": tool.get("metadata", {}).get("action", tool["name"]),
            "score": round(score, 3),
            "why_eligible": reason,
            "capabilities": contract,
            "trust": plugin.get("trust"),
            "isolation": plugin.get("isolation"),
            "side_effect_class": contract.get("side_effect_class"),
            "cost_class": contract.get("cost_class"),
            "mcp_remote": bool(tool.get("metadata", {}).get("mcp_remote")),
            "mcp_managed": bool(tool.get("metadata", {}).get("mcp_managed")),
        }
        mcp_id = _mcp_catalog_identity(tool)
        if mcp_id:
            rank = _mcp_catalog_rank(tool, plugin)
            prev = seen_mcp.get(mcp_id)
            # Prefer host-managed mirror over plugin-expand wrappers, then higher score.
            if prev is None or rank > prev[1] or (rank == prev[1] and score > prev[0]):
                seen_mcp[mcp_id] = (score, rank, row)
            continue
        ranked.append((score, row))
    for score, _rank, row in seen_mcp.values():
        ranked.append((score, row))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["plugin"], pair[1]["tool_name"]))
    total = len(ranked)
    page = [item for _, item in ranked[offset: offset + limit]]
    next_offset = offset + limit if offset + limit < total else None
    return {
        "query": query,
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
        "tools": page,
        "discover_tool": {
            "plugin_id": DISCOVER_PLUGIN_ID,
            "tool_name": DISCOVER_TOOL_NAME,
            "description": "Zoek/pagineer extra enabled tools wanneer de eerste shortlist onvoldoende is.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "offset": {"type": "integer", "minimum": 0},
                    "category": {"type": "string"},
                },
            },
        },
    }


def observation_from_invoke_result(
    *,
    plugin_id: str,
    tool_name: str,
    result: dict[str, Any],
    tool_result_max_chars: int | None = 30_000,
) -> ToolObservation:
    from .tool_observation_budget import build_bounded_tool_observation

    try:
        from reasoning.tool_engine import normalize_tool_result_status

        row = normalize_tool_result_status(dict(result))
    except Exception:
        row = dict(result)
    bounded = build_bounded_tool_observation(row, max_chars=tool_result_max_chars)
    status = str(bounded.get("status") or "unknown")
    structured = bounded.get("structured_output")
    truncation = bounded.get("_truncation") if isinstance(bounded.get("_truncation"), dict) else None
    return ToolObservation(
        call_id=row.get("id") or row.get("call_id"),
        plugin_id=plugin_id,
        tool_name=tool_name,
        status=status,
        exit_code=bounded.get("exit_code"),
        error=bounded.get("error"),
        stdout=str(bounded.get("stdout") or ""),
        stderr=str(bounded.get("stderr") or ""),
        output=str(bounded.get("output") or ""),
        structured_output=structured if isinstance(structured, (dict, list)) else None,
        truncation=truncation,
        invocation_type=str(row.get("invocation_type") or "autonomous"),
        side_effects="none" if status in {"blocked", "rejected"} else "uncertain",
    )


def _diverse_by_plugin(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Round-robin tools so one fat MCP plugin cannot occupy the whole shortlist."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in rows:
        key = str(row.get("plugin_id") or "")
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)
    out: list[dict[str, Any]] = []
    while len(out) < limit and any(buckets[key] for key in order):
        for key in order:
            if buckets[key]:
                out.append(buckets[key].pop(0))
                if len(out) >= limit:
                    break
    return out[:limit]


def build_plugin_directory(
    *,
    plugins: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    permission_ok: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
    max_tools_per_plugin: int = 12,
) -> dict[str, Any]:
    """Compact overview of every enabled plugin so Chat never only 'sees' the lexical shortlist."""
    plugins_by_id = {item["id"]: item for item in plugins}
    eligible: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    tools_by_plugin: dict[str, list[str]] = {}
    for tool in tools:
        plugin = plugins_by_id.get(tool.get("plugin_id"))
        if not plugin or not plugin.get("enabled"):
            continue
        if not tool.get("enabled"):
            continue
        ok, reason = eligible_for_autonomous(plugin, tool)
        if ok and permission_ok is not None:
            try:
                if not permission_ok(plugin, tool):
                    ok, reason = False, "policy_blocked"
            except Exception:
                ok, reason = False, "policy_blocked"
        pid = str(plugin["id"])
        name = str(plugin.get("name") or pid)
        if ok:
            tools_by_plugin.setdefault(pid, [])
            if len(tools_by_plugin[pid]) < max_tools_per_plugin:
                tools_by_plugin[pid].append(str(tool.get("name") or ""))
            if pid not in {item["plugin_id"] for item in eligible}:
                eligible.append(
                    {
                        "plugin_id": pid,
                        "plugin": name,
                        "category": str(plugin.get("category") or (plugin.get("manifest") or {}).get("category") or "Tool"),
                        "trust": plugin.get("trust"),
                        "status": plugin.get("status"),
                    }
                )
        else:
            if pid not in {item["plugin_id"] for item in blocked}:
                blocked.append(
                    {
                        "plugin_id": pid,
                        "plugin": name,
                        "reason": reason,
                        "status": plugin.get("status"),
                        "trust": plugin.get("trust"),
                    }
                )
    eligible_ids = {item["plugin_id"] for item in eligible}
    blocked = [item for item in blocked if item["plugin_id"] not in eligible_ids]
    for item in eligible:
        names = tools_by_plugin.get(item["plugin_id"]) or []
        extra = max(0, sum(1 for t in tools if t.get("plugin_id") == item["plugin_id"] and t.get("enabled")) - len(names))
        item["tools"] = names
        if extra:
            item["more_tools"] = extra
    eligible.sort(key=lambda item: str(item.get("plugin") or ""))
    blocked.sort(key=lambda item: str(item.get("plugin") or ""))
    return {
        "eligible": eligible,
        "not_autonomous": blocked,
        "eligible_plugin_count": len(eligible),
        "blocked_plugin_count": len(blocked),
    }


def render_plugin_directory(directory: dict[str, Any] | None) -> str:
    if not directory:
        return ""
    eligible = directory.get("eligible") or []
    blocked = directory.get("not_autonomous") or []
    lines = [
        "HADES OPTIONAL CAPABILITIES (registry overview — not permanent model tool schemas).",
        "Discover with hades.capabilities.search, inspect with hades.capabilities.inspect,",
        "execute only via hades.capabilities.invoke(capability_id=...). Do not invent raw plugin tool calls.",
        f"Eligible plugins ({directory.get('eligible_plugin_count', len(eligible))}):",
    ]
    if not eligible:
        lines.append("- (geen autonome eligible tools — gebruik capability search of meld dat plugins niet uitvoerbaar zijn)")
    for item in eligible:
        extra = f" +{item['more_tools']} meer" if item.get("more_tools") else ""
        tool_names = ", ".join(item.get("tools") or []) or "(geen toolnamen)"
        lines.append(
            f"- {item.get('plugin')} [{item.get('plugin_id')}] "
            f"cat={item.get('category')} trust={item.get('trust')} tools: {tool_names}{extra}"
        )
    if blocked:
        lines.append(f"Enabled maar niet autonoom uitvoerbaar ({len(blocked)}):")
        for item in blocked[:24]:
            lines.append(
                f"- {item.get('plugin')} [{item.get('plugin_id')}] reason={item.get('reason')} "
                f"status={item.get('status')} trust={item.get('trust')}"
            )
    lines.append(
        "Voorbeeld: "
        '{"hades_tool_call":{"plugin_id":"hades","tool_name":"hades.capabilities.search",'
        '"input":{"query":"pdf naar markdown","limit":5}}} '
        "daarna hades.capabilities.invoke met capability_id."
    )
    return "\n".join(lines)


def render_tool_catalog(tools: list[dict[str, Any]], *, include_discover_hint: bool = True) -> str:
    lines = [json.dumps(item, ensure_ascii=False) for item in tools]
    text = (
        "BESCHIKBARE HADES FIRST-PARTY TOOLS (stabiele kernel). "
        "Optionele plugins/MCP zijn GEEN permanente schemas — gebruik hades.capabilities.*. "
        "Gebruik geen tool als lokale kennis volstaat.\n"
        + "\n".join(lines)
        + "\n\nWanneer een tool nodig is, antwoord ALLEEN met JSON: "
        + '{"hades_tool_call":{"plugin_id":"...","tool_name":"...","input":{}}}. '
        + "Na een toolresultaat mag je nog een tool kiezen of het eindantwoord geven. "
        + "Failed/blocked tooloutput is geen bewijs voor een inhoudelijke claim. "
        + "Kies bij voorkeur tools met lagere cost_class/side_effect_class wanneer equivalent."
    )
    if include_discover_hint:
        text += (
            "\nVoor optionele plugins/MCP: "
            '{"hades_tool_call":{"plugin_id":"hades","tool_name":"hades.capabilities.search",'
            '"input":{"query":"...","limit":5}}} '
            "daarna hades.capabilities.inspect of hades.capabilities.invoke."
        )
    return text
