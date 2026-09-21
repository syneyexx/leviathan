"""Chat tool shortlist: stable first-party HADES Tool Kernel only.

Plugin and MCP tools are dynamic CapabilityRegistry entries. They must never
inflate the base model-visible tool schema payload.
"""

from __future__ import annotations

from typing import Any, Callable

from .catalog import MAX_MODEL_VISIBLE_TOOLS, core_tool_catalog, is_core_tool


def build_chat_tool_shortlist(
    *,
    query: str,
    plugins: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    settings: dict[str, Any] | None = None,
    permission_ok: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
    limit: int = 8,
    allow_tools: bool = True,
) -> list[dict[str, Any]]:
    """Build the Chat native-tool shortlist (first-party kernel only).

    ``plugins`` / ``tools`` / ``permission_ok`` / ``query`` are retained for
    call-site compatibility and optional server-side prefetch elsewhere.
    They must not inject dynamic schemas into the model payload.
    """
    _ = (query, plugins, tools, permission_ok)  # compatibility; intentionally unused for schema injection
    if not allow_tools:
        return []
    cfg = settings if isinstance(settings, dict) else {}
    if not bool(cfg.get("plugin_autonomous_tools", True)):
        return []

    core = [item for item in core_tool_catalog(settings=cfg) if is_core_tool(str(item.get("name") or ""))]
    cap = max(1, min(int(MAX_MODEL_VISIBLE_TOOLS), int(limit) if limit else MAX_MODEL_VISIBLE_TOOLS))
    # Always keep the capability broker triad when truncating — they are the
    # only path to dynamic plugins/MCP.
    broker_names = (
        "hades.capabilities.search",
        "hades.capabilities.inspect",
        "hades.capabilities.invoke",
    )
    if len(core) > cap:
        broker = [item for item in core if item.get("name") in broker_names]
        others = [item for item in core if item.get("name") not in broker_names]
        # Drop legacy discover first from others.
        others = [item for item in others if item.get("name") != "hades.discover_plugins"]
        keep_others = max(0, cap - len(broker))
        core = others[:keep_others] + broker
        # If still over (tiny cap), prefer invoke/search over inspect.
        if len(core) > cap:
            core = core[:cap]
    return core[:cap]


def assert_no_dynamic_plugin_schemas(shortlist: list[dict[str, Any]]) -> None:
    """Architectural invariant helper for tests."""
    for item in shortlist:
        name = str(item.get("name") or "")
        plugin_id = str(item.get("plugin_id") or "")
        if not is_core_tool(name):
            raise AssertionError(f"Non-core tool leaked into model shortlist: {plugin_id}/{name}")
        if plugin_id not in {"hades", "hades.core", ""}:
            raise AssertionError(f"Non-core plugin_id in model shortlist: {plugin_id}/{name}")
