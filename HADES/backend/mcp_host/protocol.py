"""MCP protocol helpers shared by stdio and Streamable HTTP clients.

Versioned compatibility:
- Generation ``modern`` (2026-07-28): stateless core, ``server/discover``,
  per-request ``_meta``, Streamable HTTP ``Mcp-Method`` / ``Mcp-Name`` headers,
  no ``initialize`` / ``Mcp-Session-Id``.
- Generation ``legacy`` (2025-11-25 and earlier supported revisions):
  ``initialize`` / ``notifications/initialized`` handshake and optional
  session id on Streamable HTTP.

Wire behavior must never mix these generations in one ambiguous codepath.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

# Preference order: newest first. Support means wire-level generation handling.
SUPPORTED_PROTOCOL_VERSIONS = (
    "2026-07-28",
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
    "2024-10-07",
)
DEFAULT_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
MODERN_PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSIONS = frozenset(v for v in SUPPORTED_PROTOCOL_VERSIONS if v != MODERN_PROTOCOL_VERSION)

MAX_TOOL_LIST_PAGES = 50
MAX_PAYLOAD_BYTES = 2_000_000
MAX_SSE_BYTES = 8_000_000
MAX_STDERR_TAIL_BYTES = 2_000
CLIENT_INFO = {"name": "hades-mcp-host", "version": "1.1.0"}
CLIENT_CAPABILITIES: dict[str, Any] = {}

META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"

CONNECTION_STATUSES = (
    "configured",
    "disconnected",
    "connecting",
    "connected",
    "ready",  # 2026: config verified / discover ok (no persistent session)
    "auth_required",
    "policy_blocked",
    "error",
    "disabled",
)

ERROR_KINDS = (
    "transport",
    "protocol",
    "tool_error",
    "auth",
    "permission",
    "timeout",
    "cancelled",
    "unknown_outcome",
    "validation",
    "dependency",
    "policy",
)


def protocol_generation(version: str | None) -> str:
    if str(version or "") == MODERN_PROTOCOL_VERSION:
        return "modern"
    return "legacy"


def is_modern_protocol(version: str | None) -> bool:
    return protocol_generation(version) == "modern"


def model_tool_name(server_id: str, remote_name: str) -> str:
    """Deterministic model-compatible name with server namespace to avoid collisions."""
    safe_server = re.sub(r"[^a-zA-Z0-9_.-]+", "_", server_id).strip("._") or "server"
    safe_tool = re.sub(r"[^a-zA-Z0-9_.-]+", "_", remote_name).strip("._") or "tool"
    name = f"mcp__{safe_server}__{safe_tool}"
    if len(name) <= 120:
        return name
    digest = hashlib.sha1(f"{server_id}:{remote_name}".encode("utf-8")).hexdigest()[:10]
    return f"mcp__{safe_server[:40]}__{safe_tool[:50]}__{digest}"[:120]


def stable_tool_id(server_id: str, remote_name: str) -> str:
    return f"{server_id}::{remote_name}"


def validate_input_schema(schema: Any) -> str | None:
    """Return a human-readable limitation when the schema is unsuitable; None if OK.

    MCP 2026-07-28 loosens schemas to JSON Schema 2020-12. We accept object-rooted
    schemas and surface soft limitations for open objects / unsupported roots.
    """
    if schema is None:
        return None
    if not isinstance(schema, dict):
        return "inputSchema is not a JSON object"
    schema_type = schema.get("type", "object")
    if schema_type not in {None, "object"} and schema_type != "object":
        if isinstance(schema_type, list) and "object" in schema_type:
            return None
        return f"unsupported root schema type: {schema_type}"
    props = schema.get("properties")
    if props is not None and not isinstance(props, dict):
        return "inputSchema.properties must be an object"
    if schema.get("additionalProperties") is True:
        return "additionalProperties=true (open object; validate carefully)"
    return None


def discovery_cursor_loop(seen: set[str], cursor: str | None) -> bool:
    """True when a cursor repeats (incomplete / looping pagination)."""
    if not cursor:
        return False
    if cursor in seen:
        return True
    seen.add(cursor)
    return False


def redact_mapping(value: Any, *, key: str = "", known_secrets: list[str] | None = None) -> Any:
    """Redact secret-shaped values for logs/API/export."""
    secretish = ("token", "secret", "password", "authorization", "api_key", "apikey", "credential", "bearer")
    secrets = [s for s in (known_secrets or []) if s]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for item_key, item_value in value.items():
            lower = str(item_key).lower()
            if any(token in lower for token in secretish):
                out[str(item_key)] = "***"
            else:
                out[str(item_key)] = redact_mapping(item_value, key=str(item_key), known_secrets=secrets)
        return out
    if isinstance(value, list):
        return [redact_mapping(item, key=key, known_secrets=secrets) for item in value]
    if isinstance(value, str):
        if any(token in key.lower() for token in secretish) and value:
            return "***"
        redacted = value
        for secret in secrets:
            if secret and secret in redacted:
                redacted = redacted.replace(secret, "***")
        return redacted
    return value


def export_safe_server(server: dict[str, Any]) -> dict[str, Any]:
    """Config export without secrets or secret refs resolved."""
    env = server.get("env") if isinstance(server.get("env"), dict) else {}
    plain = env.get("plain") if isinstance(env.get("plain"), dict) else {}
    secret_keys = sorted((env.get("secret_refs") or {}).keys()) if isinstance(env.get("secret_refs"), dict) else []
    headers = server.get("headers") if isinstance(server.get("headers"), dict) else {}
    safe_headers = {
        k: v
        for k, v in headers.items()
        if "authorization" not in str(k).lower() and "token" not in str(k).lower()
    }
    metadata = redact_mapping(server.get("metadata") or {})
    if isinstance(metadata, dict):
        metadata.pop("oauth_refresh_ref", None)
        metadata.pop("oauth_access_ref", None)
    return {
        "id": server.get("id"),
        "name": server.get("name"),
        "description": server.get("description"),
        "transport": server.get("transport"),
        "enabled": bool(server.get("enabled")),
        "auto_connect": bool(server.get("auto_connect")),
        "catalog_id": server.get("catalog_id"),
        "command": server.get("command"),
        "env": {"plain": plain, "secret_keys": secret_keys},
        "endpoint_url": server.get("endpoint_url"),
        "auth_method": server.get("auth_method"),
        "headers": safe_headers,
        "timeout_seconds": server.get("timeout_seconds"),
        "owner_kind": server.get("owner_kind"),
        "owner_plugin_id": server.get("owner_plugin_id"),
        "metadata": metadata,
        "protocol_version": server.get("protocol_version"),
        "secrets_configured": bool(server.get("auth_secret_ref") or secret_keys),
    }


def json_size_ok(payload: Any, *, limit: int = MAX_PAYLOAD_BYTES) -> bool:
    try:
        return len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= limit
    except Exception:
        return False


def build_request_meta(protocol_version: str) -> dict[str, Any]:
    return {
        META_PROTOCOL_VERSION: protocol_version,
        META_CLIENT_CAPABILITIES: dict(CLIENT_CAPABILITIES),
        META_CLIENT_INFO: dict(CLIENT_INFO),
    }


def stamp_params(params: dict[str, Any] | None, *, protocol_version: str) -> dict[str, Any]:
    """Attach modern _meta to params for 2026-07-28 requests."""
    body = dict(params or {})
    if not is_modern_protocol(protocol_version):
        return body
    meta = dict(body.get("_meta") or {}) if isinstance(body.get("_meta"), dict) else {}
    meta.update(build_request_meta(protocol_version))
    body["_meta"] = meta
    return body


def methods_requiring_mcp_name(method: str) -> bool:
    """Mcp-Name is required only for tools/call, resources/read, prompts/get (SEP-2243)."""
    return method in {"tools/call", "resources/read", "prompts/get"}


def mcp_name_from_params(method: str, params: dict[str, Any] | None) -> str | None:
    if not isinstance(params, dict):
        return None
    if method in {"tools/call", "prompts/get"}:
        name = params.get("name")
        return str(name) if name is not None else None
    if method == "resources/read":
        uri = params.get("uri")
        return str(uri) if uri is not None else None
    return None


def mcp_http_headers(
    *,
    method: str,
    protocol_version: str,
    name: str | None = None,
    session_id: str | None = None,
    extra: dict[str, str] | None = None,
    param_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build Streamable HTTP headers for the negotiated protocol generation.

    Modern (2026-07-28+): MCP-Protocol-Version, Mcp-Method, and Mcp-Name when required.
    Legacy: MCP-Protocol-Version (when speaking a revision that defines it) + optional
    Mcp-Session-Id. Do NOT emit modern routing headers on legacy requests.
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    # Protocol version header exists from 2025-06-18 onward; still useful for dual-era.
    if protocol_version:
        headers["MCP-Protocol-Version"] = protocol_version

    if is_modern_protocol(protocol_version):
        headers["Mcp-Method"] = method
        if methods_requiring_mcp_name(method):
            if name is None or name == "":
                raise ValueError(f"Mcp-Name is required for modern {method}")
            headers["Mcp-Name"] = str(name)
        if param_headers:
            for key, value in param_headers.items():
                # Never allow caller extra/param to clobber reserved routing headers.
                lower = str(key).lower()
                if lower in {"mcp-method", "mcp-name", "mcp-protocol-version", "mcp-session-id", "authorization"}:
                    continue
                headers[str(key)] = str(value)
    else:
        if session_id:
            headers["Mcp-Session-Id"] = session_id

    if extra:
        for key, value in extra.items():
            lower = str(key).lower()
            # Auth/content-type from client config is allowed; never override MCP routing.
            if lower in {"mcp-method", "mcp-name", "mcp-protocol-version", "mcp-session-id"}:
                continue
            if lower.startswith("mcp-param-"):
                continue
            headers[str(key)] = str(value)
    return headers


def parse_discover_supported_versions(result: Any) -> dict[str, Any]:
    """Parse server/discover result using the normative ``supportedVersions`` field.

    Historical non-standard aliases (protocolVersions / supportedProtocolVersions)
    are accepted only as documented compatibility input and never preferred over
    the normative field when both are present.

    Returns:
      {
        "supported": list[str],
        "source": "supportedVersions" | "alias" | "missing" | "malformed",
        "raw": ...,
        "ok": bool,
      }
    """
    if not isinstance(result, dict):
        return {"supported": [], "source": "malformed", "raw": result, "ok": False}
    if "supportedVersions" in result:
        versions = result.get("supportedVersions")
        source = "supportedVersions"
    elif "protocolVersions" in result or "supportedProtocolVersions" in result:
        versions = result.get("protocolVersions") or result.get("supportedProtocolVersions")
        source = "alias"
    else:
        return {"supported": [], "source": "missing", "raw": None, "ok": False}
    if not isinstance(versions, list):
        return {"supported": [], "source": "malformed", "raw": versions, "ok": False}
    out: list[str] = []
    for item in versions:
        if item is None or isinstance(item, (dict, list, bool)):
            return {"supported": [], "source": "malformed", "raw": versions, "ok": False}
        text = str(item).strip()
        if not text:
            return {"supported": [], "source": "malformed", "raw": versions, "ok": False}
        out.append(text)
    return {"supported": out, "source": source, "raw": versions, "ok": True}


def select_mutually_supported_version(
    server_supported: list[str],
    *,
    client_supported: tuple[str, ...] | list[str] = SUPPORTED_PROTOCOL_VERSIONS,
    prefer_modern: bool = True,
) -> str | None:
    """Pick the newest mutually supported revision. Never invent unadvertised versions."""
    server_set = {str(v) for v in server_supported}
    ordered = list(client_supported)
    if not prefer_modern:
        ordered = list(reversed(ordered))
    for version in ordered:
        if version in server_set:
            return version
    return None


def validate_modern_discover_result(result: Any) -> dict[str, Any]:
    """Strict-ish validation of a 2026 DiscoverResult. Does not mark ready on failure."""
    issues: list[str] = []
    if not isinstance(result, dict):
        return {"ok": False, "issues": ["discover result is not an object"], "supported": []}
    parsed = parse_discover_supported_versions(result)
    if not parsed["ok"]:
        issues.append(f"supportedVersions {parsed['source']}")
    if result.get("resultType") not in {None, "complete"}:
        # Discover is a complete result; input_required is not applicable here.
        if result.get("resultType") == "input_required":
            issues.append("discover returned input_required")
        elif result.get("resultType") not in {"complete"}:
            issues.append(f"unexpected resultType={result.get('resultType')!r}")
    caps = result.get("capabilities")
    if caps is not None and not isinstance(caps, dict):
        issues.append("capabilities must be an object")
    return {
        "ok": not issues and bool(parsed.get("supported")),
        "issues": issues,
        "supported": parsed.get("supported") or [],
        "source": parsed.get("source"),
    }


def finite_timeout(value: Any, *, default: float = 60.0, minimum: float = 1.0, maximum: float = 600.0) -> float:
    try:
        timeout = float(value)
    except Exception:
        timeout = default
    if not math.isfinite(timeout) or timeout <= 0:
        timeout = default
    return max(minimum, min(maximum, timeout))


def connection_status_for_generation(generation: str, *, verified: bool) -> str:
    """Truthful UI/status mapping after a successful protocol verification."""
    if not verified:
        return "disconnected"
    if generation == "modern":
        return "ready"
    return "connected"


def canonical_mcp_resource_uri(endpoint_url: str) -> str:
    """Canonical MCP resource URI for RFC 8707 resource indicators.

    Prefer the most specific MCP endpoint URL (scheme+host+path), lowercase scheme/host.
    """
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse((endpoint_url or "").strip())
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "").lower()
    if not host:
        return (endpoint_url or "").strip()
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    path = parsed.path or ""
    # Drop trailing slash except for root.
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", "", ""))
