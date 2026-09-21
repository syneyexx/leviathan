"""Authoritative side-effect execution boundary for HADES.

Conceptual pipeline (composable, not one mega-function):

  request → normalize → resolve capability → validate schema → derive effects
  → security policy → durable approval check → isolation decision
  → effect registration → execute → capture → verify → persist → honest result

This module does not replace PluginManager; it defines the invariant surface that
callers and tests can assert against, and shared helpers that must fail closed.
"""

from __future__ import annotations

from typing import Any, Mapping

# Privileged invocation types that may skip interactive trust / G11 only when
# explicitly requested via privileged_policy_skip=True from trusted internal callers.
PRIVILEGED_INVOCATION_TYPES = frozenset({"install", "system"})

# Invocation types allowed from untrusted / workflow / model-driven callers.
PUBLIC_INVOCATION_TYPES = frozenset(
    {
        "manual",
        "autonomous",
        "workflow",
        "agent",
        "mission",
        "chat",
        "work",
        "schedule",
    }
)


class PolicyModuleUnavailable(RuntimeError):
    """policy_enforcement could not be imported — fail closed."""


def normalize_invocation_type(raw: str | None, *, default: str = "manual") -> str:
    value = str(raw or default).strip().lower() or default
    if value in PRIVILEGED_INVOCATION_TYPES:
        return value
    if value in PUBLIC_INVOCATION_TYPES:
        return value
    # Unknown types are treated as public but non-privileged (no policy skip).
    return value


def may_skip_tool_policies(
    *,
    invocation_type: str,
    privileged_policy_skip: bool = False,
) -> bool:
    """Return True only for trusted internal install/system paths.

    Workflow / model / HTTP callers must never obtain a skip by setting
    invocation_type alone.
    """
    itype = normalize_invocation_type(invocation_type)
    return privileged_policy_skip and itype in PRIVILEGED_INVOCATION_TYPES


def enforce_policies_fail_closed(
    *,
    tool_name: str,
    arguments: Any,
    settings: Mapping[str, Any] | None = None,
    source: str = "execution_gateway",
    is_mcp_tool: bool | None = None,
) -> dict[str, Any]:
    """Run G11/G8 enforcement; ImportError / unexpected errors fail closed."""
    try:
        from policy_enforcement import enforce_tool_invocation_policies
    except ImportError as exc:
        raise PolicyModuleUnavailable(
            "policy_enforcement module unavailable; refusing tool execution"
        ) from exc
    try:
        return enforce_tool_invocation_policies(
            tool_name=tool_name,
            arguments=arguments,
            settings=settings,
            source=source,
            is_mcp_tool=is_mcp_tool,
        )
    except PolicyModuleUnavailable:
        raise
    except Exception as exc:
        return {
            "allowed": False,
            "reason": f"policy_enforcement_error:{type(exc).__name__}",
            "findings": [{"code": "policy_error", "message": str(exc)}],
            "args": None,
            "defenses": ["fail_closed"],
            "source": source,
            "tool_name": tool_name,
        }


def assert_public_invocation_type(invocation_type: str) -> str:
    """Reject privileged types for public/workflow adapters."""
    itype = normalize_invocation_type(invocation_type)
    if itype in PRIVILEGED_INVOCATION_TYPES:
        raise PermissionError(
            f"invocation_type '{itype}' is privileged and cannot be set by public callers"
        )
    return itype


# Marker used by architectural invariant tests — every production side-effect
# kernel that goes through PluginManager.invoke should be reachable from a
# path that imports this module (or calls may_skip_tool_policies /
# enforce_policies_fail_closed).
EXECUTION_GATEWAY_MODULE = "runtime.execution_gateway"
