"""HADES Plugin Runtime v2 — trust ladder, capability contracts, isolation, restart truth.

Application-level enforcement only. Isolation tiers are NOT an OS sandbox.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

# --- Trust ladder -----------------------------------------------------------

TRUST_ORDER = ("untrusted", "manual", "verified", "trusted")
TRUST_ALIASES = {
    "local": "untrusted",
    "locally-converted": "untrusted",
    "converted": "untrusted",
    "user": "manual",
    "enabled": "manual",
    "signed": "verified",
    "promoted": "trusted",
}

# --- Isolation (app-level; not OS sandbox unless tier=secured) --------------

# ``secured`` routes PluginManager._run_command through execution_isolation.run_isolated
# (Linux userns+mount when available). Windows secured FS isolation remains fail-closed
# (Job Objects ≠ FS jail). Other tiers stay application-level only.
ISOLATION_TIERS = (
    "none",
    "plugin_cwd",
    "restricted_env",
    "temp_workspace",
    "container",
    "secured",
)
DEFAULT_ISOLATION = "plugin_cwd"

# Non-secret HADES runtime variables plugins may inherit without manifest declaration.
HADES_PLUGIN_RUNTIME_ENV_ALLOW = frozenset(
    {
        "HADES_DATA_DIR",
        "HADES_HOME",
        "HADES_REPO_ROOT",
        "HADES_RUNTIME_ROOT",
        "HADES_USER_DATA",
    }
)

# Env keys stripped under restricted_env / temp_workspace (plus credential-shaped keys).
RESTRICTED_ENV_DENY = frozenset(
    {
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "NPM_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "DOCKER_HOST",
    }
)

# --- Capability effects -----------------------------------------------------

EFFECT_SUBPROCESS = "subprocess"
EFFECT_NETWORK = "network"
EFFECT_READ = "read_files"
EFFECT_WRITE = "write_files"
EFFECT_SERVICE = "service"
EFFECT_MCP = "mcp"

SIDE_EFFECT_RANK = {"none": 0, "read": 1, "write": 2, "network": 3, "process": 4}
COST_CLASSES = ("cheap", "moderate", "expensive")
LATENCY_CLASSES = ("fast", "normal", "slow")


def normalize_trust(raw: str | None) -> str:
    text = str(raw or "untrusted").strip().lower()
    text = TRUST_ALIASES.get(text, text)
    return text if text in TRUST_ORDER else "untrusted"


def trust_rank(raw: str | None) -> int:
    return TRUST_ORDER.index(normalize_trust(raw))


def can_promote_trust(current: str | None, target: str | None) -> bool:
    return trust_rank(target) >= trust_rank(current)


def normalize_isolation(raw: str | None) -> str:
    text = str(raw or DEFAULT_ISOLATION).strip().lower()
    return text if text in ISOLATION_TIERS else DEFAULT_ISOLATION


def permission_strings(plugin: dict[str, Any], tool: dict[str, Any] | None = None) -> set[str]:
    values = {str(item).lower().replace("_", ":") for item in plugin.get("permissions", [])}
    if tool:
        values.update(str(item).lower().replace("_", ":") for item in tool.get("metadata", {}).get("permissions", []))
    return values


def effects_from_permissions(permissions: set[str], *, tool: dict[str, Any] | None = None, plugin: dict[str, Any] | None = None) -> list[str]:
    effects: set[str] = set()
    for item in permissions:
        if "subprocess" in item or "process" in item or "shell" in item:
            effects.add(EFFECT_SUBPROCESS)
        if "network" in item or "http" in item or "internet" in item:
            effects.add(EFFECT_NETWORK)
        if "filesystem" in item or "file" in item:
            if "write" in item or ":w" in item:
                effects.add(EFFECT_WRITE)
                effects.add(EFFECT_READ)
            elif "read" in item or ":r" in item:
                effects.add(EFFECT_READ)
            else:
                # Bare filesystem / filesystem:read → read-only.
                # Write requires an explicit token such as filesystem:write or write_files.
                effects.add(EFFECT_READ)
    action = ""
    mode = ""
    if tool:
        action = str(tool.get("metadata", {}).get("action") or tool.get("action") or tool.get("name") or "").lower()
        mode = str(tool.get("metadata", {}).get("mode") or tool.get("mode") or "").lower()
        if tool.get("metadata", {}).get("mcp_remote") or tool.get("mcp_remote"):
            effects.add(EFFECT_MCP)
    if plugin:
        for item in plugin.get("tools") or []:
            if isinstance(item, dict) and str(item.get("name", "")).lower() in {"list_tools", "call_tool"}:
                effects.add(EFFECT_MCP)
        if str(plugin.get("plugin_type") or plugin.get("manifest", {}).get("plugin_type") or "").lower() == "service":
            effects.add(EFFECT_SERVICE)
        mcp = plugin.get("manifest", {}).get("mcp") if isinstance(plugin.get("manifest"), dict) else plugin.get("mcp")
        if isinstance(mcp, dict) and mcp.get("expand_tools"):
            effects.add(EFFECT_MCP)
    if mode == "service" or action in {"start", "serve", "dev", "stop"}:
        effects.add(EFFECT_SERVICE)
        effects.add(EFFECT_SUBPROCESS)
    if not effects:
        effects.add(EFFECT_SUBPROCESS)
    return sorted(effects)


def derive_side_effect_class(effects: list[str]) -> str:
    if EFFECT_SUBPROCESS in effects or EFFECT_SERVICE in effects or EFFECT_MCP in effects:
        return "process"
    if EFFECT_NETWORK in effects:
        return "network"
    if EFFECT_WRITE in effects:
        return "write"
    if EFFECT_READ in effects:
        return "read"
    return "none"


def derive_cost_class(effects: list[str], *, tool: dict[str, Any] | None = None) -> str:
    name = str((tool or {}).get("name") or "").lower()
    if any(token in name for token in ("crawl", "train", "index", "build", "download", "scrape")):
        return "expensive"
    if EFFECT_NETWORK in effects or EFFECT_SERVICE in effects or EFFECT_MCP in effects:
        return "moderate"
    return "cheap"


def derive_latency_class(effects: list[str], *, tool: dict[str, Any] | None = None) -> str:
    mode = str((tool or {}).get("metadata", {}).get("mode") or (tool or {}).get("mode") or "").lower()
    if mode == "service" or EFFECT_SERVICE in effects:
        return "slow"
    if EFFECT_NETWORK in effects or EFFECT_MCP in effects:
        return "normal"
    return "fast"


def derive_failure_modes(effects: list[str]) -> list[str]:
    modes = {"timeout", "dependency"}
    if EFFECT_NETWORK in effects or EFFECT_MCP in effects:
        modes.add("network")
    modes.add("schema")
    if EFFECT_SERVICE in effects:
        modes.add("healthcheck")
    return sorted(modes)


def build_capability_contract(
    plugin: dict[str, Any] | None = None,
    tool: dict[str, Any] | None = None,
    *,
    permissions: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Build or normalize a capability contract for a plugin or tool."""
    existing = None
    if tool:
        existing = tool.get("capabilities") or tool.get("metadata", {}).get("capabilities")
    if existing is None and plugin:
        existing = plugin.get("capabilities") or (plugin.get("manifest") or {}).get("capabilities")
    if isinstance(existing, dict) and existing.get("effects"):
        effects = [str(item) for item in existing["effects"] if str(item).strip()]
        return {
            "effects": sorted(set(effects)),
            "side_effect_class": str(existing.get("side_effect_class") or derive_side_effect_class(effects)),
            "cost_class": str(existing.get("cost_class") or derive_cost_class(effects, tool=tool)),
            "latency_class": str(existing.get("latency_class") or derive_latency_class(effects, tool=tool)),
            "failure_modes": list(existing.get("failure_modes") or derive_failure_modes(effects)),
        }
    perms = set(permissions) if permissions is not None else permission_strings(plugin or {}, tool)
    # Also accept raw permission list strings
    if permissions is None and plugin:
        perms = {str(item).lower().replace("_", ":") for item in plugin.get("permissions", [])}
        if tool:
            perms.update(str(item).lower().replace("_", ":") for item in tool.get("metadata", {}).get("permissions", tool.get("permissions", [])))
    effects = effects_from_permissions(perms, tool=tool, plugin=plugin)
    return {
        "effects": effects,
        "side_effect_class": derive_side_effect_class(effects),
        "cost_class": derive_cost_class(effects, tool=tool),
        "latency_class": derive_latency_class(effects, tool=tool),
        "failure_modes": derive_failure_modes(effects),
    }


