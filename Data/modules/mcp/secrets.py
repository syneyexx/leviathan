"""Secret reference resolution for MCP server env injection.

Never persist plaintext secrets in MCP server rows.
Resolve only at process launch / request time.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any, Mapping

from Data.modules.common.secrets import looks_like_secret, redact_secrets

from .errors import MCP_SECRET_UNRESOLVED, McpError

# Minimal host env keys safe to pass into untrusted MCP children (Round 8).
# Full ``os.environ`` inheritance is opt-in only — default is allowlist.
_SAFE_INHERIT_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "TERM",
    }
)

# Known sensitive env key substrings — plaintext values must never live in env_public.
_DEFAULT_SENSITIVE_NAME_PARTS: frozenset[str] = frozenset(
    {
        "API_KEY",
        "APIKEY",
        "TOKEN",
        "PASSWORD",
        "AUTHORIZATION",
        "COOKIE",
        "SECRET",
        "PRIVATE_KEY",
        "CREDENTIAL",
        "PASSWD",
        "ACCESS_KEY",
    }
)

_SENSITIVE_NAME_RE = re.compile(
    r"(API[_-]?KEY|TOKEN|PASSWORD|AUTHORIZATION|COOKIE|SECRET|PRIVATE[_-]?KEY|"
    r"CREDENTIAL|PASSWD|ACCESS[_-]?KEY)",
    re.IGNORECASE,
)

MCP_PLAINTEXT_SECRET_REJECTED = "MCP_PLAINTEXT_SECRET_REJECTED"


def configured_sensitive_env_names() -> frozenset[str]:
    """Extra sensitive names from ``LEVIATHAN_MCP_SENSITIVE_ENV_KEYS`` (comma-separated)."""
    raw = (os.environ.get("LEVIATHAN_MCP_SENSITIVE_ENV_KEYS") or "").strip()
    if not raw:
        return frozenset()
    return frozenset(part.strip().upper() for part in raw.split(",") if part.strip())


def is_secret_env_name(key: str, *, extra_names: Mapping[str, Any] | None = None) -> bool:
    """Classify an env key as secret-bearing (must use secret_refs, never env_public)."""
    text = str(key or "").strip()
    if not text:
        return False
    upper = text.upper()
    extras = configured_sensitive_env_names()
    if extra_names:
        extras = extras | frozenset(str(k).strip().upper() for k in extra_names if str(k).strip())
    if upper in extras or upper in _DEFAULT_SENSITIVE_NAME_PARTS:
        return True
    if any(part in upper for part in _DEFAULT_SENSITIVE_NAME_PARTS):
        return True
    if any(extra and extra in upper for extra in extras):
        return True
    return bool(_SENSITIVE_NAME_RE.search(upper))


def validate_public_env(
    env_public: Mapping[str, str] | None,
    *,
    extra_sensitive_names: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Reject known sensitive keys (and secret-shaped values) from public env config.

    Returns a sanitized copy. Raises ``McpError(MCP_PLAINTEXT_SECRET_REJECTED)`` on violation.
    """
    if not env_public:
        return {}
    cleaned: dict[str, str] = {}
    rejected: list[str] = []
    for key, value in env_public.items():
        name = str(key)
        val = "" if value is None else str(value)
        if is_secret_env_name(name, extra_names=extra_sensitive_names):
            rejected.append(name)
            continue
        if val and looks_like_secret(val):
            rejected.append(name)
            continue
        cleaned[name] = val
    if rejected:
        raise McpError(
            MCP_PLAINTEXT_SECRET_REJECTED,
            "Plaintext secrets must not be stored in MCP public env; use secret_refs",
            details={
                "rejected_keys": sorted(set(rejected)),
                "hint": "Pass secret_refs like {\"API_KEY\": \"secret:MY_API_KEY\"}",
            },
        )
    return cleaned


def normalize_secret_refs(secret_refs: Mapping[str, str] | None) -> dict[str, str]:
    """Normalize secret ref map; values must be refs, never plaintext blobs."""
    if not secret_refs:
        return {}
    out: dict[str, str] = {}
    for key, ref in secret_refs.items():
        name = str(key)
        text = str(ref or "").strip()
        if not text:
            raise McpError(MCP_SECRET_UNRESOLVED, f"Empty secret reference for {name}")
        # Reject accidental plaintext (no ref prefix and looks secret-shaped).
        if not (
            text.startswith("secret:")
            or text.startswith("env:")
            or "/" in text
            or text.isidentifier()
            or text.replace(".", "_").replace("-", "_").isidentifier()
        ):
            if looks_like_secret(text):
                raise McpError(
                    MCP_PLAINTEXT_SECRET_REJECTED,
                    f"secret_refs[{name}] looks like a plaintext secret; use secret:NAME or env:NAME",
                    details={"key": name},
                )
        out[name] = text
    return out


def resolve_secret_ref(ref: str, *, overrides: Mapping[str, str] | None = None) -> str:
    """Resolve a secret reference.

    Supported forms:
      secret:ENV_NAME          → os.environ[ENV_NAME]
      env:ENV_NAME             → os.environ[ENV_NAME]
      secret:mcp/github        → os.environ[LEVIATHAN_SECRET_MCP_GITHUB] or MCP_GITHUB
    """
    if overrides and ref in overrides:
        return overrides[ref]
    text = (ref or "").strip()
    if text == "":
        raise McpError(MCP_SECRET_UNRESOLVED, "Empty secret reference")

    if text.startswith("secret:") or text.startswith("env:"):
        key = text.split(":", 1)[1].strip()
    else:
        key = text

    # Path-like refs → env key.
    if "/" in key or "." in key:
        env_key = "LEVIATHAN_SECRET_" + key.upper().replace("/", "_").replace(".", "_").replace("-", "_")
        alt = key.upper().replace("/", "_").replace(".", "_").replace("-", "_")
        value = os.environ.get(env_key) or os.environ.get(alt)
    else:
        value = os.environ.get(key)

    if value is None or value == "":
        raise McpError(
            MCP_SECRET_UNRESOLVED,
            f"Secret reference unresolved: {ref}",
            details={"ref": ref},
        )
    return value


