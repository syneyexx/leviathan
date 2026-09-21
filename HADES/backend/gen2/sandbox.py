"""Zero-trust plugin sandbox envelopes — path jail + host tier detection.

Tier 0/1: application-level policy + path/network allowlists (always enforceable).
Tier 2: Windows Job Objects for process/resource management (+ optional restricted
token when available). Job Objects are NOT full FS/network isolation.
Tier 3: Docker/WSL/VM when the host advertises them — never claimed without detection.

Fail closed: requesting an unavailable tier blocks execution.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Callable


SANDBOX_ACTIONS = frozenset(
    {"read", "write", "network", "subprocess", "inspect", "env", "secret"}
)

TIER_LABELS = {
    0: "trusted HADES core",
    1: "restricted subprocess",
    2: "Windows Job Object process/resource management (not full FS/network isolation)",
    3: "container/WSL/VM isolation",
}


def sandbox_honesty_labels(caps: dict[str, Any] | None = None) -> dict[str, Any]:
    """UI/API honesty labels — never claim OS isolation from Linux/API probe alone."""
    host = caps if caps is not None else detect_host_sandbox_capabilities()
    verification = str(host.get("verification_status") or "UNVERIFIED_ON_HOST")
    job = bool(host.get("job_objects"))
    return {
        "verification_status": verification,
        "os_isolation_enforced": False,
        "operationally_tested": bool(host.get("operationally_tested")),
        "tier2_label": (
            "API_PRESENT_UNTESTED" if job and verification == "API_PRESENT_UNTESTED" else "UNVERIFIED_ON_HOST"
        ),
        "tier2_scope": TIER_LABELS[2],
        "ui_badges": [
            {
                "id": "os_isolation",
                "tone": "warning",
                "text": "OS isolation UNVERIFIED_ON_HOST"
                if not job
                else "Job Object API present — not operationally_tested",
            },
            {
                "id": "tier0_1",
                "tone": "info",
                "text": "Tier 0/1 path+network envelopes enforceable on this host",
            },
        ],
        "notes": list(host.get("notes") or []),
    }


def path_is_within(candidate: Path, root: Path) -> bool:
    """True iff candidate is root or a descendant after resolve (no string-prefix jail)."""
    try:
        cand = candidate.expanduser().resolve(strict=False)
        base = root.expanduser().resolve(strict=False)
    except OSError:
        return False
    if os.name == "nt":
        cand_s = os.path.normcase(str(cand))
        base_s = os.path.normcase(str(base))
    else:
        cand_s = str(cand)
        base_s = str(base)
    try:
        Path(cand_s).relative_to(Path(base_s))
        return True
    except ValueError:
        return False


def detect_host_sandbox_capabilities() -> dict[str, Any]:
    """Probe what isolation tiers this host can actually enforce.

    Job Object *API presence* alone never sets operationally_tested=True.
    Tier 2 is only listed when the Windows Job Object enforcement module can run.
    """
    from gen2.sandbox_job import job_object_api_present, restricted_token_api_present

    is_windows = os.name == "nt" or sys.platform.startswith("win")
    job_objects = job_object_api_present()
    restricted_token = restricted_token_api_present()
    appcontainer = False
    if is_windows:
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            advapi = ctypes.windll.advapi32  # type: ignore[attr-defined]
            appcontainer = hasattr(advapi, "CreateAppContainerProfile") or hasattr(
                kernel32, "CreateAppContainerProfile"
            )
        except Exception:
            appcontainer = False

    docker = shutil.which("docker") is not None
    wsl = False
    if is_windows:
        wsl = shutil.which("wsl") is not None or shutil.which("wsl.exe") is not None
    vm_like = docker or wsl

    available = {0, 1}
    notes: list[str] = []
    # Enforcement code is implemented; availability still requires Windows Job APIs.
    enforcement_implemented = True
    if job_objects:
        available.add(2)
        notes.append("Windows Job Object enforcement module available on this host (not yet operationally_tested)")
    else:
        notes.append("Tier 2 Job Objects unavailable on this host — UNVERIFIED_ON_HOST / fail-closed")
    if vm_like:
        available.add(3)
        notes.append("Tier 3 container/WSL binary detected")
    else:
        notes.append("Tier 3 Docker/WSL not detected")
    if restricted_token:
        notes.append("Restricted Token API present (optional harden path; AppContainer not required for Tier 2)")
    if appcontainer:
        notes.append("AppContainer API present but not required/wired for current Tier 2 architecture")

    return {
        "platform": platform.system(),
        "is_windows": is_windows,
        "job_objects": job_objects,
        "job_object_enforcement_implemented": enforcement_implemented,
        "appcontainer": appcontainer,
        "restricted_token": restricted_token,
        "docker": docker,
        "wsl": wsl,
        "available_tiers": sorted(available),
        "notes": notes,
        "quality_evaluated": False,
        "operationally_tested": False,
        "os_isolation_enforced": False,  # never true from API probe alone
        "available_on_host": True,  # tiers 0/1 always
        "verification_status": "UNVERIFIED_ON_HOST" if not job_objects else "API_PRESENT_UNTESTED",
    }


def available_sandbox_tiers() -> frozenset[int]:
    caps = detect_host_sandbox_capabilities()
    return frozenset(int(t) for t in caps["available_tiers"])


def build_default_envelope(plugin_id: str, *, permissions: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    perms = {p.lower() for p in (permissions or [])}
    tier = 0 if plugin_id.startswith("hades.") or plugin_id in {"core", "hades-core"} else 1
    if "network" in perms or "filesystem" in perms:
        tier = max(tier, 1)
    available = available_sandbox_tiers()
    # Prefer highest available hardened tier when third-party + subprocess.
    # execution_mode advertises windows_job_object only when Job APIs exist; enforcement
    # is performed by WindowsJobSandbox when spawning, not by API presence alone.
    if tier >= 1 and 2 in available and ("subprocess" in perms or "filesystem" in perms):
        preferred = 2
    else:
        preferred = tier
    host_caps = detect_host_sandbox_capabilities()
    can_job = bool(host_caps.get("job_objects")) and preferred == 2 and 2 in available
    envelope = {
        "filesystem_reads": ["{data_root}/plugins/" + plugin_id, "{data_root}/plugin-outputs/" + plugin_id],
        "filesystem_writes": ["{data_root}/plugin-outputs/" + plugin_id],
        "network_domains": [] if "network" not in perms else ["*"],
        "network_policy": "deny" if "network" not in perms else "ask",
        "subprocess": "allow" if "subprocess" in perms or tier >= 1 else "deny",
        "environment_variables": [],
        "secrets": [],
        "timeout_seconds": 120,
        "cpu_limit_percent": 50,
        "ram_limit_mb": 1024,
        "working_directory": "{data_root}/plugins/" + plugin_id,
        "execution_mode": (
            "windows_job_object"
            if can_job
            else ("restricted_subprocess" if tier == 1 else "trusted_core")
        ),
        "autonomous_allowed": False,
        "approval_required": True,
        "tier": preferred if preferred in available else tier,
        "tier_labels": dict(TIER_LABELS),
        "host_capabilities": host_caps,
        "os_isolation_enforced": False,
        "notes": (
            "Tier 0/1 always enforceable. Tier 2 uses WindowsJobSandbox (Job Object + "
            "KILL_ON_JOB_CLOSE + memory/process/CPU limits) when APIs exist. "
            "API presence ≠ operationally_tested. Tier 3 requires detected Docker/WSL. "
            "Unavailable tiers fail closed. AppContainer is optional/not required for Tier 2."
        ),
    }
    return int(envelope["tier"]), envelope


def enforce_envelope_policy(
    *,
    plugin_id: str,
    envelope: dict[str, Any],
    requested_tier: int,
    action: str,
    path: str | None = None,
    network_host: str | None = None,
    autonomous: bool = False,
    approved: bool = False,
    check_approval: bool = True,
    expand_path: Callable[[str], str],
    available_tiers: frozenset[int] | None = None,
) -> dict[str, Any]:
    action_norm = str(action or "").strip().lower()
    available_enforcement = sorted(available_tiers if available_tiers is not None else available_sandbox_tiers())
    available_set = set(available_enforcement)
    violations: list[str] = []
    effective_tier: int | None = requested_tier
    block_reason: str | None = None

    if action_norm not in SANDBOX_ACTIONS:
        violations.append(f"invalid_action:{action_norm or 'missing'}")

    if check_approval:
        if autonomous and not envelope.get("autonomous_allowed") and not approved:
            violations.append("autonomous_not_allowed")
        if envelope.get("approval_required") and not approved and action_norm in {"write", "network", "subprocess"}:
            violations.append("approval_required")

    if action_norm in {"read", "write"}:
        if not path:
            violations.append("path_required")
        else:
            allowed_key = "filesystem_reads" if action_norm == "read" else "filesystem_writes"
            allowed_raw = list(envelope.get(allowed_key) or [])
            if not allowed_raw:
                violations.append("empty_filesystem_allowlist")
            else:
                allowed = [Path(expand_path(p)) for p in allowed_raw]
                try:
                    resolved = Path(path).expanduser().resolve(strict=False)
                except OSError:
                    violations.append("path_unresolvable")
                    resolved = None
                if resolved is not None and not any(path_is_within(resolved, a) for a in allowed):
                    violations.append(f"path_outside_envelope:{resolved}")

    if action_norm == "network":
        if not network_host:
            violations.append("network_host_required")
        else:
            policy = str(envelope.get("network_policy") or "deny").lower()
            if policy == "deny":
                violations.append("network_denied")
            elif policy == "ask" and check_approval and not approved:
                violations.append("network_ask_requires_approval")
            domains = list(envelope.get("network_domains") or [])
            if policy != "deny":
                if domains == ["*"]:
                    pass
                elif not domains:
                    violations.append("empty_network_allowlist")
                elif network_host not in domains and not any(
                    network_host.endswith(d) for d in domains if isinstance(d, str) and d.startswith(".")
                ):
                    violations.append(f"network_host_not_allowed:{network_host}")

    if action_norm == "subprocess":
        sub = str(envelope.get("subprocess") or "deny").lower()
        if sub in {"deny", "false", "0", "no"}:
            violations.append("subprocess_denied")

    if action_norm == "env":
        allowed_env = {str(x) for x in (envelope.get("environment_variables") or [])}
        # path carries the env var name for env checks (reuse field; no new API required).
        env_name = (path or "").strip()
        if not env_name:
            violations.append("env_name_required")
        elif allowed_env and env_name not in allowed_env:
            violations.append(f"env_not_allowed:{env_name}")
        elif not allowed_env:
            violations.append("empty_env_allowlist")

    if action_norm == "secret":
        allowed_secrets = {str(x) for x in (envelope.get("secrets") or [])}
        secret_name = (path or "").strip()
        if not secret_name:
            violations.append("secret_name_required")
        elif not allowed_secrets:
            violations.append("empty_secrets_allowlist")
        elif secret_name not in allowed_secrets:
            violations.append(f"secret_not_allowed:{secret_name}")

    if requested_tier not in available_set:
        effective_tier = None
        block_reason = "requested_tier_not_enforceable_on_host"
        violations.append("tier_unavailable")
        violations.append(f"requested_tier:{requested_tier}")

    ok = not violations
    return {
        "ok": ok,
        "plugin_id": plugin_id,
        "action": action_norm,
        "violations": violations,
        "requested_tier": requested_tier,
        "effective_tier": effective_tier if ok else None,
        "available_enforcement": available_enforcement,
        "block_reason": block_reason if not ok else None,
        "execution_mode": envelope.get("execution_mode") if ok else "blocked",
        "tier": requested_tier,
        "symlink_policy": "resolve_follows_symlinks; junctions_unverified",
        "notes": (
            "Path checks use resolve()+relative_to after canonicalization. "
            "Symlink/junction escape is not fully claimed on Windows without OS tests."
        ),
        "host_capabilities": detect_host_sandbox_capabilities(),
        "honesty": sandbox_honesty_labels(),
    }


def try_assign_job_object(pid: int) -> dict[str, Any]:
    """Best-effort assign of an existing PID. Prefer ``spawn_in_job_object`` for owned children.

    Closing a job with KILL_ON_JOB_CLOSE kills assigned processes — this helper therefore
    only reports API/assignment success and does not claim full lifecycle operational proof.
    """
    from gen2.sandbox_job import WindowsJobSandbox, job_object_api_present

    if not job_object_api_present():
        return {
            "ok": False,
            "available": False,
            "reason": "not_windows",
            "pid": pid,
            "operationally_tested": False,
            "os_isolation_enforced": False,
        }
    # Probe: create job without kill-on-close so we don't murder the target PID on close.
    sandbox = WindowsJobSandbox(
        memory_limit_mb=1024,
        process_limit=8,
        cpu_rate_percent=50,
        kill_on_job_close=False,
    )
    try:
        sandbox.open()
        sandbox.assign_pid(pid)
        return {
            "ok": True,
            "available": True,
            "reason": None,
            "pid": pid,
            "operationally_tested": False,
            "os_isolation_enforced": True,
            "limits_applied": dict(sandbox._limits_applied),
            "enforcement": "windows_job_object",
            "note": "Assigned without KILL_ON_JOB_CLOSE (probe). Use spawn_in_job_object for lifecycle.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "available": True,
            "reason": str(exc),
            "pid": pid,
            "operationally_tested": False,
            "os_isolation_enforced": False,
        }
    finally:
        sandbox.close()


def spawn_in_job_object(
    argv: list[str],
    *,
    cwd: str | None = None,
    timeout_seconds: float | None = 30.0,
    memory_limit_mb: int | None = 1024,
    process_limit: int | None = 8,
    cpu_rate_percent: int | None = 50,
) -> dict[str, Any]:
    """Spawn argv inside a Tier-2 Job Object lifecycle (Windows). Fail closed elsewhere."""
    from gen2.sandbox_job import WindowsJobSandbox

    sandbox = WindowsJobSandbox(
        memory_limit_mb=memory_limit_mb,
        process_limit=process_limit,
        cpu_rate_percent=cpu_rate_percent,
        kill_on_job_close=True,
    )
    return sandbox.run(argv, cwd=cwd, timeout_seconds=timeout_seconds).to_public()
