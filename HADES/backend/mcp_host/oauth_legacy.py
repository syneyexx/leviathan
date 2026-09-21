"""MCP OAuth (PKCE) for Streamable HTTP — RFC 9728 / 8414 / 8707 / 9207.

Desktop public client: no client secret. Tokens stored via McpSecretStore only.

Discovery order (MCP authorization-server-discovery):
1. WWW-Authenticate resource_metadata on 401
2. Path-based well-known: /.well-known/oauth-protected-resource{path}
3. Root well-known: /.well-known/oauth-protected-resource

Authorization server metadata candidates (path issuer):
1. OAuth AS metadata with path insertion
2. OIDC discovery with path insertion
3. OIDC discovery with path appending

Without path:
1. OAuth AS metadata
2. OIDC discovery

Client identity strategy (MCP auth / CIMD):
- Prefer an explicitly configured OAuth client_id on the server metadata.
- Optional Client ID Metadata Document URL when the AS supports CIMD.
- Do NOT invent a universal client id for arbitrary providers.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import httpx

from mcp_host.policy import is_loopback_url, require_network_policy, settings_approved_flag
from mcp_host.protocol import canonical_mcp_resource_uri
from mcp_host.secrets import SecretStorageUnavailable, secret_store
from url_security import UrlSecurityError, assert_public_http_url, safe_public_url

_PENDING: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
OAUTH_STATE_TTL_SECONDS = 900
_MAX_REDIRECTS = 3

_WWW_AUTH_PARAM_RE = re.compile(
    r'([Hh][Tt][Tt][Pp][Ss]?|[A-Za-z0-9_]+)\s*=\s*("(?:\\.|[^"\\])*"|[^,\s]+)'
)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def parse_www_authenticate(header_value: str | None) -> dict[str, Any]:
    """Parse a Bearer WWW-Authenticate challenge into a dict of parameters."""
    if not header_value:
        return {}
    out: dict[str, Any] = {"raw": header_value}
    text = header_value.strip()
    scheme, _, rest = text.partition(" ")
    out["scheme"] = scheme
    for match in _WWW_AUTH_PARAM_RE.finditer(rest or text):
        key = match.group(1).lower()
        value = match.group(2)
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"')
        out[key] = value
    return out


def protected_resource_metadata_urls(endpoint_url: str) -> list[str]:
    """RFC 9728 / MCP ordered well-known candidates for an MCP endpoint URL."""
    parsed = urlparse((endpoint_url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return []
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or ""
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
    candidates: list[str] = []
    if path and path != "/":
        candidates.append(urljoin(origin + "/", f".well-known/oauth-protected-resource{path}"))
    candidates.append(urljoin(origin + "/", ".well-known/oauth-protected-resource"))
    # De-dupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def authorization_server_metadata_urls(issuer: str) -> list[str]:
    """MCP-required AS metadata candidate URLs for an issuer identifier."""
    raw = (issuer or "").rstrip("/")
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return []
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or ""
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
    if path and path != "/":
        return [
            f"{origin}/.well-known/oauth-authorization-server{path}",
            f"{origin}/.well-known/openid-configuration{path}",
            f"{origin}{path}/.well-known/openid-configuration",
        ]
    return [
        f"{origin}/.well-known/oauth-authorization-server",
        f"{origin}/.well-known/openid-configuration",
    ]


def _is_explicit_loopback_host(host: str) -> bool:
    normalized = (host or "").lower().strip("[]")
    return normalized in {"localhost", "127.0.0.1", "::1"}


def _safe_fetch_url(url: str, *, allow_private: bool, purpose: str) -> str | None:
    """Validate an OAuth fetch target with context-bound loopback permission.

    OAuth traffic carrying metadata/codes/tokens must use HTTPS off-host. The
    private exception is deliberately limited to explicit loopback and is only
    active when the caller proves the original MCP/OAuth context is local.
    """
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower().strip("[]")
    local = _is_explicit_loopback_host(host)
    if parsed.scheme == "http" and not (allow_private and local):
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    try:
        assert_public_http_url(
            url,
            allow_private=bool(allow_private and local),
            purpose=purpose,
        )
    except (UrlSecurityError, ValueError):
        return None
    return url


def _get_json(
    client: httpx.Client,
    url: str,
    *,
    allow_private: bool,
    purpose: str,
    findings: list[str],
) -> dict[str, Any] | None:
    safe = _safe_fetch_url(url, allow_private=allow_private, purpose=purpose)
    if not safe:
        findings.append(f"{url}: blocked by SSRF/TLS policy")
        return None
    current = safe
    for _ in range(_MAX_REDIRECTS + 1):
        try:
            response = client.get(current, headers={"Accept": "application/json"})
        except Exception as exc:
            findings.append(f"{current}: {exc}")
            return None
        if response.status_code in {301, 302, 303, 307, 308}:
            loc = response.headers.get("Location")
            if not loc:
                findings.append(f"{current}: redirect without Location")
                return None
            nxt = urljoin(current, loc)
            if not _safe_fetch_url(nxt, allow_private=allow_private, purpose=purpose):
                findings.append(f"{nxt}: redirect blocked by SSRF/TLS policy")
                return None
            current = nxt
            continue
        if response.status_code == 404:
            findings.append(f"{current}: 404")
            return None
        if response.status_code >= 400:
            findings.append(f"{current}: HTTP {response.status_code}")
            return None
        try:
            data = response.json()
        except Exception:
            findings.append(f"{current}: invalid JSON")
            return None
        if not isinstance(data, dict):
            findings.append(f"{current}: JSON was not an object")
            return None
        return data
    findings.append(f"{url}: too many redirects")
    return None


def discover_auth(
    endpoint_url: str,
    *,
    allow_private: bool = False,
    settings: dict[str, Any] | None = None,
    www_authenticate: str | None = None,
    probe_unauthorized: bool = True,
) -> dict[str, Any]:
    """RFC 9728 protected resource metadata discovery for MCP HTTP endpoints."""
    if settings is not None:
        require_network_policy(
            settings,
            endpoint_url=endpoint_url,
            approved=settings_approved_flag(settings, "mcp.network_approved", "approved_network", "network_approved"),
            purpose="mcp_oauth_discovery",
        )
    findings: list[str] = []
    candidates: list[str] = []
    challenge = parse_www_authenticate(www_authenticate)
    resource_metadata_url = challenge.get("resource_metadata")
    if isinstance(resource_metadata_url, str) and resource_metadata_url.strip():
        candidates.append(resource_metadata_url.strip())

    with httpx.Client(timeout=20.0, follow_redirects=False) as client:
        if probe_unauthorized and not resource_metadata_url:
            # Attempt an unauthenticated probe to capture WWW-Authenticate.
            safe_endpoint = _safe_fetch_url(endpoint_url, allow_private=allow_private, purpose="mcp_oauth_probe")
            if safe_endpoint:
                try:
                    probe = client.post(
                        safe_endpoint,
                        headers={"Accept": "application/json", "Content-Type": "application/json"},
                        content=b"{}",
                    )
                    if probe.status_code in {401, 403}:
                        challenge = parse_www_authenticate(probe.headers.get("WWW-Authenticate"))
                        meta = challenge.get("resource_metadata")
                        if isinstance(meta, str) and meta.strip():
                            candidates.insert(0, meta.strip())
                except Exception as exc:
                    findings.append(f"probe: {exc}")

        for url in protected_resource_metadata_urls(endpoint_url):
            if url not in candidates:
                candidates.append(url)

        for url in candidates:
            data = _get_json(
                client,
                url,
                allow_private=allow_private,
                purpose="mcp_oauth_discovery",
                findings=findings,
            )
            if not data:
                continue
            auth_servers = data.get("authorization_servers")
            if not auth_servers and data.get("authorization_server"):
                auth_servers = [data.get("authorization_server")]
            if not auth_servers:
                findings.append(f"{url}: missing authorization_servers")
                continue
            resource = data.get("resource") or canonical_mcp_resource_uri(endpoint_url)
            return {
                "ok": True,
                "resource_metadata": data,
                "authorization_servers": list(auth_servers or []),
                "scopes_supported": data.get("scopes_supported") or [],
                "discovery_url": url,
                "resource": resource,
                "www_authenticate": challenge or None,
            }
    return {"ok": False, "error": "Geen OAuth protected-resource metadata gevonden", "findings": findings}


def fetch_authorization_server_metadata(
    issuer: str,
    *,
    allow_private: bool = False,
) -> dict[str, Any]:
    """Discover and validate AS metadata; issuer in document must match."""
    expected = str(issuer or "").rstrip("/")
    findings: list[str] = []
    with httpx.Client(timeout=20.0, follow_redirects=False) as client:
        for url in authorization_server_metadata_urls(expected):
            data = _get_json(
                client,
                url,
                allow_private=allow_private,
                purpose="mcp_oauth_as",
                findings=findings,
            )
            if not data:
                continue
            meta_issuer = str(data.get("issuer") or "").rstrip("/")
            if meta_issuer != expected:
                findings.append(f"{url}: issuer mismatch {meta_issuer!r} != {expected!r}")
                continue
            authorize = str(data.get("authorization_endpoint") or "").strip()
            token_endpoint = str(data.get("token_endpoint") or "").strip()
            if not authorize or not token_endpoint:
                findings.append(f"{url}: missing authorization_endpoint/token_endpoint")
                continue
            for endpoint_name, endpoint_url in (
                ("authorization_endpoint", authorize),
                ("token_endpoint", token_endpoint),
            ):
                if not _safe_fetch_url(endpoint_url, allow_private=allow_private, purpose="mcp_oauth_as_endpoint"):
                    findings.append(f"{url}: {endpoint_name} blocked by SSRF/TLS policy")
                    break
            else:
                return {"ok": True, "metadata": data, "discovery_url": url, "issuer": expected}
    return {"ok": False, "error": "Authorization server metadata niet gevonden", "findings": findings}


def validate_pkce_s256(as_meta: dict[str, Any]) -> dict[str, Any]:
    """Fail closed unless S256 is advertised when the field is present or required."""
    methods = as_meta.get("code_challenge_methods_supported")
    if methods is None:
        return {
            "ok": False,
            "error": "code_challenge_methods_supported ontbreekt — PKCE S256 kan niet worden geverifieerd",
        }
    if not isinstance(methods, list):
        return {"ok": False, "error": "code_challenge_methods_supported is malformed"}
    normalized = [str(item) for item in methods]
    if "S256" not in normalized:
        return {
            "ok": False,
            "error": "Authorization server ondersteunt geen S256 PKCE (plain-only/afwezig geweigerd)",
            "code_challenge_methods_supported": normalized,
        }
    return {"ok": True, "code_challenge_methods_supported": normalized}


def assert_redirect_uri_valid(redirect_uri: str) -> None:
    parsed = urlparse((redirect_uri or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("redirect_uri must be an absolute http(s) URI")
    if parsed.username or parsed.password:
        raise ValueError("redirect_uri credentials are not allowed")
    if parsed.scheme == "http" and not is_loopback_url(redirect_uri):
        raise ValueError("redirect_uri must use HTTPS unless it is loopback")
    if parsed.fragment:
        raise ValueError("redirect_uri MUST NOT contain a URI fragment")


def sanitize_ui_return_url(url: str | None, *, default: str) -> str:
    """Allow only loopback http(s) SPA return URLs — prevent open redirects after OAuth."""
    fallback = (default or "").strip() or "http://127.0.0.1:3000/#/mcp"
    raw = (url or "").strip()
    if not raw:
        return fallback
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return fallback
    if parsed.username or parsed.password:
        return fallback
    if not is_loopback_url(raw):
        return fallback
    return raw


def start_oauth_flow(
    *,
    server_id: str,
    endpoint_url: str,
    redirect_uri: str,
    client_id: str | None = None,
    client_metadata_url: str | None = None,
    allow_private: bool = False,
    settings: dict[str, Any] | None = None,
    authorization_server_metadata: dict[str, Any] | None = None,
    resource_metadata: dict[str, Any] | None = None,
    ui_return_url: str | None = None,
    resource: str | None = None,
) -> dict[str, Any]:
    assert_redirect_uri_valid(redirect_uri)
    ui_return_url = sanitize_ui_return_url(ui_return_url, default="http://127.0.0.1:3000/#/mcp") if ui_return_url else None
    if settings is not None:
        require_network_policy(
            settings,
            endpoint_url=endpoint_url,
            approved=settings_approved_flag(settings, "mcp.network_approved", "approved_network", "network_approved"),
            purpose="mcp_oauth_start",
        )
    if resource_metadata:
        discovery = {
            "ok": True,
            "resource_metadata": resource_metadata,
            "authorization_servers": list(resource_metadata.get("authorization_servers") or []),
            "scopes_supported": resource_metadata.get("scopes_supported") or [],
            "resource": resource_metadata.get("resource") or canonical_mcp_resource_uri(endpoint_url),
        }
    else:
        discovery = discover_auth(endpoint_url, allow_private=allow_private, settings=None)
    if not discovery.get("ok"):
        return {"ok": False, "status": "auth_required", "error": discovery.get("error"), "discovery": discovery}
    auth_servers = discovery.get("authorization_servers") or []
    if not auth_servers:
        return {"ok": False, "status": "auth_required", "error": "Geen authorization_server in metadata", "discovery": discovery}
    issuer = str(auth_servers[0]).rstrip("/")
    if not _safe_fetch_url(issuer, allow_private=allow_private, purpose="mcp_oauth_issuer"):
        return {"ok": False, "error": "Authorization server issuer geblokkeerd door SSRF/TLS policy"}
    resolved_client_id = (client_id or client_metadata_url or "").strip()
    if not resolved_client_id:
        return {
            "ok": False,
            "status": "auth_required",
            "error": (
                "Geen OAuth client_id geconfigureerd. Stel metadata.oauth_client_id in "
                "(of een Client ID Metadata Document URL). GitHub remote MCP vereist een "
                "GitHub App/OAuth App — gebruik anders Bearer/PAT."
            ),
            "discovery": discovery,
            "registration_required": True,
        }
    if authorization_server_metadata is not None:
        as_meta = authorization_server_metadata
        # Still require issuer consistency when provided.
        meta_issuer = str(as_meta.get("issuer") or issuer).rstrip("/")
        if str(as_meta.get("issuer") or "").rstrip("/") and meta_issuer != issuer:
            return {"ok": False, "error": "Authorization server issuer mismatch"}
    else:
        fetched = fetch_authorization_server_metadata(issuer, allow_private=allow_private)
        if not fetched.get("ok"):
            return {"ok": False, "error": fetched.get("error"), "findings": fetched.get("findings")}
        as_meta = fetched["metadata"]
    pkce = validate_pkce_s256(as_meta if isinstance(as_meta, dict) else {})
    if not pkce.get("ok"):
        return {"ok": False, "error": pkce.get("error"), "authorization_server_metadata": as_meta}
    authorize = str((as_meta or {}).get("authorization_endpoint") or "").strip()
    token_endpoint = str((as_meta or {}).get("token_endpoint") or "").strip()
    meta_issuer = str((as_meta or {}).get("issuer") or issuer).rstrip("/")
    if not authorize or not token_endpoint:
        return {
            "ok": False,
            "error": "authorization_endpoint/token_endpoint ontbreekt",
            "authorization_server_metadata": as_meta,
        }
    for endpoint_name, endpoint_value in (("authorization_endpoint", authorize), ("token_endpoint", token_endpoint)):
        if not _safe_fetch_url(endpoint_value, allow_private=allow_private, purpose=f"mcp_oauth_{endpoint_name}"):
            return {"ok": False, "error": f"{endpoint_name} geblokkeerd door SSRF/TLS policy"}
    resource_uri = (resource or discovery.get("resource") or canonical_mcp_resource_uri(endpoint_url)).strip()
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    scopes = discovery.get("scopes_supported") or []
    scope = " ".join(scopes[:8]) if scopes else ""
    params = {
        "response_type": "code",
        "client_id": resolved_client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": resource_uri,
    }
    if scope:
        params["scope"] = scope
    auth_url = authorize + ("&" if "?" in authorize else "?") + urlencode(params)
    with _LOCK:
        _PENDING[state] = {
            "server_id": server_id,
            "verifier": verifier,
            "redirect_uri": redirect_uri,
            "client_id": resolved_client_id,
            "token_endpoint": token_endpoint,
            "created_at": time.time(),
            "endpoint_url": endpoint_url,
            "issuer": meta_issuer,
            "resource": resource_uri,
            "ui_return_url": ui_return_url,
            "allow_private": bool(allow_private),
            "used": False,
        }
    return {
        "ok": True,
        "status": "auth_required",
        "authorization_url": auth_url,
        "state": state,
        "redirect_uri": redirect_uri,
        "resource": resource_uri,
        "pkce": True,
        "client_secret_required": False,
        "issuer": meta_issuer,
        "discovery": discovery,
    }


def _store_tokens_atomically(
    *,
    server_id: str,
    access: str,
    refresh: str | None,
    previous_refresh_ref: str | None = None,
) -> dict[str, Any]:
    """Store access (+ optional refresh). Roll back access if refresh store fails."""
    access_ref = secret_store.new_ref(server_id, "oauth_access")
    secret_store.store(access_ref, str(access))
    refresh_ref = None
    if refresh:
        refresh_ref = secret_store.new_ref(server_id, "oauth_refresh")
        try:
            secret_store.store(refresh_ref, str(refresh))
        except Exception as exc:
            # Roll back newly stored access token so we do not orphan a usable secret
            # without a durable refresh path / metadata link.
            secret_store.delete(access_ref, missing_ok=True)
            raise SecretStorageUnavailable(f"Refresh token opslaan mislukt: {exc}") from exc
        if previous_refresh_ref and previous_refresh_ref != refresh_ref:
            deleted = secret_store.delete(previous_refresh_ref, missing_ok=True)
            if not deleted.get("ok"):
                # New secrets are stored; surface cleanup failure without rolling back session.
                return {
                    "access_ref": access_ref,
                    "refresh_ref": refresh_ref,
                    "cleanup_warning": deleted,
                }
    return {"access_ref": access_ref, "refresh_ref": refresh_ref}


def complete_oauth_flow(*, state: str, code: str, iss: str | None = None) -> dict[str, Any]:
    # Never log `code`.
    with _LOCK:
        pending = _PENDING.get(state)
        if not pending:
            return {"ok": False, "error": "Ongeldige of verlopen OAuth state"}
        if pending.get("used"):
            return {"ok": False, "error": "OAuth state is al gebruikt (replay geweigerd)"}
        if time.time() - float(pending.get("created_at") or 0) > OAUTH_STATE_TTL_SECONDS:
            _PENDING.pop(state, None)
            return {"ok": False, "error": "OAuth-sessie verlopen"}
        pending["used"] = True
        snapshot = dict(pending)
        _PENDING.pop(state, None)
    expected_issuer = str(snapshot.get("issuer") or "").rstrip("/")
    if iss is not None and expected_issuer:
        if str(iss).rstrip("/") != expected_issuer:
            return {"ok": False, "error": "OAuth issuer mismatch (RFC 9207)"}
    token_endpoint = snapshot["token_endpoint"]
    resource_uri = str(snapshot.get("resource") or "").strip()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": snapshot["redirect_uri"],
        "client_id": snapshot["client_id"],
        "code_verifier": snapshot["verifier"],
    }
    if resource_uri:
        data["resource"] = resource_uri
    safe = _safe_fetch_url(
        token_endpoint,
        allow_private=bool(snapshot.get("allow_private")),
        purpose="mcp_oauth_token_exchange",
    )
    if not safe:
        return {"ok": False, "error": f"Token endpoint geblokkeerd door netwerkbeleid: {token_endpoint}"}
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        try:
            response = client.post(safe, data=data, headers={"Accept": "application/json"})
        except Exception as exc:
            return {"ok": False, "error": f"Token exchange mislukt: {exc}"}
    if response.status_code >= 400:
        # Do not echo token endpoint bodies that may contain sensitive diagnostics.
        return {"ok": False, "error": f"Token exchange HTTP {response.status_code}"}
    try:
        token_payload = response.json()
    except Exception:
        return {"ok": False, "error": "Token response was geen JSON"}
    access = token_payload.get("access_token")
    if not access:
        return {"ok": False, "error": "Geen access_token in OAuth-response"}
    refresh = token_payload.get("refresh_token")
    server_id = snapshot["server_id"]
    try:
        stored = _store_tokens_atomically(server_id=server_id, access=str(access), refresh=str(refresh) if refresh else None)
    except SecretStorageUnavailable as exc:
        return {"ok": False, "error": str(exc)}
    expires_at = None
    try:
        if token_payload.get("expires_in") is not None:
            expires_at = time.time() + float(token_payload["expires_in"])
    except Exception:
        expires_at = None
    return {
        "ok": True,
        "server_id": server_id,
        "auth_secret_ref": stored["access_ref"],
        "refresh_secret_ref": stored.get("refresh_ref"),
        "token_type": token_payload.get("token_type") or "Bearer",
        "expires_in": token_payload.get("expires_in"),
        "expires_at": expires_at,
        "issuer": expected_issuer,
        "client_id": snapshot["client_id"],
        "resource": resource_uri,
        "endpoint_url": snapshot.get("endpoint_url"),
        "ui_return_url": snapshot.get("ui_return_url"),
        "token_endpoint": token_endpoint,
        # Never return raw tokens to callers.
    }


def refresh_oauth_token(
    *,
    server_id: str,
    refresh_ref: str,
    token_endpoint: str,
    client_id: str,
    issuer: str | None = None,
    resource: str | None = None,
    allow_private: bool = False,
) -> dict[str, Any]:
    refresh = secret_store.get(refresh_ref)
    if not refresh:
        return {"ok": False, "error": "Geen refresh token", "reauth_required": True}
    safe = _safe_fetch_url(token_endpoint, allow_private=allow_private, purpose="mcp_oauth_refresh")
    if not safe:
        return {"ok": False, "error": f"Token endpoint geblokkeerd: {token_endpoint}"}
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": client_id,
    }
    if resource:
        data["resource"] = resource
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        try:
            response = client.post(safe, data=data, headers={"Accept": "application/json"})
        except Exception as exc:
            return {"ok": False, "error": f"Refresh mislukt: {exc}"}
    if response.status_code >= 400:
        body = response.text[:300]
        reauth = "invalid_grant" in body.lower() or response.status_code in {400, 401}
        return {"ok": False, "error": f"Refresh HTTP {response.status_code}", "reauth_required": reauth}
    try:
        token_payload = response.json()
    except Exception:
        return {"ok": False, "error": "Refresh response was geen JSON"}
    access = token_payload.get("access_token")
    if not access:
        return {"ok": False, "error": "Geen access_token bij refresh", "reauth_required": True}
    new_refresh = token_payload.get("refresh_token")
    try:
        stored = _store_tokens_atomically(
            server_id=server_id,
            access=str(access),
            refresh=str(new_refresh) if new_refresh else None,
            previous_refresh_ref=refresh_ref if new_refresh else None,
        )
    except SecretStorageUnavailable as exc:
        return {"ok": False, "error": str(exc)}
    expires_at = None
    try:
        if token_payload.get("expires_in") is not None:
            expires_at = time.time() + float(token_payload["expires_in"])
    except Exception:
        expires_at = None
    return {
        "ok": True,
        "auth_secret_ref": stored["access_ref"],
        "refresh_secret_ref": stored.get("refresh_ref") or refresh_ref,
        "expires_in": token_payload.get("expires_in"),
        "expires_at": expires_at,
        "issuer": issuer,
        "resource": resource,
        "rotated_refresh": bool(new_refresh),
    }


def cancel_oauth_flow(state: str) -> bool:
    with _LOCK:
        return _PENDING.pop(state, None) is not None


def peek_oauth_pending(state: str) -> dict[str, Any] | None:
    with _LOCK:
        pending = _PENDING.get(state)
        return dict(pending) if pending else None
