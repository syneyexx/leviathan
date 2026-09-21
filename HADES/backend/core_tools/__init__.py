"""First-party HADES core tools for Chat (in-process, not plugins)."""

from __future__ import annotations

from .catalog import (
    CAPABILITIES_INSPECT,
    CAPABILITIES_INVOKE,
    CAPABILITIES_SEARCH,
    CORE_PLUGIN_ID,
    CORE_TOOL_NAMES,
    DISCOVER_PLUGINS,
    FS_LIST,
    FS_READ,
    FS_WRITE,
    KNOWLEDGE_SEARCH,
    MAX_MODEL_VISIBLE_TOOLS,
    MEMORY_PROPOSE,
    TERMINAL,
    WEB_FETCH,
    core_tool_catalog,
    is_capability_broker_tool,
    is_core_tool,
)
from .provider import invoke_core_tool, record_core_blocked
from .shortlist import assert_no_dynamic_plugin_schemas, build_chat_tool_shortlist

__all__ = [
    "CAPABILITIES_INSPECT",
    "CAPABILITIES_INVOKE",
    "CAPABILITIES_SEARCH",
    "CORE_PLUGIN_ID",
    "CORE_TOOL_NAMES",
    "DISCOVER_PLUGINS",
    "FS_LIST",
    "FS_READ",
    "FS_WRITE",
    "KNOWLEDGE_SEARCH",
    "MAX_MODEL_VISIBLE_TOOLS",
    "MEMORY_PROPOSE",
    "TERMINAL",
    "WEB_FETCH",
    "assert_no_dynamic_plugin_schemas",
    "build_chat_tool_shortlist",
    "core_tool_catalog",
    "invoke_core_tool",
    "is_capability_broker_tool",
    "is_core_tool",
    "record_core_blocked",
]