def enrich_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Normalize v2 fields onto a format-1 manifest (forward-compatible)."""
    out = dict(manifest)
    permissions = out.get("permissions") if isinstance(out.get("permissions"), list) else ["subprocess"]
    out["permissions"] = permissions
    out["isolation"] = normalize_isolation(out.get("isolation"))
    out["trust_default"] = normalize_trust(out.get("trust_default") or "untrusted")
    out["capabilities"] = build_capability_contract({"permissions": permissions, "plugin_type": out.get("plugin_type"), "tools": out.get("tools"), "mcp": out.get("mcp"), "manifest": out})
    # Marketplace hygiene block
    market = out.get("marketplace") if isinstance(out.get("marketplace"), dict) else {}
    market.setdefault("pinned_version", str(out.get("version") or "0.1.0"))
    if out.get("source"):
        market.setdefault("source_url", str(out.get("source")))
    if out.get("license"):
        market.setdefault("license", str(out.get("license")))
    market.setdefault("signed", bool(market.get("signature")))
    out["marketplace"] = market
    # MCP expand opt-in default for MCP-shaped plugins
    tools = out.get("tools") if isinstance(out.get("tools"), list) else []
    tool_names = {str(item.get("name", "")).lower() for item in tools if isinstance(item, dict)}
    mcp = out.get("mcp") if isinstance(out.get("mcp"), dict) else {}
    if "list_tools" in tool_names and "call_tool" in tool_names:
        mcp.setdefault("expand_tools", True)
        mcp.setdefault("transport", "stdio")
    if mcp:
        out["mcp"] = mcp
    enriched_tools: list[dict[str, Any]] = []
    for raw in tools:
        if not isinstance(raw, dict):
            continue
        tool = dict(raw)
        tool["capabilities"] = build_capability_contract(
            {"permissions": permissions, "plugin_type": out.get("plugin_type"), "mcp": out.get("mcp"), "manifest": out},
            tool,
        )
        enriched_tools.append(tool)
    out["tools"] = enriched_tools
    return out


CAPABILITY_APPROVAL_KINDS = ("network", "file_read", "file_write", "subprocess")


def required_policy_kinds(contract: dict[str, Any]) -> list[str]:
    effects = set(contract.get("effects") or [])
    kinds: list[str] = []
    if EFFECT_NETWORK in effects or EFFECT_MCP in effects:
        kinds.append("network")
    if EFFECT_READ in effects:
        kinds.append("file_read")
    if EFFECT_WRITE in effects:
        kinds.append("file_write")
    needs_subprocess = EFFECT_SUBPROCESS in effects or EFFECT_SERVICE in effects
    # MCP bridges fail closed on subprocess unless the contract is HTTP-shaped
    # (network without local process/service effects). Pure ``mcp`` (plugin expand)
    # still spawns a local bridge and must honor subprocess_policy.
    if EFFECT_MCP in effects and EFFECT_NETWORK not in effects:
        needs_subprocess = True
    if needs_subprocess:
        kinds.append("subprocess")
    return kinds


def normalize_capability_approvals(
    approvals: dict[str, bool] | None = None,
    *,
    approved_network: bool = False,
    approved_file_read: bool = False,
    approved_file_write: bool = False,
    approved_subprocess: bool = False,
    grant_kinds: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, bool]:
    """Build the per-kind approval map used at the PluginManager boundary.

    ``approved_by_user`` is intentionally not an input — it is audit-only and
    must never satisfy a side-effect ``ask`` policy by itself (F-03).
    """
    out: dict[str, bool] = {
        "network": bool(approved_network),
        "file_read": bool(approved_file_read),
        "file_write": bool(approved_file_write),
        "subprocess": bool(approved_subprocess),
    }
    if isinstance(approvals, dict):
        for kind in CAPABILITY_APPROVAL_KINDS:
            if kind in approvals:
                out[kind] = bool(approvals[kind])
            alt = f"approved_{kind}"
            if alt in approvals:
                out[kind] = bool(approvals[alt])
    if grant_kinds:
        for kind in grant_kinds:
            key = str(kind).strip().lower()
            if key in out:
                out[key] = True
    return out


def evaluate_global_side_effect_policies(
    *,
    contract: dict[str, Any],
    settings: dict[str, Any] | None,
    invocation_type: str,
    approved_by_user: bool = False,
    approvals: dict[str, bool] | None = None,
    extra_kinds: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Enforce global HADES side-effect policies at the execution boundary.

    - ``block`` always wins (including privileged/install paths).
    - ``ask`` never means allow for ``invocation_type=autonomous``.
    - Manual/install may proceed on ``ask`` only with the matching per-kind
      approval flag (``approved_subprocess``, ``approved_network``, …).
    - ``approved_by_user`` is informational/audit only — never authority for
      side-effect kinds (F-03 / PLUGIN_RUNTIME_CONTRACT).
    - Unset policy keys are not invented here (provider/runtime supplies them).
    """
    _ = bool(approved_by_user)  # retained for caller/audit signature compatibility
    cfg = settings if isinstance(settings, dict) else {}
    inv = str(invocation_type or "manual").strip().lower() or "manual"
    kind_approvals = normalize_capability_approvals(approvals)
    needed = list(required_policy_kinds(contract))
    if extra_kinds:
        for kind in extra_kinds:
            key = str(kind).strip().lower()
            if key in CAPABILITY_APPROVAL_KINDS and key not in needed:
                needed.append(key)
    for kind in needed:
        policy_key = f"{kind}_policy"
        raw = cfg.get(policy_key)
        if raw is None and kind == "network":
            raw = cfg.get("network")
        if raw is None:
            continue
        policy = str(raw).strip().lower()
        if policy == "allow":
            continue
        if policy == "block":
            return {
                "allowed": False,
                "reason": f"global {kind}_policy=block",
                "kind": kind,
                "policy": policy,
            }
        if policy == "ask":
            # Autonomous must never promote ask → allow (even with approved_by_user).
            if inv == "autonomous":
                return {
                    "allowed": False,
                    "reason": f"autonomous cannot promote {kind}_policy=ask to allow",
                    "kind": kind,
                    "policy": policy,
                    "requires_approval": True,
                }
            if not bool(kind_approvals.get(kind)):
                return {
                    "allowed": False,
                    "reason": f"explicit approval required for {kind}_policy=ask",
                    "kind": kind,
                    "policy": policy,
                    "requires_approval": True,
                }
            continue
        return {
            "allowed": False,
            "reason": f"unknown {kind}_policy={policy!r} — fail-closed",
            "kind": kind,
            "policy": policy,
        }
    return {"allowed": True, "reason": "ok", "kind": None, "policy": None}


