"""Policy, trust, health and prerequisite filtering.

Planning/ranking may recommend. This module never grants extra authority.
PluginManager eligibility and global policies remain the execution boundary.
"""

from __future__ import annotations

from typing import Any, Callable

from plugin_runtime_v2 import (
    build_capability_contract,
    eligible_for_autonomous,
    evaluate_global_side_effect_policies,
)

from .contracts import CanonicalCapability, RankedCandidate
from .taxonomy import REASONING_KINDS


def plugin_health_state(plugin: dict[str, Any] | None) -> str:
    if not plugin:
        return "unknown"
    if plugin.get("failure_state") in {"dependency_failed", "integrity_failed", "unsupported_runtime", "not_ready"}:
        return "needs_setup"
    if not plugin.get("enabled"):
        return "blocked"
    if plugin.get("status") != "ready":
        return "needs_setup"
    health = str(plugin.get("health") or "").lower()
    if health in {"unhealthy", "needs_attention"}:
        return "degraded"
    if health in {"prepared", "healthy", "unknown", ""}:
        return "available"
    return "unknown"


def apply_runtime_health(record: CanonicalCapability, plugin: dict[str, Any] | None) -> CanonicalCapability:
    record.health = plugin_health_state(plugin) if plugin is not None else record.health
    record.availability = record.health == "available"
    return record


def policy_allows(
    record: CanonicalCapability,
    *,
    plugin: dict[str, Any] | None,
    tool: dict[str, Any] | None,
    settings: dict[str, Any] | None,
    invocation_type: str = "autonomous",
    approved_by_user: bool = False,
    permission_ok: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
) -> tuple[bool, str]:
    """Fail-closed eligibility. Skills/knowledge skip subprocess eligibility."""
    if record.kind in REASONING_KINDS:
        if record.plugin_id:
            if plugin is None:
                return False, "missing_plugin"
            if not plugin.get("enabled", True):
                return False, "plugin_disabled"
            if plugin.get("status") not in {None, "ready", ""}:
                return False, f"status={plugin.get('status')}"
        return True, "reasoning_content"
    if plugin is None and record.source == "native":
        return True, "native"
    if plugin is None:
        return False, "missing_plugin"
    if tool is not None:
        ok, reason = eligible_for_autonomous(plugin, tool)
        if not ok:
            return False, reason
        if permission_ok is not None:
            try:
                if not permission_ok(plugin, tool):
                    return False, "permission_denied"
            except Exception:
                return False, "permission_denied"
        contract = build_capability_contract(plugin, tool)
        policy = evaluate_global_side_effect_policies(
            contract=contract,
            settings=settings,
            invocation_type=invocation_type,
            approved_by_user=approved_by_user,
            approvals=None,
        )
        if not policy.get("allowed"):
            return False, str(policy.get("reason") or "policy_block")
        return True, "ok"
    if not plugin.get("enabled") or plugin.get("status") != "ready":
        return False, "not_ready"
    return True, "plugin_ready"


def filter_candidates(
    candidates: list[RankedCandidate],
    *,
    plugins_by_id: dict[str, dict[str, Any]] | None = None,
    tools_by_key: dict[tuple[str, str], dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
    permission_ok: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
    known_dead: set[str] | None = None,
) -> tuple[list[RankedCandidate], list[RankedCandidate]]:
    selected: list[RankedCandidate] = []
    rejected: list[RankedCandidate] = []
    dead = known_dead or set()
    for item in candidates:
        record = item.capability
        if record.canonical_id in dead or record.provider_id in dead:
            item.eligible = False
            item.rejected_reason = "known_dead_route"
            rejected.append(item)
            continue
        plugin = (plugins_by_id or {}).get(record.plugin_id or "")
        tool = None
        if record.kind == "tool" and record.plugin_id:
            tool = (tools_by_key or {}).get((record.plugin_id, record.name))
        allowed, reason = policy_allows(
            record,
            plugin=plugin,
            tool=tool,
            settings=settings,
            permission_ok=permission_ok,
        )
        if not allowed:
            item.eligible = False
            item.rejected_reason = reason
            rejected.append(item)
            continue
        item.eligible = True
        if reason not in item.reasons:
            item.reasons.append(reason)
        selected.append(item)
    return selected, rejected
