"""HADES network/subprocess policy helpers for MCP side effects.

``ask`` never means allow. Scoped ApprovalService decisions authorize one
server identity (id + endpoint/command fingerprint) for a bounded effect.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable
from urllib.parse import urlparse


class McpPolicyError(PermissionError):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "policy",
        approval_required: bool = False,
        approval: dict[str, Any] | None = None,
        effect: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.approval_required = approval_required
        self.approval = approval
        self.effect = effect


def _policy(settings: dict[str, Any], key: str, default: str) -> str:
    raw = settings.get(key)
    if raw is None and key == "network_policy":
        raw = settings.get("network")
    return str(raw if raw is not None else default).lower()


def is_loopback_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in {"127.0.0.1", "localhost", "::1"} or host.endswith(".localhost")


def scope_fingerprint(scope: dict[str, Any]) -> str:
    raw = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mcp_network_scope(*, server_id: str, endpoint_url: str, effect: str) -> dict[str, Any]:
    return {
        "kind": "mcp_network",
        "server_id": server_id,
        "endpoint_url": str(endpoint_url or "").strip(),
        "effect": effect,
    }


def mcp_subprocess_scope(*, server_id: str, command: dict[str, Any] | None, effect: str) -> dict[str, Any]:
    cmd = command if isinstance(command, dict) else {}
    return {
        "kind": "mcp_subprocess",
        "server_id": server_id,
        "executable": str(cmd.get("executable") or ""),
        "args": list(cmd.get("args") or []),
        "cwd": cmd.get("cwd"),
        "effect": effect,
    }


def mcp_tool_scope(
    *,
    server_id: str,
    tool_id: str,
    tool_name: str,
    effect: str = "mcp_tool_invoke",
) -> dict[str, Any]:
    """Exact scope for MCP tool invoke approvals (ApprovalService authority)."""
    return {
        "kind": "mcp_tool",
        "server_id": str(server_id or ""),
        "tool_id": str(tool_id or ""),
        "tool_name": str(tool_name or ""),
        "effect": effect,
    }


def workflow_product_scope(
    *,
    workflow_id: str,
    action: str,
    step_id: str | None = None,
) -> dict[str, Any]:
    """Exact scope for Gen2 product-action approvals."""
    scope: dict[str, Any] = {
        "kind": "workflow_product",
        "workflow_id": str(workflow_id or ""),
        "action": str(action or ""),
    }
    if step_id:
        scope["step_id"] = str(step_id)
    return scope


def require_network_policy(
    settings: dict[str, Any],
    *,
    endpoint_url: str,
    approved: bool = False,
    purpose: str = "mcp_http",
) -> None:
    """Enforce HADES network_policy for external MCP HTTP / OAuth I/O.

    ask must never be treated as allow.
    Loopback endpoints follow existing HADES local conventions (allowed without
    external network approval).
    """
    if is_loopback_url(endpoint_url):
        return
    policy = _policy(settings, "network_policy", "block")
    if policy == "allow":
        return
    if policy == "block":
        raise McpPolicyError(
            f"Netwerkbeleid blokkeert externe MCP-activiteit ({purpose})",
            kind="permission",
            effect=purpose,
        )
    if policy == "ask":
        if approved:
            return
        raise McpPolicyError(
            f"Expliciete netwerkgoedkeuring vereist voor MCP ({purpose})",
            kind="permission",
            approval_required=True,
            effect=purpose,
        )
    raise McpPolicyError(f"Onbekend netwerkbeleid '{policy}' — fail-closed", kind="permission")


def require_subprocess_policy(
    settings: dict[str, Any],
    *,
    approved: bool = False,
    purpose: str = "mcp_stdio",
) -> None:
    policy = _policy(settings, "subprocess_policy", "allow")
    if policy == "allow":
        return
    if policy == "block":
        raise McpPolicyError(
            f"Subprocess-beleid blokkeert MCP stdio ({purpose})",
            kind="permission",
            effect=purpose,
        )
    if policy == "ask":
        if approved:
            return
        raise McpPolicyError(
            f"Expliciete subprocess-goedkeuring vereist voor MCP ({purpose})",
            kind="permission",
            approval_required=True,
            effect=purpose,
        )
    raise McpPolicyError(f"Onbekend subprocess-beleid '{policy}' — fail-closed", kind="permission")


def settings_approved_flag(settings: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        if bool(settings.get(key)):
            return True
    return False


def resolve_scoped_approval(
    approval_service: Any | None,
    *,
    approval_id: str | None,
    expected_scope: dict[str, Any],
) -> bool:
    """Return True when ApprovalService has an approved decision for this exact scope.

    Client booleans such as ``approved_by_user`` / ``preapproved`` are never consulted.
    Expired or non-approved records fail closed.
    """
    if not approval_id or approval_service is None:
        return False
    try:
        item = approval_service.get(approval_id)
    except Exception:
        return False
    if not item or item.get("status") != "approved":
        return False
    expires = item.get("expires_at")
    if expires:
        try:
            from database import utc_now

            if str(expires) < utc_now():
                return False
        except Exception:
            return False
    if item.get("timed_out") is True:
        return False
    scope = item.get("scope_json") or {}
    if isinstance(scope, str):
        try:
            scope = json.loads(scope)
        except Exception:
            return False
    if not isinstance(scope, dict):
        return False
    # Endpoint/command/tool identity must still match; changing config invalidates approval.
    return scope_fingerprint(scope) == scope_fingerprint(expected_scope)


def request_mcp_policy_approval(
    approval_service: Any,
    *,
    server_id: str,
    effect: str,
    scope: dict[str, Any],
    expected_effect: str,
) -> dict[str, Any]:
    return approval_service.create_tool_approval(
        plugin_id=f"mcp:{server_id}",
        tool_name=f"mcp.policy.{effect}",
        arguments={"scope": scope},
        expected_effect=expected_effect,
        schema_version="mcp-policy-1",
        scope=scope,
    )