def min_trust_for_autonomous(contract: dict[str, Any]) -> str:
    """Network/process-heavy tools need verified; write+network need trusted."""
    effects = set(contract.get("effects") or [])
    if EFFECT_WRITE in effects and EFFECT_NETWORK in effects:
        return "trusted"
    if EFFECT_NETWORK in effects or EFFECT_SERVICE in effects or EFFECT_MCP in effects or EFFECT_WRITE in effects:
        return "verified"
    return "manual"


def eligible_for_manual(plugin: dict[str, Any]) -> tuple[bool, str]:
    if not plugin.get("enabled"):
        return False, "plugin_disabled"
    if plugin.get("status") != "ready":
        return False, f"status={plugin.get('status')}"
    structural = {"dependency_failed", "integrity_failed", "unsupported_runtime", "not_ready"}
    if plugin.get("failure_state") in structural:
        return False, f"failure_state={plugin.get('failure_state')}"
    # Missing trust on raw fixtures defaults to untrusted (fail closed); DB rows always normalize trust.
    trust_value = plugin.get("trust")
    trust = "untrusted" if trust_value is None else normalize_trust(trust_value)
    if trust_rank(trust) < trust_rank("manual"):
        return False, f"trust={trust}<manual"
    return True, "ok"


def eligible_for_autonomous(plugin: dict[str, Any], tool: dict[str, Any]) -> tuple[bool, str]:
    if not plugin.get("enabled") or plugin.get("status") != "ready":
        return False, "not_ready"
    structural = {"dependency_failed", "integrity_failed", "unsupported_runtime", "not_ready"}
    if plugin.get("failure_state") in structural:
        return False, f"failure_state={plugin.get('failure_state')}"
    if not bool((plugin.get("manifest") or {}).get("autonomous", True)):
        return False, "plugin_autonomous=false"
    if not bool(tool.get("metadata", {}).get("autonomous", True)):
        return False, "tool_autonomous=false"
    contract = build_capability_contract(plugin, tool)
    needed = min_trust_for_autonomous(contract)
    trust_value = plugin.get("trust")
    trust = "untrusted" if trust_value is None else normalize_trust(trust_value)
    if trust_rank(trust) < trust_rank(needed):
        return False, f"trust={trust}<{needed}"
    return True, "ok"


