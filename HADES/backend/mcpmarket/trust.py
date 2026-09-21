"""Trust boundary for MCPMarket metadata. Marketplace never grants HADES trust."""

from __future__ import annotations

from typing import Any

from plugin_runtime_v2 import TRUST_ORDER, normalize_trust

from .parse import INJECTION_MARKERS


def classify_side_effects(listing: dict[str, Any]) -> str:
    blob = " ".join(
        str(listing.get(key) or "")
        for key in ("description", "name", "command", "transport")
    ).lower()
    if any(token in blob for token in ("docker", "npx", "uvx", "pip install", "clone", "shell", "exec")):
        return "process"
    if listing.get("kind_hint") == "skill":
        return "none"
    return "network"


def classify_credentials(listing: dict[str, Any]) -> dict[str, Any]:
    blob = f"{listing.get('description') or ''} {listing.get('auth') or ''}".lower()
    needs = any(token in blob for token in ("api key", "oauth", "token", "secret", "bearer", "login"))
    return {
        "requires_auth": needs or bool(listing.get("requires_auth")),
        "marketplace_grants_credentials": False,
        "store": "hades.mcp_host.secrets" if needs else None,
    }


def inspect_listing(listing: dict[str, Any], *, policy_blocked: bool = False) -> dict[str, Any]:
    trust = normalize_trust("untrusted")
    injection = bool(listing.get("injection_flagged"))
    side = classify_side_effects(listing)
    creds = classify_credentials(listing)
    state = "discovered"
    if policy_blocked:
        state = "policy_blocked"
    elif injection:
        state = "untrusted"
    health = "needs_setup"
    if policy_blocked:
        health = "blocked"
    return {
        "trust": trust,
        "trust_ladder": list(TRUST_ORDER),
        "marketplace_grants_trust": False,
        "instruction_authority": False,
        "auto_install": False,
        "auto_connect": False,
        "side_effect_class": side,
        "credentials": creds,
        "injection_flagged": injection,
        "injection_markers": list(INJECTION_MARKERS),
        "state": state,
        "health": health,
        "operator_approval_required": True,
    }


def allow_connection(*, operator_approved: bool, policy_blocked: bool, trust: str) -> tuple[bool, str]:
    if policy_blocked:
        return False, "policy_blocked"
    if not operator_approved:
        return False, "operator_approval_required"
    if normalize_trust(trust) in {"trusted"} and not operator_approved:
        return False, "marketplace_cannot_elevate_trust"
    return True, "operator_approved_draft_only"
