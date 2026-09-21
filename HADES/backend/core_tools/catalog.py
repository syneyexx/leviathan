"""Explicit core tool schemas and effects (no permission inference).

The model-facing HADES Tool Kernel is intentionally small and stable.
Dynamic plugin/MCP tools are discovered via ``hades.capabilities.*`` and
are never permanent members of this catalog.
"""

from __future__ import annotations

from typing import Any

CORE_PLUGIN_ID = "hades"

# Hard architectural budget for initial Chat model-visible tools.
MAX_MODEL_VISIBLE_TOOLS = 12

FS_LIST = "hades.fs_list"
FS_READ = "hades.fs_read"
FS_WRITE = "hades.fs_write"
TERMINAL = "hades.terminal"
KNOWLEDGE_SEARCH = "hades.knowledge_search"
MEMORY_PROPOSE = "hades.memory_propose"
WEB_FETCH = "hades.web_fetch"
DISCOVER_PLUGINS = "hades.discover_plugins"
CAPABILITIES_SEARCH = "hades.capabilities.search"
CAPABILITIES_INSPECT = "hades.capabilities.inspect"
CAPABILITIES_INVOKE = "hades.capabilities.invoke"

CORE_TOOL_NAMES = (
    FS_LIST,
    FS_READ,
    FS_WRITE,
    TERMINAL,
    KNOWLEDGE_SEARCH,
    MEMORY_PROPOSE,
    WEB_FETCH,
    CAPABILITIES_SEARCH,
    CAPABILITIES_INSPECT,
    CAPABILITIES_INVOKE,
    DISCOVER_PLUGINS,  # legacy alias surface — still first-party, not a plugin
)

# Accept legacy discover name from older prompts / payloads.
DISCOVER_ALIASES = frozenset({DISCOVER_PLUGINS, "hades.discover_tools"})
CAPABILITY_TOOL_NAMES = frozenset({CAPABILITIES_SEARCH, CAPABILITIES_INSPECT, CAPABILITIES_INVOKE})
# Discover aliases route through the capability broker search path.
CAPABILITY_SEARCH_ALIASES = frozenset({CAPABILITIES_SEARCH, *DISCOVER_ALIASES})


def _canonical_core_name(name: str) -> str | None:
    raw = str(name or "").strip()
    if not raw:
        return None
    if raw in DISCOVER_ALIASES:
        return DISCOVER_PLUGINS
    if raw in CORE_TOOL_NAMES or raw in CAPABILITY_TOOL_NAMES:
        return raw
    # Provider function names often sanitize '.' → '_'.
    underscored = {
        item.replace(".", "_"): item
        for item in (*CORE_TOOL_NAMES, *DISCOVER_ALIASES, *CAPABILITY_TOOL_NAMES)
    }
    if raw in underscored:
        hit = underscored[raw]
        return DISCOVER_PLUGINS if hit in DISCOVER_ALIASES else hit
    return None


def is_core_tool(name: str) -> bool:
    return _canonical_core_name(name) is not None


def is_capability_broker_tool(name: str) -> bool:
    canon = _canonical_core_name(name)
    return canon in CAPABILITY_TOOL_NAMES or canon == DISCOVER_PLUGINS


def _tool(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    effects: list[str],
    side_effect_class: str,
    policy_kind: str | None = None,
    cost_class: str = "cheap",
    latency_class: str = "fast",
) -> dict[str, Any]:
    return {
        "plugin_id": CORE_PLUGIN_ID,
        "name": name,
        "enabled": True,
        "description": description,
        "input_schema": input_schema,
        "metadata": {
            "core": True,
            "policy_kind": policy_kind,
            "permissions": [],
        },
        "capabilities": {
            "effects": list(effects),
            "side_effect_class": side_effect_class,
            "cost_class": cost_class,
            "latency_class": latency_class,
            "failure_modes": ["timeout", "schema"],
        },
        "plugin": {
            "id": CORE_PLUGIN_ID,
            "name": "HADES Core",
            "enabled": True,
            "status": "ready",
            "trust": "trusted",
            "permissions": [],
            "manifest": {"autonomous": True, "category": "Core"},
            "plugin_type": "Core",
            "category": "Core",
            "capabilities": {
                "effects": list(effects),
                "side_effect_class": side_effect_class,
            },
        },
    }


