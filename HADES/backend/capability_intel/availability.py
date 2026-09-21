"""Live availability reasons for capability discovery (not authorization grants).

Search may surface a capability that cannot currently execute. Reasons are
honest and bounded — they never grant authority.
"""

from __future__ import annotations

from typing import Any

from plugin_runtime_v2 import (
    build_capability_contract,
    eligible_for_autonomous,
    evaluate_global_side_effect_policies,
)

# Stable reason codes returned to the model / FINALBETA.
AVAILABLE = "available"
DISABLED = "disabled"
PLUGIN_UNHEALTHY = "plugin_unhealthy"
APPROVAL_REQUIRED = "approval_required"
NETWORK_BLOCKED = "network_blocked"
FILESYSTEM_BLOCKED = "filesystem_blocked"
SUBPROCESS_BLOCKED = "subprocess_blocked"
NOT_AUTONOMOUS = "not_autonomous"
MISSING_DEPENDENCY = "missing_dependency"
MCP_DISCONNECTED = "mcp_disconnected"
UNTRUSTED = "untrusted"
NOT_READY = "not_ready"
UNKNOWN = "unknown"
UNREGISTERED = "unregistered"


def _policy_reason_code(reason: str) -> str:
    lower = str(reason or "").lower()
    if "network" in lower and "block" in lower:
        return NETWORK_BLOCKED
    if "file_write" in lower or "file_read" in lower or "filesystem" in lower:
        return FILESYSTEM_BLOCKED
    if "subprocess" in lower and "block" in lower:
        return SUBPROCESS_BLOCKED
    if "approval" in lower or "ask" in lower:
        return APPROVAL_REQUIRED
    return UNKNOWN


def evaluate_availability(
    *,
    plugin: dict[str, Any] | None,
    tool: dict[str, Any] | None,
    settings: dict[str, Any] | None = None,
    provider: str = "plugin",
    mcp_connected: bool | None = None,
) -> dict[str, Any]:
    """Return ``{available, reason, detail, autonomous, policy}`` without granting rights."""
    cfg = settings if isinstance(settings, dict) else {}
    if tool is None:
        return {
            "available": False,
            "reason": UNREGISTERED,
            "detail": "Capability tool row is missing from the registry.",
            "autonomous": False,
            "executable": False,
        }
    if provider == "mcp" and mcp_connected is False:
        return {
            "available": False,
            "reason": MCP_DISCONNECTED,
            "detail": "MCP server is disconnected.",
            "autonomous": False,
            "executable": False,
        }
    if plugin is None:
        return {
            "available": False,
            "reason": UNREGISTERED,
            "detail": "Provider plugin record is missing.",
            "autonomous": False,
            "executable": False,
        }
    if not bool(plugin.get("enabled", True)):
        return {
            "available": False,
            "reason": DISABLED,
            "detail": "Plugin is disabled.",
            "autonomous": False,
            "executable": False,
        }
    status = str(plugin.get("status") or "").lower()
    failure = str(plugin.get("failure_state") or "").lower()
    if failure in {"dependency_failed", "integrity_failed", "unsupported_runtime"}:
        return {
            "available": False,
            "reason": MISSING_DEPENDENCY if failure == "dependency_failed" else PLUGIN_UNHEALTHY,
            "detail": f"Plugin failure_state={failure}",
            "autonomous": False,
            "executable": False,
        }
    if status and status not in {"ready", ""}:
        return {
            "available": False,
            "reason": NOT_READY if status != "unhealthy" else PLUGIN_UNHEALTHY,
            "detail": f"Plugin status={status}",
            "autonomous": False,
            "executable": False,
        }
    health = str(plugin.get("health") or "").lower()
    if health in {"unhealthy", "needs_attention"}:
        return {
            "available": False,
            "reason": PLUGIN_UNHEALTHY,
            "detail": f"Plugin health={health}",
            "autonomous": False,
            "executable": False,
        }

    ok, autonomy_reason = eligible_for_autonomous(plugin, tool)
    contract = build_capability_contract(plugin, tool)
    policy = evaluate_global_side_effect_policies(
        contract=contract,
        settings=cfg,
        invocation_type="autonomous",
        approved_by_user=False,
    )
    policy_allowed = bool(policy.get("allowed"))
    policy_reason = str(policy.get("reason") or "")

    if not ok:
        lower = autonomy_reason.lower()
        if "autonomous" in lower:
            reason = NOT_AUTONOMOUS
        elif "trust" in lower:
            reason = UNTRUSTED
        elif "enabled" in lower or "ready" in lower:
            reason = DISABLED if "enabled" in lower else NOT_READY
        else:
            reason = NOT_AUTONOMOUS
        return {
            "available": False,
            "reason": reason,
            "detail": autonomy_reason,
            "autonomous": False,
            "executable": False,
            "policy": policy,
        }

    if not policy_allowed:
        code = _policy_reason_code(policy_reason)
        return {
            "available": False,
            "reason": code,
            "detail": policy_reason or "Blocked by global side-effect policy.",
            "autonomous": True,
            "executable": False,
            "policy": policy,
        }

    return {
        "available": True,
        "reason": AVAILABLE,
        "detail": "Eligible for autonomous execution under current policy.",
        "autonomous": True,
        "executable": True,
        "policy": policy,
    }
