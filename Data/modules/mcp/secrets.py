"""Secret reference resolution for MCP server env injection.

Never persist plaintext secrets in MCP server rows.
Resolve only at process launch / request time.
"""

from __future__ import annotations

import os
from typing import Mapping

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
    """
    if inherit:
        env: dict[str, str] = dict(os.environ)
    else:
        env = {k: v for k, v in os.environ.items() if k in _SAFE_INHERIT_KEYS}
    for key, value in env_public.items():
        env[str(key)] = str(value)
    secret_values: list[str] = []
    for key, ref in secret_refs.items():
        resolved = resolve_secret_ref(str(ref), overrides=overrides)
        env[str(key)] = resolved
        secret_values.append(resolved)
    return env, secret_values
