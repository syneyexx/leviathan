"""Failure-atomic OAuth token staging for the MCP manager.

The OAuth protocol module owns discovery/PKCE/state and token HTTP exchanges.
This helper exists specifically for refresh-token rotation across two durable
stores (OS keyring + SQLite): it never deletes the old DB-referenced token refs.
The manager binds the returned new refs in SQLite first and performs old-secret
cleanup only after that commit succeeds.
"""

from __future__ import annotations

import time
from typing import Any

from mcp_host.oauth import _safe_fetch_url
from mcp_host.secrets import SecretStorageUnavailable, secret_store
from secure_http_transport import create_safe_http_client


def _rollback_new_refs(refs: list[str]) -> None:
    failures: list[str] = []
    seen: set[str] = set()
    for ref in reversed(refs):
        if not ref or ref in seen:
            continue
        seen.add(ref)
        result = secret_store.delete(ref, missing_ok=True)
        if not result.get("ok"):
            failures.append(f"{ref}:{result.get('error') or result.get('error_type') or 'delete_failed'}")
    if failures:
        raise SecretStorageUnavailable(
            "OAuth token staging rollback kon nieuwe refs niet volledig opruimen: " + "; ".join(failures)
        )


def refresh_oauth_token_staged(
    *,
    server_id: str,
    refresh_ref: str,
    token_endpoint: str,
    client_id: str,
    issuer: str | None = None,
    resource: str | None = None,
    allow_private: bool = False,
) -> dict[str, Any]:
    """Refresh OAuth credentials without deleting any currently bound secret ref."""
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
    try:
        with create_safe_http_client(
            timeout=30.0,
            follow_redirects=False,
            # OAuth private-mode is restricted by _safe_fetch_url to explicit
            # loopback development endpoints. Enforce the same narrow policy at
            # the actual TCP connect boundary so DNS cannot rebind afterwards.
            allow_loopback=allow_private,
        ) as client:
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

    new_refs: list[str] = []
    access_ref = secret_store.new_ref(server_id, "oauth_access")
    try:
        secret_store.store(access_ref, str(access))
        new_refs.append(access_ref)
        refresh_secret_ref: str | None = None
        if new_refresh:
            refresh_secret_ref = secret_store.new_ref(server_id, "oauth_refresh")
            secret_store.store(refresh_secret_ref, str(new_refresh))
            new_refs.append(refresh_secret_ref)
    except Exception as exc:
        try:
            _rollback_new_refs(new_refs)
        except Exception as rollback_exc:
            raise SecretStorageUnavailable(
                f"OAuth token staging faalde en rollback was incompleet: {rollback_exc}"
            ) from exc
        if isinstance(exc, SecretStorageUnavailable):
            raise
        raise SecretStorageUnavailable(f"OAuth tokens veilig opslaan mislukt: {exc}") from exc

    expires_at = None
    try:
        if token_payload.get("expires_in") is not None:
            expires_at = time.time() + float(token_payload["expires_in"])
    except Exception:
        expires_at = None

    cleanup_refs = [refresh_ref] if new_refresh and refresh_ref != refresh_secret_ref else []
    return {
        "ok": True,
        "auth_secret_ref": access_ref,
        "refresh_secret_ref": refresh_secret_ref or refresh_ref,
        "expires_in": token_payload.get("expires_in"),
        "expires_at": expires_at,
        "issuer": issuer,
        "resource": resource,
        "rotated_refresh": bool(new_refresh),
        "new_secret_refs": new_refs,
        "cleanup_refs": cleanup_refs,
    }


def rollback_staged_oauth_refs(refs: list[str] | tuple[str, ...] | None) -> None:
    """Public rollback used when SQLite binding fails after token staging."""
    _rollback_new_refs([str(ref) for ref in (refs or []) if ref])