def build_process_env(
    *,
    env_public: Mapping[str, str],
    secret_refs: Mapping[str, str],
    overrides: Mapping[str, str] | None = None,
    inherit: bool = False,
) -> tuple[dict[str, str], list[str]]:
    """Build subprocess env and return (env, secret_values_for_redaction).

    Default ``inherit=False`` copies only ``_SAFE_INHERIT_KEYS`` so AWS_*/API
    keys from the parent do not leak into MCP children. Pass ``inherit=True``
    only when an operator explicitly needs full parent env.

    Secret refs are resolved only here (process creation), never earlier.
    """
    # Fail closed: refuse to inject sensitive keys from public env even if a
    # legacy row slipped past validation.
    safe_public = {}
    for key, value in (env_public or {}).items():
        if is_secret_env_name(str(key)):
            continue
        safe_public[str(key)] = str(value)

    if inherit:
        env: dict[str, str] = dict(os.environ)
    else:
        env = {k: v for k, v in os.environ.items() if k in _SAFE_INHERIT_KEYS}
    for key, value in safe_public.items():
        env[str(key)] = str(value)
    secret_values: list[str] = []
    for key, ref in (secret_refs or {}).items():
        resolved = resolve_secret_ref(str(ref), overrides=overrides)
        env[str(key)] = resolved
        secret_values.append(resolved)
    return env, secret_values


def redact_for_payload(
    value: Any,
    *,
    secret_values: list[str] | None = None,
    preserve_keys: frozenset[str] | None = None,
) -> Any:
    """Redact secret material from API / log payloads (structure-preserving).

    ``preserve_keys`` (e.g. ``secret_refs``) keep their string values intact —
    refs are not plaintext secrets and must remain operator-visible.
    """
    keep = preserve_keys or frozenset({"secret_refs"})
    if isinstance(value, str):
        out = value
        for secret in secret_values or []:
            if secret:
                out = out.replace(secret, "***REDACTED***")
        return redact_secrets(out)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key in keep:
                out[key] = v
            else:
                out[key] = redact_for_payload(v, secret_values=secret_values, preserve_keys=keep)
        return out
    if isinstance(value, list):
        return [
            redact_for_payload(item, secret_values=secret_values, preserve_keys=keep) for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            redact_for_payload(item, secret_values=secret_values, preserve_keys=keep) for item in value
        )
    return value


def scrub_legacy_public_env_row(
    env_public: Mapping[str, Any] | None,
    secret_refs: Mapping[str, Any] | None,
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Split sensitive keys out of public env into secret_refs (no plaintext kept).

    Returns ``(env_public, secret_refs, scrubbed_key_names)``. Scrubbed values are
    discarded from public env; refs point at ``env:KEY`` so operators can supply
    host env — plaintext is never written back.
    """
    public: dict[str, str] = {}
    refs: dict[str, str] = {str(k): str(v) for k, v in (secret_refs or {}).items()}
    scrubbed: list[str] = []
    for key, value in (env_public or {}).items():
        name = str(key)
        val = "" if value is None else str(value)
        if is_secret_env_name(name) or (val and looks_like_secret(val)):
            scrubbed.append(name)
            if name not in refs:
                # Prefer env:NAME so resolution reads host env of the same key.
                refs[name] = f"env:{name}"
            continue
        public[name] = val
    return public, refs, scrubbed


def scrub_mcp_server_secrets(
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Migration helper: scrub plaintext secrets from mcp_servers.env_public_json.

    Report includes counts and key *names* only — never secret values.
    """
    report: dict[str, Any] = {
        "servers_scanned": 0,
        "servers_scrubbed": 0,
        "keys_scrubbed": 0,
        "scrubbed_key_names": [],
    }
    try:
        rows = conn.execute(
            "SELECT server_id, env_public_json, secret_refs_json FROM mcp_servers"
        ).fetchall()
    except sqlite3.Error:
        return report

    scrubbed_names: set[str] = set()
    for row in rows:
        report["servers_scanned"] += 1
        try:
            env_public = json.loads(row["env_public_json"] or "{}")
        except Exception:  # noqa: BLE001
            env_public = {}
        try:
            secret_refs = json.loads(row["secret_refs_json"] or "{}")
        except Exception:  # noqa: BLE001
            secret_refs = {}
        if not isinstance(env_public, dict):
            env_public = {}
        if not isinstance(secret_refs, dict):
            secret_refs = {}
        new_public, new_refs, scrubbed = scrub_legacy_public_env_row(env_public, secret_refs)
        if not scrubbed:
            continue
        report["servers_scrubbed"] += 1
        report["keys_scrubbed"] += len(scrubbed)
        scrubbed_names.update(scrubbed)
        conn.execute(
            "UPDATE mcp_servers SET env_public_json = ?, secret_refs_json = ? WHERE server_id = ?",
            (json.dumps(new_public), json.dumps(new_refs), row["server_id"]),
        )
    report["scrubbed_key_names"] = sorted(scrubbed_names)
    return report
