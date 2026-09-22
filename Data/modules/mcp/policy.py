"""MCP trust / effect policy — never trust tool descriptions as security authority."""

from __future__ import annotations

from typing import Any

from Data.modules.function_runtime.types import SideEffect

from .types import McpIsolationKind, McpServerConfig, McpTransportKind, McpTrust


# Conservative defaults when semantic effects are unknown.
_DEFAULT_UNKNOWN_EFFECTS: tuple[SideEffect, ...] = (
    SideEffect.EXECUTE,
    SideEffect.EXTERNAL_SIDE_EFFECT,
)

_TRANSPORT_EFFECTS: dict[McpTransportKind, tuple[SideEffect, ...]] = {
    McpTransportKind.STDIO: (SideEffect.EXECUTE,),
    McpTransportKind.HTTP: (SideEffect.NETWORK,),
    McpTransportKind.SSE: (SideEffect.NETWORK,),
}


def transport_effects(transport: McpTransportKind) -> tuple[SideEffect, ...]:
    return _TRANSPORT_EFFECTS.get(transport, (SideEffect.EXECUTE, SideEffect.NETWORK))


def parse_side_effects(raw: Any) -> tuple[SideEffect, ...]:
    if raw is None:
        return ()
    items: list[str]
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, (list, tuple)):
        items = [str(item) for item in raw]
    else:
        return ()
    out: list[SideEffect] = []
    for item in items:
        key = item.strip().upper()
        try:
            out.append(SideEffect(key))
        except ValueError:
            # Unknown labels map conservatively.
            out.append(SideEffect.EXTERNAL_SIDE_EFFECT)
    return tuple(dict.fromkeys(out))


def resolve_semantic_effects(
    config: McpServerConfig,
    tool_name: str,
    *,
    tool_annotations: dict[str, Any] | None = None,
) -> tuple[SideEffect, ...]:
    """Resolve semantic effects without trusting free-text descriptions.

    Priority:
    1. Explicit per-tool config on the server registration
    2. Trusted annotations only when trust >= MANUAL and annotations present
    3. Conservative unknown fallback
    """
    declared = config.semantic_effects.get(tool_name)
    if declared:
        return parse_side_effects(declared)

    if config.trust in {McpTrust.MANUAL, McpTrust.TRUSTED} and tool_annotations:
        # MCP tool annotations are advisory hints — only accept explicit effect keys.
        if "sideEffects" in tool_annotations:
            parsed = parse_side_effects(tool_annotations.get("sideEffects"))
            if parsed:
                return parsed
        # Boolean hints from MCP annotations (readOnlyHint / destructiveHint).
        effects: list[SideEffect] = []
        if tool_annotations.get("readOnlyHint") is True:
            effects.append(SideEffect.READ)
        if tool_annotations.get("destructiveHint") is True:
            effects.extend([SideEffect.WRITE, SideEffect.DESTRUCTIVE])
        if tool_annotations.get("openWorldHint") is True:
            effects.append(SideEffect.NETWORK)
        if effects:
            return tuple(dict.fromkeys(effects))

    # Unknown → conservative.
    base = list(_DEFAULT_UNKNOWN_EFFECTS)
    # Always include transport-class effects for honesty.
    for effect in transport_effects(config.transport):
        if effect not in base:
            base.append(effect)
    if config.trust == McpTrust.UNTRUSTED:
        if SideEffect.EXECUTE not in base:
            base.append(SideEffect.EXECUTE)
    return tuple(base)


def resolve_effective_isolation(
    requested: McpIsolationKind,
    *,
    transport: McpTransportKind,
    allow_container: bool = False,
) -> tuple[McpIsolationKind, bool]:
    """Return (effective, matched). Never silently claim stronger isolation."""
    if requested in {McpIsolationKind.CONTAINER, McpIsolationKind.SANDBOX}:
        if allow_container:
            return requested, True
        # Fail-closed callers should refuse; bridge reports honesty.
        if transport == McpTransportKind.STDIO:
            return McpIsolationKind.SUBPROCESS, False
        return McpIsolationKind.NONE, False
    if requested in {McpIsolationKind.SUBPROCESS, McpIsolationKind.PROCESS}:
        if transport == McpTransportKind.STDIO:
            return McpIsolationKind.SUBPROCESS, True
        return McpIsolationKind.NONE, False
    return McpIsolationKind.NONE, True


def sanitize_text_for_log(text: str, *, secret_values: list[str] | None = None, max_chars: int = 2000) -> str:
    out = text or ""
    for secret in secret_values or []:
        if secret:
            out = out.replace(secret, "***REDACTED***")
    if len(out) > max_chars:
        out = out[: max_chars - 3] + "..."
    return out
