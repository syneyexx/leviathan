"""Sandbox policy profiles — personal / strict / research / coding.

Profiles are deterministic capability envelopes. They never delegate allow/deny
to an LLM. Tier availability still comes from host probes (fail-closed).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from gen2.sandbox import available_sandbox_tiers, build_default_envelope, detect_host_sandbox_capabilities

POLICY_PROFILE_IDS = ("personal", "strict", "research", "coding")

_PROFILE_SPECS: dict[str, dict[str, Any]] = {
    "personal": {
        "label": "Personal",
        "description": "Balanced local use; network ask; moderate resource caps.",
        "permissions": ["filesystem", "subprocess"],
        "network_policy": "ask",
        "timeout_seconds": 180,
        "cpu_limit_percent": 60,
        "ram_limit_mb": 1536,
        "preferred_tier": 1,
        "jit_grants": True,
        "grant_ttl_seconds": 3600,
    },
    "strict": {
        "label": "Strict",
        "description": "Least privilege; network deny; short timeouts; no autonomous grants.",
        "permissions": ["filesystem"],
        "network_policy": "deny",
        "timeout_seconds": 60,
        "cpu_limit_percent": 30,
        "ram_limit_mb": 512,
        "preferred_tier": 2,
        "jit_grants": False,
        "grant_ttl_seconds": 0,
    },
    "research": {
        "label": "Research",
        "description": "Retrieval-oriented; network ask; larger context/timeouts.",
        "permissions": ["filesystem", "network", "subprocess"],
        "network_policy": "ask",
        "timeout_seconds": 300,
        "cpu_limit_percent": 50,
        "ram_limit_mb": 2048,
        "preferred_tier": 1,
        "jit_grants": True,
        "grant_ttl_seconds": 7200,
    },
    "coding": {
        "label": "Coding",
        "description": "Local build/test; subprocess allow; network ask for deps.",
        "permissions": ["filesystem", "subprocess", "network"],
        "network_policy": "ask",
        "timeout_seconds": 600,
        "cpu_limit_percent": 80,
        "ram_limit_mb": 4096,
        "preferred_tier": 2,
        "jit_grants": True,
        "grant_ttl_seconds": 1800,
    },
}


def list_policy_profiles() -> list[dict[str, Any]]:
    host = detect_host_sandbox_capabilities()
    available = available_sandbox_tiers()
    out: list[dict[str, Any]] = []
    for pid in POLICY_PROFILE_IDS:
        spec = _PROFILE_SPECS[pid]
        preferred = int(spec["preferred_tier"])
        effective_tier = preferred if preferred in available else max(t for t in available if t <= preferred)
        out.append(
            {
                "id": pid,
                "label": spec["label"],
                "description": spec["description"],
                "permissions": list(spec["permissions"]),
                "network_policy": spec["network_policy"],
                "timeout_seconds": spec["timeout_seconds"],
                "cpu_limit_percent": spec["cpu_limit_percent"],
                "ram_limit_mb": spec["ram_limit_mb"],
                "preferred_tier": preferred,
                "effective_tier": effective_tier,
                "tier_available": preferred in available,
                "jit_grants": bool(spec["jit_grants"]),
                "grant_ttl_seconds": int(spec["grant_ttl_seconds"]),
                "host_verification_status": host.get("verification_status"),
                "security_decided_by": "policy_profile",
                "note": (
                    "effective_tier may be lower than preferred when host lacks Job Objects/containers"
                    if preferred not in available
                    else "preferred tier available on host probe"
                ),
            }
        )
    return out


def get_policy_profile(profile_id: str) -> dict[str, Any]:
    pid = (profile_id or "").strip().lower()
    if pid not in _PROFILE_SPECS:
        raise ValueError(f"unknown_policy_profile:{profile_id}")
    for row in list_policy_profiles():
        if row["id"] == pid:
            return row
    raise ValueError(f"unknown_policy_profile:{profile_id}")


def envelope_for_profile(plugin_id: str, profile_id: str) -> dict[str, Any]:
    """Build a capability envelope from a named policy profile."""
    profile = get_policy_profile(profile_id)
    tier, envelope = build_default_envelope(plugin_id, permissions=list(profile["permissions"]))
    env = deepcopy(envelope)
    env["network_policy"] = profile["network_policy"]
    if profile["network_policy"] == "deny":
        env["network_domains"] = []
    # Subprocess follows profile permissions — never inherit tier>=1 allow for strict.
    env["subprocess"] = "allow" if "subprocess" in profile["permissions"] else "deny"
    env["timeout_seconds"] = profile["timeout_seconds"]
    env["cpu_limit_percent"] = profile["cpu_limit_percent"]
    env["ram_limit_mb"] = profile["ram_limit_mb"]
    env["policy_profile"] = profile["id"]
    env["jit_grants"] = profile["jit_grants"]
    env["grant_ttl_seconds"] = profile["grant_ttl_seconds"]
    # Prefer profile effective tier when higher than default, still fail-closed via enforce.
    preferred = int(profile["effective_tier"])
    return {
        "plugin_id": plugin_id,
        "tier": max(tier, preferred) if preferred in available_sandbox_tiers() else tier,
        "envelope": env,
        "profile": profile,
    }


ALLOWED_JIT_CAPABILITIES = frozenset(
    {"network", "subprocess", "filesystem", "env", "secret", "read", "write"}
)


def jit_grant(
    *,
    plugin_id: str,
    profile_id: str,
    capability: str,
    reason: str,
    now_iso: str,
    expires_iso: str | None = None,
) -> dict[str, Any]:
    """Issue a just-in-time grant record (caller persists). Denied when profile forbids JIT."""
    profile = get_policy_profile(profile_id)
    cap = (capability or "").strip().lower()
    if cap not in ALLOWED_JIT_CAPABILITIES:
        return {
            "ok": False,
            "plugin_id": plugin_id,
            "capability": cap,
            "blocked": True,
            "reason": "unknown_jit_capability",
            "profile_id": profile_id,
            "allowed_capabilities": sorted(ALLOWED_JIT_CAPABILITIES),
        }
    if not profile.get("jit_grants"):
        return {
            "ok": False,
            "plugin_id": plugin_id,
            "capability": cap,
            "blocked": True,
            "reason": "policy_profile_disallows_jit",
            "profile_id": profile_id,
            "honesty": "strict profile refuses JIT — least privilege by design",
        }
    return {
        "ok": True,
        "plugin_id": plugin_id,
        "capability": cap,
        "reason": (reason or "")[:500],
        "profile_id": profile_id,
        "granted_at": now_iso,
        "expires_at": expires_iso,
        "ttl_seconds": profile["grant_ttl_seconds"],
        "blocked": False,
        "status": "active",
        "security_decided_by": "policy_profile_jit",
        "honesty": "JIT grant is application-level; not OS isolation",
    }


def revoke_jit_grant_payload(
    *,
    grant_id: str,
    plugin_id: str,
    capability: str,
    reason: str,
    now_iso: str,
) -> dict[str, Any]:
    """Build a revoke record for a previously issued JIT grant (caller persists)."""
    return {
        "ok": True,
        "grant_id": grant_id,
        "plugin_id": plugin_id,
        "capability": (capability or "").strip().lower(),
        "status": "revoked",
        "revoked_at": now_iso,
        "revoke_reason": (reason or "")[:500],
        "security_decided_by": "policy_profile_jit_revoke",
    }


def jit_ux_panel_model(profile_id: str | None = None) -> dict[str, Any]:
    """Honest UX model for Mission Control / Settings JIT panel."""
    profiles = list_policy_profiles()
    selected = None
    if profile_id:
        try:
            selected = get_policy_profile(profile_id)
        except ValueError:
            selected = None
    return {
        "profiles": profiles,
        "selected": selected,
        "allowed_capabilities": sorted(ALLOWED_JIT_CAPABILITIES),
        "actions": ["apply_profile", "request_jit_grant", "revoke_jit_grant", "list_jit_grants"],
        "honesty": [
            "Security decisions come from policy_profile, never from the LLM.",
            "JIT grants expire; strict profile refuses grants.",
            "Application-level only — OS isolation remains UNVERIFIED_ON_HOST without Windows selftest.",
        ],
    }