def core_tool_catalog(*, settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return policy-filtered first-party Tool Kernel rows for Chat shortlists.

    Plugin/MCP tools are intentionally absent — they are broker capabilities.
    """
    cfg = settings if isinstance(settings, dict) else {}
    network_policy = str(cfg.get("network_policy") or "block").strip().lower()

    tools = [
        _tool(
            name=FS_LIST,
            description="List files and directories inside the HADES data/workspace jail.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path inside the jail (default: root)."},
                },
            },
            effects=["read_files"],
            side_effect_class="read",
            policy_kind="file_read",
        ),
        _tool(
            name=FS_READ,
            description="Read a text file inside the HADES data/workspace jail (size-capped, no binary dumps).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or jail-absolute path to read."},
                },
                "required": ["path"],
            },
            effects=["read_files"],
            side_effect_class="read",
            policy_kind="file_read",
        ),
        _tool(
            name=FS_WRITE,
            description="Write a text file inside the HADES jail. Policy ask requires approval; never silent.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
            effects=["write_files", "read_files"],
            side_effect_class="write",
            policy_kind="file_write",
        ),
        _tool(
            name=TERMINAL,
            description="Run an allowlisted argv command inside the terminal cwd jail (shell=False).",
            input_schema={
                "type": "object",
                "properties": {
                    "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "cwd": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
                },
                "required": ["argv"],
            },
            effects=["subprocess"],
            side_effect_class="process",
            policy_kind="subprocess",
            cost_class="moderate",
            latency_class="normal",
        ),
        _tool(
            name=KNOWLEDGE_SEARCH,
            description="Search local HADES knowledge with provenance (source id/uri).",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
            effects=[],
            side_effect_class="none",
            policy_kind=None,
        ),
        _tool(
            name=MEMORY_PROPOSE,
            description="Create a durable memory proposal for user review (never auto-promotes).",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "summary": {"type": "string"},
                    "collection": {"type": "string"},
                },
                "required": ["title", "content"],
            },
            effects=[],
            side_effect_class="none",
            policy_kind=None,
        ),
        _tool(
            name=CAPABILITIES_SEARCH,
            description=(
                "Search optional plugin/MCP capabilities by task meaning. "
                "Returns compact matches with availability reasons — not full schemas. "
                "Discovery does not grant execution rights; use inspect/invoke next."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language task or capability need."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
            effects=[],
            side_effect_class="none",
            policy_kind=None,
        ),
        _tool(
            name=CAPABILITIES_INSPECT,
            description=(
                "Inspect one registered capability_id: argument schema, effects, "
                "availability, policy/approval implications. Prefer after search."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "capability_id": {
                        "type": "string",
                        "description": "Stable id such as plugin:markitdown:convert or mcp:github:create_issue.",
                    },
                },
                "required": ["capability_id"],
            },
            effects=[],
            side_effect_class="none",
            policy_kind=None,
        ),
        _tool(
            name=CAPABILITIES_INVOKE,
            description=(
                "Invoke a registered capability by capability_id through the HADES broker. "
                "Only registry entries may execute; model-supplied trust/autonomy/effects are ignored. "
                "Policy, trust, health and approval are re-checked live."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "capability_id": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["capability_id"],
            },
            effects=[],  # effects resolved from the target capability at invoke time
            side_effect_class="none",
            policy_kind=None,
        ),
        # Legacy hades.discover_plugins remains callable (is_core_tool / provider alias)
        # but is intentionally omitted from the model-visible catalog to avoid duplicate
        # discovery schemas alongside hades.capabilities.search.
    ]
    if network_policy == "allow":
        # Insert before capability tools so native ops stay grouped.
        insert_at = next((i for i, t in enumerate(tools) if t["name"] == CAPABILITIES_SEARCH), len(tools))
        tools.insert(
            insert_at,
            _tool(
                name=WEB_FETCH,
                description="Fetch a public HTTP(S) URL when network_policy=allow.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_chars": {"type": "integer", "minimum": 200, "maximum": 50_000},
                    },
                    "required": ["url"],
                },
                effects=["network"],
                side_effect_class="network",
                policy_kind="network",
                cost_class="moderate",
                latency_class="normal",
            ),
        )
    if len(tools) > MAX_MODEL_VISIBLE_TOOLS:
        tools = tools[:MAX_MODEL_VISIBLE_TOOLS]
    return tools