def score_agent_tool(query: str, plugin: dict[str, Any], tool: dict[str, Any], contract: dict[str, Any]) -> float:
    tokens = set(re.findall(r"[a-zA-ZÀ-ÿ0-9_.-]+", query.lower()))
    text = (
        f"{plugin.get('name','')} {plugin.get('description','')} "
        f"{tool.get('name','')} {tool.get('description','')} "
        f"{' '.join(contract.get('effects') or [])} {contract.get('side_effect_class','')}"
    ).lower()
    tool_tokens = set(re.findall(r"[a-zA-ZÀ-ÿ0-9_.-]+", text))
    overlap = float(len(tokens & tool_tokens))
    exact = 4.0 if str(tool.get("name", "")).lower() in query.lower() else 0.0
    plugin_bonus = 2.0 if str(plugin.get("name", "")).lower() in query.lower() else 0.0
    category = str(plugin.get("category") or (plugin.get("manifest") or {}).get("category", ""))
    category_bonus = 1.0 if category.lower() in query.lower() else 0.0
    lexical = overlap + exact + plugin_bonus + category_bonus
    if lexical <= 0:
        # Preserve historical shortlist semantics: no lexical signal ⇒ score 0.
        return 0.0
    # Prefer cheaper/faster tools only as a tie-break on top of lexical matches.
    cost = str(contract.get("cost_class") or "moderate")
    cost_bonus = {"cheap": 0.4, "moderate": 0.2, "expensive": 0.0}.get(cost, 0.1)
    trust_bonus = 0.15 * trust_rank(plugin.get("trust"))
    mcp_bonus = 0.5 if tool.get("metadata", {}).get("mcp_remote") and "mcp" in query.lower() else 0.0
    return lexical + cost_bonus + trust_bonus + mcp_bonus


def restricted_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """Scrub credential-shaped ambient values, including secret-shaped ``HADES_*`` keys.

    Plugin processes must not inherit unrelated host/HADES secrets merely because
    the parent process holds them. Explicit tool/plugin env maps are applied by
    callers after this scrub.
    """
    env = dict(base if base is not None else os.environ)
    for key in list(env):
        upper = key.upper()
        if upper in RESTRICTED_ENV_DENY or upper.endswith("_API_KEY") or upper.endswith("_SECRET") or upper.endswith("_TOKEN"):
            env.pop(key, None)
    env["HADES_PLUGIN_ISOLATION"] = "restricted_env"
    return env


def authorized_plugin_environment(
    base: dict[str, str] | None,
    plugin: dict[str, Any],
    tool: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Build a plugin child env with explicit credential authorization.

    Starts from a scrubbed ambient map, then re-enters only:
    - non-secret runtime variables that survived scrubbing
    - credentials listed in manifest ``required_env`` / ``optional_env``
    - explicit string env from the tool metadata ``env`` map (caller may also merge)
    """
    env = restricted_environment(base)
    manifest = plugin.get("manifest") if isinstance(plugin.get("manifest"), dict) else {}
    allowed: set[str] = set()
    for field in ("required_env", "optional_env"):
        declared = manifest.get(field) or []
        if isinstance(declared, dict):
            allowed.update(str(k) for k in declared.keys())
        elif isinstance(declared, list):
            for item in declared:
                if isinstance(item, str):
                    allowed.add(item)
                elif isinstance(item, dict) and item.get("name"):
                    allowed.add(str(item["name"]))
    # Re-admit only explicitly authorized ambient credentials from the original base.
    source = dict(base if base is not None else os.environ)
    for key in allowed:
        if key in source and key not in env:
            env[key] = source[key]
    for key, value in source.items():
        if key in env:
            continue
        upper = str(key).upper()
        if upper in HADES_PLUGIN_RUNTIME_ENV_ALLOW:
            env[key] = value
    return env


def resolve_workdir(plugin: dict[str, Any], isolation: str, runtime_root: Path) -> Path:
    plugin_root = Path(plugin["local_path"]).resolve()
    if isolation in {"none", "plugin_cwd", "restricted_env", "container", "secured"}:
        return plugin_root
    if isolation == "temp_workspace":
        work = runtime_root / plugin["id"] / "workspace"
        work.mkdir(parents=True, exist_ok=True)
        return work
    return plugin_root


def service_state_path(runtime_root: Path, plugin_id: str) -> Path:
    path = runtime_root / plugin_id
    path.mkdir(parents=True, exist_ok=True)
    return path / "service.state.json"


def write_service_state(runtime_root: Path, plugin_id: str, state: dict[str, Any]) -> Path:
    path = service_state_path(runtime_root, plugin_id)
    payload = {**state, "updated_at": time.time()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_service_state(runtime_root: Path, plugin_id: str) -> dict[str, Any] | None:
    path = service_state_path(runtime_root, plugin_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def clear_service_state(runtime_root: Path, plugin_id: str) -> None:
    path = service_state_path(runtime_root, plugin_id)
    path.unlink(missing_ok=True)


def process_alive(pid: int | None) -> bool:
    if not pid or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ProcessLookupError, PermissionError, ValueError):
        return False


def process_identity_matches(pid: int | None, started_at: float | None) -> bool:
    """Best-effort identity check: PID alive; optional create-time when /proc exists."""
    if not process_alive(pid):
        return False
    if started_at is None:
        return True
    # Linux /proc create time (approximate identity)
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8", errors="ignore")
        # field 22 is starttime in clock ticks; coarse check that process exists with reasonable age
        fields = stat.split()
        if len(fields) < 22:
            return True
        # If process started long before our recorded start, treat as PID reuse
        uptime = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        boot = time.time() - uptime
        ticks = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK")) if hasattr(os, "sysconf") else 100
        proc_start = boot + (float(fields[21]) / float(ticks or 100))
        return abs(proc_start - float(started_at)) < 30.0
    except Exception:
        return True


def build_timeline(
    *,
    events: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    service_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for event in events:
        items.append(
            {
                "kind": "event",
                "id": f"event:{event.get('id')}",
                "level": event.get("level"),
                "message": event.get("message"),
                "status": event.get("level"),
                "created_at": event.get("created_at"),
                "source": "plugin_events",
            }
        )
    for call in tool_calls:
        items.append(
            {
                "kind": "tool_call",
                "id": f"call:{call.get('id')}",
                "tool_name": call.get("tool_name"),
                "status": call.get("status"),
                "message": call.get("error") or call.get("tool_name"),
                "invocation_type": call.get("invocation_type"),
                "duration_ms": call.get("duration_ms"),
                "exit_code": call.get("exit_code"),
                "created_at": call.get("started_at") or call.get("timestamp"),
                "finished_at": call.get("finished_at"),
                "source": "tool_calls",
            }
        )
    if service_state:
        items.append(
            {
                "kind": "service_state",
                "id": "service:current",
                "status": service_state.get("status") or service_state.get("health"),
                "message": f"pid={service_state.get('pid')} alive={service_state.get('alive')}",
                "created_at": service_state.get("iso_updated_at") or service_state.get("updated_at"),
                "source": "service.state.json",
                "detail": service_state,
            }
        )

    def _sort_key(item: dict[str, Any]) -> tuple[str, str]:
        created = str(item.get("created_at") or "")
        return (created, str(item.get("id") or ""))

    items.sort(key=_sort_key)
    return items


def expected_effect_summary(plugin: dict[str, Any], tool: dict[str, Any]) -> str:
    contract = build_capability_contract(plugin, tool)
    effects = ", ".join(contract.get("effects") or []) or "none"
    return (
        f"{plugin.get('name')}.{tool.get('name')}: "
        f"side_effect={contract.get('side_effect_class')}, "
        f"cost={contract.get('cost_class')}, effects=[{effects}]"
    )


def mcp_wrapper_tool(remote_name: str, description: str, input_schema: dict[str, Any] | None = None) -> dict[str, Any]:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", remote_name).strip("._") or "tool"
    return {
        "name": f"mcp__{safe}"[:120],
        "action": "mcp_call",
        "mode": "command",
        "description": description or f"MCP tool {remote_name}",
        "command": [
            "{python}",
            "hades_bridge.py",
            "--action",
            "call_tool",
            "--tool",
            remote_name,
            "--arguments",
            "{arguments}",
            "--timeout",
            "120",
        ],
        "input_schema": input_schema
        if isinstance(input_schema, dict)
        else {
            "type": "object",
            "properties": {
                "arguments": {
                    "type": "string",
                    "default": "{}",
                    "description": "JSON object string for MCP tool arguments",
                }
            },
            "additionalProperties": False,
        },
        "autonomous": False,
        "mcp_remote": True,
        "mcp_tool": remote_name,
        "capabilities": {
            "effects": [EFFECT_MCP, EFFECT_SUBPROCESS, EFFECT_NETWORK],
            "side_effect_class": "process",
            "cost_class": "moderate",
            "latency_class": "normal",
            "failure_modes": ["timeout", "network", "schema", "dependency"],
        },
    }


def validate_marketplace_hygiene(manifest: dict[str, Any], *, require_integrity_for_package: bool = False) -> list[str]:
    """Return list of hygiene warnings (empty = clean). Raises ValueError for hard failures."""
    warnings: list[str] = []
    version = str(manifest.get("version") or "").strip()
    if not version:
        raise ValueError("Marketplace-hygiëne: versie ontbreekt.")
    source = str(manifest.get("source") or (manifest.get("marketplace") or {}).get("source_url") or "").strip()
    if source.startswith(("http://", "https://")) and not source.startswith("https://"):
        warnings.append("Bron-URL is niet https.")
    market = manifest.get("marketplace") if isinstance(manifest.get("marketplace"), dict) else {}
    if not market.get("pinned_version"):
        warnings.append("pinned_version ontbreekt; afgeleid van version.")
    if require_integrity_for_package and not isinstance(manifest.get("integrity"), dict):
        raise ValueError("Marketplace-hygiëne: .HadesPlugin vereist integrity-map.")
    hades_api = str(manifest.get("hades_api") or "")
    if hades_api and not re.search(r"0\.4", hades_api):
        warnings.append(f"hades_api={hades_api} kan ouder zijn dan 0.4.x.")
    return warnings
