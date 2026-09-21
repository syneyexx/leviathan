"""Hardened public MCP manager.

The stable implementation lives in :mod:`mcp_host.manager_core`. This thin
layer keeps security/truth invariants reviewable without subtly rewriting the
large execution/orchestration implementation.
"""

from __future__ import annotations

import copy
import time
from typing import Any
from urllib.parse import urlparse

from mcp_host.catalog import catalog_items, enrich_catalog_status
from mcp_host.clients import HttpMcpClient, McpClientError
from mcp_host.header_secrets import (
    HEADER_CLEANUP_FAILURES_KEY,
    HEADER_CLEANUP_PENDING_KEY,
    HEADER_SECRET_PREFIX,
    HeaderSecretStage,
    is_sensitive_header_name,
    migrate_plaintext_sensitive_headers,
    normalize_sensitive_headers,
    persist_header_cleanup_failures,
    resolve_sensitive_headers,
    retry_pending_header_secret_cleanup,
    stage_sensitive_headers,
)
from mcp_host.manager_core import (
    McpManager as _McpManagerCore,
    get_mcp_manager,
    is_mcp_tool_metadata,
    set_mcp_manager,
)
from mcp_host.oauth import complete_oauth_flow, discover_auth, start_oauth_flow
from mcp_host.oauth_tokens import refresh_oauth_token_staged, rollback_staged_oauth_refs
from mcp_host.policy import McpPolicyError, require_network_policy
from mcp_host.protocol import (
    canonical_mcp_resource_uri,
    connection_status_for_generation,
    export_safe_server,
    finite_timeout,
    protocol_generation,
    redact_mapping,
)
from mcp_host.secrets import SecretStorageUnavailable, secret_store

_OAUTH_CLEANUP_PENDING_KEY = "oauth_secret_cleanup_pending"
_OAUTH_CLEANUP_FAILURES_KEY = "oauth_secret_cleanup_failures"

_INTERNAL_METADATA_KEYS = frozenset(
    {
        "oauth_refresh_ref",
        "oauth_access_ref",
        "oauth_issuer",
        "oauth_expires_at",
        "oauth_resource",
        "oauth_token_endpoint",
        "secret_cleanup_failures",
        "secret_cleanup_pending",
        HEADER_CLEANUP_PENDING_KEY,
        HEADER_CLEANUP_FAILURES_KEY,
        _OAUTH_CLEANUP_PENDING_KEY,
        _OAUTH_CLEANUP_FAILURES_KEY,
    }
)


def _explicit_loopback_endpoint(url: str | None) -> bool:
    try:
        host = (urlparse(str(url or "")).hostname or "").lower().strip("[]")
    except Exception:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _unique_refs(refs: list[str] | tuple[str, ...] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in refs or []:
        ref = str(raw or "")
        if ref and ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


class McpManager(_McpManagerCore):
    """Core manager plus fail-closed security and live-truth invariants."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.oauth_secret_cleanup = self._retry_pending_oauth_secret_cleanup()
        self.header_secret_cleanup = retry_pending_header_secret_cleanup(self.store)
        self.header_secret_migration = migrate_plaintext_sensitive_headers(self.store)

    # --- Public status/config views ------------------------------------

    def _public_server_view(self, server: dict[str, Any]) -> dict[str, Any]:
        safe = copy.deepcopy(server)
        safe.pop("auth_secret_ref", None)
        env = safe.get("env") if isinstance(safe.get("env"), dict) else {}
        refs = env.get("secret_refs") if isinstance(env.get("secret_refs"), dict) else {}
        safe["env"] = {
            "plain": dict(env.get("plain") or {}),
            "secret_keys": sorted(
                key for key in refs.keys() if not str(key).startswith(HEADER_SECRET_PREFIX)
            ),
        }
        safe["headers"] = redact_mapping(safe.get("headers") or {})
        metadata = redact_mapping(safe.get("metadata") or {})
        if isinstance(metadata, dict):
            metadata = {
                str(key): value
                for key, value in metadata.items()
                if str(key) not in _INTERNAL_METADATA_KEYS
            }
        safe["metadata"] = metadata if isinstance(metadata, dict) else {}
        return safe

    def catalog(self) -> dict[str, Any]:
        self.reconcile_plugin_servers()
        servers = self.store.list_servers()
        for server in servers:
            self._annotate_server(server)
        items = enrich_catalog_status(catalog_items(), servers)
        return {"items": items, "count": len(items), "secret_storage": secret_store.available()}

    def list_servers(self) -> list[dict[str, Any]]:
        self.reconcile_plugin_servers()
        servers = self.store.list_servers()
        for server in servers:
            self._annotate_server(server)
        return [self._public_server_view(server) for server in servers]

    def get_server(self, server_id: str) -> dict[str, Any] | None:
        server = self.store.get_server(server_id)
        if not server:
            return None
        self._annotate_server(server)
        return self._public_server_view(server)

    def export_config(self) -> dict[str, Any]:
        """Export portable MCP config without secret refs or secret-bearing values."""
        servers: list[dict[str, Any]] = []
        for raw in self.store.list_servers():
            safe = export_safe_server(raw)
            raw_env = raw.get("env") if isinstance(raw.get("env"), dict) else {}
            raw_refs = raw_env.get("secret_refs") if isinstance(raw_env.get("secret_refs"), dict) else {}
            safe_env = safe.get("env") if isinstance(safe.get("env"), dict) else {}
            safe["env"] = {
                "plain": dict(safe_env.get("plain") or {}),
                "secret_keys": sorted(
                    str(key)
                    for key in (safe_env.get("secret_keys") or [])
                    if not str(key).startswith(HEADER_SECRET_PREFIX)
                ),
            }
            safe["headers"] = {
                str(key): ("***" if is_sensitive_header_name(str(key)) else str(value))
                for key, value in (safe.get("headers") or {}).items()
            }
            metadata = safe.get("metadata") if isinstance(safe.get("metadata"), dict) else {}
            safe["metadata"] = {
                str(key): value
                for key, value in metadata.items()
                if str(key) not in _INTERNAL_METADATA_KEYS
            }
            safe["secrets_configured"] = bool(raw.get("auth_secret_ref") or raw_refs)
            servers.append(safe)
        return {"servers": servers, "secret_storage": secret_store.available()}

    # --- Generic durable secret cleanup --------------------------------

    def _persist_oauth_cleanup_failures(self, server_id: str, failures: list[dict[str, str]]) -> None:
        server = self.store.get_server(server_id)
        if not server:
            raise SecretStorageUnavailable(
                "OAuth secret cleanup faalde nadat de serverrij verdween; refs konden niet duurzaam worden gekoppeld"
            )
        metadata = dict(server.get("metadata") or {})
        had_pending = _OAUTH_CLEANUP_PENDING_KEY in metadata or _OAUTH_CLEANUP_FAILURES_KEY in metadata
        if not failures and not had_pending:
            return
        if failures:
            metadata[_OAUTH_CLEANUP_PENDING_KEY] = [item["ref"] for item in failures]
            metadata[_OAUTH_CLEANUP_FAILURES_KEY] = failures
        else:
            metadata.pop(_OAUTH_CLEANUP_PENDING_KEY, None)
            metadata.pop(_OAUTH_CLEANUP_FAILURES_KEY, None)
        server["metadata"] = metadata
        env = server.get("env") if isinstance(server.get("env"), dict) else {}
        server["env"] = {"plain": env.get("plain") or {}, "secret_refs": env.get("secret_refs") or {}}
        self.store.upsert_server(server)

    def _retry_pending_oauth_secret_cleanup(self) -> dict[str, Any]:
        attempted = 0
        remaining_total = 0
        for server in self.store.list_servers():
            metadata = dict(server.get("metadata") or {})
            pending = _unique_refs(metadata.get(_OAUTH_CLEANUP_PENDING_KEY) or [])
            if not pending:
                continue
            attempted += len(pending)
            remaining: list[dict[str, str]] = []
            for ref in pending:
                result = secret_store.delete(ref, missing_ok=True)
                if not result.get("ok"):
                    remaining.append(
                        {
                            "ref": ref,
                            "error": str(result.get("error") or result.get("error_type") or "delete_failed"),
                        }
                    )
            self._persist_oauth_cleanup_failures(str(server["id"]), remaining)
            remaining_total += len(remaining)
        if remaining_total:
            raise SecretStorageUnavailable(
                f"{remaining_total} oude OAuth secret(s) konden niet veilig worden opgeruimd"
            )
        return {"ok": True, "attempted": attempted, "remaining": 0}

    def _cleanup_oauth_refs_after_commit(self, server_id: str, refs: list[str]) -> None:
        server = self.store.get_server(server_id)
        if not server:
            raise SecretStorageUnavailable("OAuth cleanup kon serverrij na commit niet teruglezen")
        metadata = dict(server.get("metadata") or {})
        prior_pending = _unique_refs(metadata.get(_OAUTH_CLEANUP_PENDING_KEY) or [])
        targets = _unique_refs([*refs, *prior_pending])
        if not targets:
            return
        failures: list[dict[str, str]] = []
        for ref in targets:
            result = secret_store.delete(ref, missing_ok=True)
            if not result.get("ok"):
                failures.append(
                    {
                        "ref": ref,
                        "error": str(result.get("error") or result.get("error_type") or "delete_failed"),
                    }
                )
        self._persist_oauth_cleanup_failures(server_id, failures)
        if not failures:
            return
        self.store.update_server_status(
            server_id,
            connection_status="error",
            last_error="Oude OAuth secrets konden niet volledig worden opgeruimd",
            last_error_kind="dependency",
        )
        raise SecretStorageUnavailable(
            "Nieuwe OAuth credentials zijn gebonden, maar oude secrets konden niet veilig worden opgeruimd; "
            "de server blijft geblokkeerd tot cleanup slaagt"
        )

    def _discard_unbound_oauth_refs(self, refs: list[str] | tuple[str, ...] | None) -> None:
        rollback_staged_oauth_refs(_unique_refs(refs))

    def _collect_secret_refs(self, server: dict[str, Any]) -> list[str]:
        """Include current refs plus durable cleanup refs when deleting a server."""
        refs = list(super()._collect_secret_refs(server))
        metadata = server.get("metadata") if isinstance(server.get("metadata"), dict) else {}
        for key in (
            "secret_cleanup_pending",
            HEADER_CLEANUP_PENDING_KEY,
            _OAUTH_CLEANUP_PENDING_KEY,
        ):
            refs.extend(str(ref) for ref in (metadata.get(key) or []) if ref)
        return _unique_refs(refs)

    # --- Config normalization / secret lifecycle -----------------------

    def _sanitize_config_payload(
        self,
        payload: dict[str, Any],
        *,
        existing: dict[str, Any] | None,
    ) -> dict[str, Any]:
        safe_payload = copy.deepcopy(payload)
        incoming_metadata = safe_payload.get("metadata")
        if incoming_metadata is not None and not isinstance(incoming_metadata, dict):
            raise ValueError("metadata must be an object")
        existing_metadata = dict((existing or {}).get("metadata") or {})
        if incoming_metadata is not None:
            merged_metadata = dict(existing_metadata)
            for key, value in incoming_metadata.items():
                if str(key) in _INTERNAL_METADATA_KEYS:
                    continue
                merged_metadata[str(key)] = value
            safe_payload["metadata"] = merged_metadata
        return safe_payload

    def _prepare_server_payload(
        self,
        payload: dict[str, Any],
        *,
        existing: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], HeaderSecretStage]:
        safe_payload = self._sanitize_config_payload(payload, existing=existing)
        body = super()._normalize_server_payload(safe_payload, existing=existing)
        env = body.get("env") if isinstance(body.get("env"), dict) else {}
        refs = dict(env.get("secret_refs") or {})

        if body.get("transport") == "streamable_http":
            clean_headers, refs, stage = stage_sensitive_headers(
                server_id=str(body["id"]),
                headers=dict(body.get("headers") or {}),
                existing_secret_refs=refs,
            )
            body["headers"] = clean_headers
            body["env"] = {"plain": {}, "secret_refs": refs}
            return body, stage

        stage = HeaderSecretStage()
        kept_refs: dict[str, str] = {}
        for key, ref in refs.items():
            if str(key).startswith(HEADER_SECRET_PREFIX):
                if ref:
                    stage.cleanup_after_commit.append(str(ref))
            else:
                kept_refs[str(key)] = str(ref)
        body["env"] = {"plain": env.get("plain") or {}, "secret_refs": kept_refs}
        return body, stage

    def _rollback_header_stage(self, stage: HeaderSecretStage, original: Exception) -> None:
        try:
            stage.rollback()
        except Exception as rollback_exc:
            raise SecretStorageUnavailable(
                f"MCP-config write faalde en header-secret rollback was incompleet: {rollback_exc}"
            ) from original

    def _commit_header_stage(self, server_id: str, stage: HeaderSecretStage) -> None:
        failures = stage.commit()
        if not failures:
            return
        persist_header_cleanup_failures(self.store, server_id, failures)
        self.store.update_server_status(
            server_id,
            connection_status="error",
            last_error="Oude MCP HTTP-header secrets konden niet volledig worden opgeruimd",
            last_error_kind="dependency",
        )
        raise SecretStorageUnavailable(
            "MCP-config is opgeslagen, maar oude HTTP-header secrets konden niet veilig worden opgeruimd; "
            "de server blijft geblokkeerd tot cleanup slaagt"
        )

    def _normalize_server_payload(
        self,
        payload: dict[str, Any],
        *,
        existing: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Compatibility path; production CRUD uses staged persistence below."""
        safe_payload = self._sanitize_config_payload(payload, existing=existing)
        body = super()._normalize_server_payload(safe_payload, existing=existing)
        if body.get("transport") != "streamable_http":
            return body
        env = body.get("env") if isinstance(body.get("env"), dict) else {}
        refs = dict(env.get("secret_refs") or {})
        clean_headers, refs = normalize_sensitive_headers(
            server_id=str(body["id"]),
            headers=dict(body.get("headers") or {}),
            existing_secret_refs=refs,
        )
        body["headers"] = clean_headers
        body["env"] = {"plain": {}, "secret_refs": refs}
        return body

    def create_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        body, stage = self._prepare_server_payload(payload, existing=None)
        if not self._mcp_enabled() and body.get("enabled", True):
            exc = PermissionError("MCP is uitgeschakeld in instellingen (mcp.enabled)")
            self._rollback_header_stage(stage, exc)
            raise exc
        try:
            server = self.store.upsert_server(body)
        except Exception as exc:
            self._rollback_header_stage(stage, exc)
            raise
        self._commit_header_stage(str(server["id"]), stage)
        if server.get("auto_connect") and server.get("enabled"):
            try:
                self.connect(server["id"])
            except Exception as exc:
                self.store.update_server_status(
                    server["id"],
                    connection_status="error",
                    last_error=str(exc),
                    last_error_kind=getattr(exc, "kind", "transport"),
                )
        return self.get_server(server["id"])  # type: ignore[return-value]

    def update_server(self, server_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.store.get_server(server_id)
        if not existing:
            raise KeyError(server_id)
        if existing.get("owner_kind") == "plugin":
            allowed = {"enabled", "auto_connect", "description", "timeout_seconds", "name"}
            filtered = {k: v for k, v in payload.items() if k in allowed}
            merged = {**existing, **filtered}
            env = existing.get("env") or {}
            merged["env"] = {"plain": env.get("plain") or {}, "secret_refs": env.get("secret_refs") or {}}
            server = self.store.upsert_server(merged)
            self._mirror_plugin_state(server)
            return self.get_server(server_id)  # type: ignore[return-value]

        metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
        if metadata.get(HEADER_CLEANUP_PENDING_KEY):
            retry_pending_header_secret_cleanup(self.store)
            existing = self.store.get_server(server_id) or existing
            metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
        if metadata.get(_OAUTH_CLEANUP_PENDING_KEY):
            self._retry_pending_oauth_secret_cleanup()
            existing = self.store.get_server(server_id) or existing

        body, stage = self._prepare_server_payload(payload, existing=existing)
        body["id"] = server_id
        with self._session_lock:
            was_live = server_id in self._sessions
        try:
            server = self.store.upsert_server(body)
        except Exception as exc:
            self._rollback_header_stage(stage, exc)
            raise
        self._commit_header_stage(server_id, stage)
        if was_live:
            self.disconnect(server_id)
            if server.get("enabled"):
                self.connect(server_id)
        return self.get_server(server_id)  # type: ignore[return-value]

    # --- Transport / OAuth --------------------------------------------

    def _build_client(
        self,
        server: dict[str, Any],
        *,
        approval_id: str | None = None,
        internal_rebuild: bool = False,
    ) -> Any:
        if server.get("transport") == "stdio":
            cleaned = copy.deepcopy(server)
            env = cleaned.get("env") if isinstance(cleaned.get("env"), dict) else {}
            refs = {
                str(k): str(v)
                for k, v in (env.get("secret_refs") or {}).items()
                if not str(k).startswith(HEADER_SECRET_PREFIX)
            }
            cleaned["env"] = {"plain": env.get("plain") or {}, "secret_refs": refs}
            return super()._build_client(
                cleaned,
                approval_id=approval_id,
                internal_rebuild=internal_rebuild,
            )

        metadata = server.get("metadata") if isinstance(server.get("metadata"), dict) else {}
        if metadata.get(HEADER_CLEANUP_PENDING_KEY):
            retry_pending_header_secret_cleanup(self.store)
            server = self.store.get_server(server["id"]) or server
            metadata = server.get("metadata") if isinstance(server.get("metadata"), dict) else {}
        if metadata.get(_OAUTH_CLEANUP_PENDING_KEY):
            self._retry_pending_oauth_secret_cleanup()
            server = self.store.get_server(server["id"]) or server

        timeout = finite_timeout(server.get("timeout_seconds") or 60)
        settings = self._settings()
        self._maybe_refresh_oauth(server)
        server = self.store.get_server(server["id"]) or server
        env = server.get("env") if isinstance(server.get("env"), dict) else {}
        try:
            headers = resolve_sensitive_headers(
                dict(server.get("headers") or {}),
                dict(env.get("secret_refs") or {}),
            )
        except SecretStorageUnavailable as exc:
            raise McpClientError(str(exc), kind="auth") from exc

        token = None
        if server.get("auth_method") in {"bearer", "oauth"}:
            try:
                token = secret_store.get(server.get("auth_secret_ref"))
            except SecretStorageUnavailable as exc:
                raise McpClientError(str(exc), kind="auth") from exc
            if not token:
                raise McpClientError("Authenticatie vereist — geen token in veilige opslag", kind="auth")

        endpoint = str(server.get("endpoint_url") or "")
        approved = internal_rebuild or self._policy_approved(
            server,
            effect="mcp_http_connect",
            approval_id=approval_id,
        )
        require_network_policy(
            settings,
            endpoint_url=endpoint,
            approved=approved,
            purpose="mcp_http_connect",
        )
        return HttpMcpClient(
            endpoint,
            headers=headers,
            bearer_token=token,
            timeout=timeout,
            allow_private=_explicit_loopback_endpoint(endpoint),
        )

    def _maybe_refresh_oauth(self, server: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        if server.get("auth_method") != "oauth":
            return {"ok": True, "skipped": "not_oauth"}
        meta = server.get("metadata") if isinstance(server.get("metadata"), dict) else {}
        if meta.get(_OAUTH_CLEANUP_PENDING_KEY):
            self._retry_pending_oauth_secret_cleanup()
            server = self.store.get_server(server["id"]) or server
            meta = server.get("metadata") if isinstance(server.get("metadata"), dict) else {}
        refresh_ref = meta.get("oauth_refresh_ref")
        token_endpoint = meta.get("oauth_token_endpoint")
        client_id = meta.get("oauth_client_id")
        expires_at = meta.get("oauth_expires_at")
        if not refresh_ref or not token_endpoint or not client_id:
            if force:
                return {"ok": False, "reauth_required": True, "error": "OAuth refresh configuration is incomplete"}
            return {"ok": True, "skipped": "refresh_not_configured"}
        try:
            expires = float(expires_at) if expires_at is not None else None
        except Exception:
            expires = None
        if not force and expires is not None and expires > time.time() + 60:
            return {"ok": True, "skipped": "token_not_near_expiry"}

        with self._oauth_refresh_lock:
            refreshed = refresh_oauth_token_staged(
                server_id=str(server["id"]),
                refresh_ref=str(refresh_ref),
                token_endpoint=str(token_endpoint),
                client_id=str(client_id),
                issuer=meta.get("oauth_issuer"),
                resource=meta.get("oauth_resource")
                or canonical_mcp_resource_uri(str(server.get("endpoint_url") or "")),
                allow_private=_explicit_loopback_endpoint(server.get("endpoint_url")),
            )
            if not refreshed.get("ok"):
                if refreshed.get("reauth_required") or force:
                    self.store.update_server_status(
                        server["id"],
                        auth_status="required",
                        connection_status="auth_required",
                        last_error=str(refreshed.get("error") or "OAuth refresh failed"),
                        last_error_kind="auth",
                    )
                return refreshed

            current = self.store.get_server(server["id"]) or server
            old_access = current.get("auth_secret_ref")
            current["auth_secret_ref"] = refreshed["auth_secret_ref"]
            current["auth_status"] = "ok"
            next_meta = dict(current.get("metadata") or meta)
            next_meta["oauth_refresh_ref"] = refreshed.get("refresh_secret_ref") or refresh_ref
            if refreshed.get("expires_at") is not None:
                next_meta["oauth_expires_at"] = refreshed["expires_at"]
            current["metadata"] = next_meta
            current_env = current.get("env") or {}
            current["env"] = {
                "plain": current_env.get("plain") or {},
                "secret_refs": current_env.get("secret_refs") or {},
            }
            try:
                self.store.upsert_server(current)
            except Exception as exc:
                try:
                    self._discard_unbound_oauth_refs(refreshed.get("new_secret_refs") or [])
                except Exception as rollback_exc:
                    raise SecretStorageUnavailable(
                        f"OAuth refresh DB-binding faalde en token rollback was incompleet: {rollback_exc}"
                    ) from exc
                raise

            cleanup_refs = list(refreshed.get("cleanup_refs") or [])
            if old_access and old_access != refreshed["auth_secret_ref"]:
                cleanup_refs.append(str(old_access))
            self._cleanup_oauth_refs_after_commit(str(server["id"]), cleanup_refs)
            return refreshed

    def _discard_oauth_result_secrets(self, result: dict[str, Any]) -> None:
        refs = [result.get("auth_secret_ref"), result.get("refresh_secret_ref")]
        self._discard_unbound_oauth_refs([str(ref) for ref in refs if ref])

    def complete_oauth(self, *, state: str, code: str, iss: str | None = None) -> dict[str, Any]:
        result = complete_oauth_flow(state=state, code=code, iss=iss)
        if not result.get("ok"):
            return result
        server_id = str(result["server_id"])
        server = self.store.get_server(server_id)
        if not server:
            self._discard_oauth_result_secrets(result)
            return {
                "ok": False,
                "error": "OAuth server verdwenen vóór token-binding",
                "ui_return_url": result.get("ui_return_url"),
            }
        pending_endpoint = str(result.get("endpoint_url") or "").strip()
        if pending_endpoint and str(server.get("endpoint_url") or "").strip() != pending_endpoint:
            self._discard_oauth_result_secrets(result)
            return {
                "ok": False,
                "error": "OAuth state is bound to a different MCP endpoint",
                "ui_return_url": result.get("ui_return_url"),
            }
        metadata_now = server.get("metadata") if isinstance(server.get("metadata"), dict) else {}
        if metadata_now.get(_OAUTH_CLEANUP_PENDING_KEY):
            try:
                self._retry_pending_oauth_secret_cleanup()
            except Exception:
                self._discard_oauth_result_secrets(result)
                raise
            server = self.store.get_server(server_id) or server

        old_access = server.get("auth_secret_ref")
        old_meta = dict(server.get("metadata") or {})
        old_refresh = old_meta.get("oauth_refresh_ref")
        env = server.get("env") or {}
        server["auth_secret_ref"] = result["auth_secret_ref"]
        server["auth_method"] = "oauth"
        server["auth_status"] = "ok"
        server["env"] = {"plain": env.get("plain") or {}, "secret_refs": env.get("secret_refs") or {}}
        meta = dict(old_meta)
        if result.get("refresh_secret_ref"):
            meta["oauth_refresh_ref"] = result["refresh_secret_ref"]
        else:
            meta.pop("oauth_refresh_ref", None)
        if result.get("issuer"):
            meta["oauth_issuer"] = result["issuer"]
        if result.get("client_id"):
            meta["oauth_client_id"] = result["client_id"]
        if result.get("expires_at") is not None:
            meta["oauth_expires_at"] = result["expires_at"]
        else:
            meta.pop("oauth_expires_at", None)
        if result.get("resource"):
            meta["oauth_resource"] = result["resource"]
        if result.get("token_endpoint"):
            meta["oauth_token_endpoint"] = result["token_endpoint"]
        server["metadata"] = meta

        try:
            self.store.upsert_server(server)
        except Exception as exc:
            try:
                self._discard_oauth_result_secrets(result)
            except Exception as rollback_exc:
                raise SecretStorageUnavailable(
                    f"OAuth completion DB-binding faalde en token rollback was incompleet: {rollback_exc}"
                ) from exc
            raise

        cleanup_refs: list[str] = []
        if old_access and old_access != result.get("auth_secret_ref"):
            cleanup_refs.append(str(old_access))
        if old_refresh and old_refresh != result.get("refresh_secret_ref"):
            cleanup_refs.append(str(old_refresh))
        self._cleanup_oauth_refs_after_commit(server_id, cleanup_refs)
        self.store.update_server_status(
            server_id,
            auth_status="ok",
            connection_status="configured",
            clear_error=True,
        )
        return {"ok": True, "server": self.get_server(server_id), "ui_return_url": result.get("ui_return_url")}

    def _retry_oauth_tool_call(
        self,
        *,
        server: dict[str, Any],
        remote_name: str,
        arguments: dict[str, Any],
        input_schema: dict[str, Any] | None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        """Refresh exactly once after a proven 401; never resend a rejected token unchanged."""
        server_id = str(server["id"])
        refreshed = self._maybe_refresh_oauth(server, force=True)
        if not refreshed.get("ok"):
            raise McpClientError(
                str(refreshed.get("error") or "OAuth refresh failed — reauthorization required"),
                kind="auth",
            )
        server = self.store.get_server(server_id) or server
        try:
            token = secret_store.get(server.get("auth_secret_ref"))
        except SecretStorageUnavailable as exc:
            raise McpClientError(str(exc), kind="auth") from exc
        if not token:
            self.store.update_server_status(server_id, auth_status="required", connection_status="auth_required")
            raise McpClientError("OAuth refresh failed — reauthorization required", kind="auth")
        with self._session_lock:
            old = self._sessions.get(server_id)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        client = self._build_client(server, approval_id=None, internal_rebuild=True)
        if old is not None:
            client.protocol_version = getattr(old, "protocol_version", client.protocol_version)
            client.protocol_generation = getattr(old, "protocol_generation", client.protocol_generation)
            if hasattr(client, "session_id"):
                client.session_id = getattr(old, "session_id", None)
        with self._session_lock:
            self._sessions[server_id] = client
        return client.call_tool(
            remote_name,
            arguments if isinstance(arguments, dict) else {},
            execution_id=execution_id,
            input_schema=input_schema,
        )

    def auth_status(
        self,
        server_id: str,
        *,
        discover: bool = False,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        result = super().auth_status(server_id, discover=False, approval_id=approval_id)
        if not discover:
            return result
        server = self.store.get_server(server_id)
        if not server:
            raise KeyError(server_id)
        discovery = None
        if server.get("transport") == "streamable_http" and server.get("endpoint_url"):
            settings = self._settings()
            try:
                approved = self._policy_approved(
                    server,
                    effect="mcp_oauth_discovery",
                    approval_id=approval_id,
                )
                require_network_policy(
                    settings,
                    endpoint_url=str(server["endpoint_url"]),
                    approved=approved,
                    purpose="mcp_oauth_discovery",
                )
                discovery = discover_auth(
                    str(server["endpoint_url"]),
                    allow_private=_explicit_loopback_endpoint(server.get("endpoint_url")),
                )
            except McpPolicyError as exc:
                approval = None
                if exc.approval_required:
                    approval = self._ensure_policy_approval(
                        server,
                        effect=exc.effect or "mcp_oauth_discovery",
                    )
                discovery = {
                    "ok": False,
                    "error": str(exc),
                    "policy_blocked": True,
                    "approval_required": bool(exc.approval_required),
                    "approval": approval,
                }
        return {**result, "oauth_discovery": discovery, "discovery_performed": True}

    def start_oauth(
        self,
        server_id: str,
        *,
        redirect_uri: str,
        ui_return_url: str | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        server = self.store.get_server(server_id)
        if not server:
            raise KeyError(server_id)
        if server.get("transport") != "streamable_http":
            raise ValueError("OAuth is alleen voor Streamable HTTP-servers")
        meta = server.get("metadata") if isinstance(server.get("metadata"), dict) else {}
        client_id = str(meta.get("oauth_client_id") or "").strip() or None
        client_metadata_url = str(meta.get("oauth_client_metadata_url") or "").strip() or None
        if not self._policy_approved(server, effect="mcp_oauth_start", approval_id=approval_id):
            settings = self._settings()
            try:
                require_network_policy(
                    settings,
                    endpoint_url=str(server.get("endpoint_url") or ""),
                    approved=False,
                    purpose="mcp_oauth_start",
                )
            except McpPolicyError as exc:
                if exc.approval_required:
                    approval = self._ensure_policy_approval(server, effect="mcp_oauth_start")
                    raise McpPolicyError(
                        str(exc),
                        kind=exc.kind,
                        approval_required=True,
                        approval=approval,
                        effect="mcp_oauth_start",
                    ) from exc
                raise
        result = start_oauth_flow(
            server_id=server_id,
            endpoint_url=str(server.get("endpoint_url") or ""),
            redirect_uri=redirect_uri,
            client_id=client_id,
            client_metadata_url=client_metadata_url,
            allow_private=_explicit_loopback_endpoint(server.get("endpoint_url")),
            settings=self._settings(),
            ui_return_url=ui_return_url,
        )
        if result.get("ok"):
            self.store.update_server_status(
                server_id,
                auth_status="required",
                connection_status="auth_required",
            )
        return result

    # --- Truthful runtime status ---------------------------------------

    def refresh_tools(self, server_id: str) -> dict[str, Any]:
        result = super().refresh_tools(server_id)
        server = self.store.get_server(server_id)
        if not server or server.get("owner_kind") == "plugin":
            return result
        with self._session_lock:
            client = self._sessions.get(server_id)
        generation = getattr(client, "protocol_generation", None) or protocol_generation(
            server.get("protocol_version")
        )
        status = connection_status_for_generation(generation, verified=True)
        self.store.update_server_status(server_id, connection_status=status)
        self._mirror_to_plugin(server_id)
        return result

    def _connect_plugin_owned(self, server: dict[str, Any]) -> dict[str, Any]:
        result = super()._connect_plugin_owned(server)
        expansion = result.get("expansion") if isinstance(result.get("expansion"), dict) else {}
        if expansion.get("ok") is False and not expansion.get("skipped"):
            error = str(expansion.get("error") or "MCP expansion failed")
            self.store.update_server_status(
                server["id"],
                connection_status="error",
                last_error=error,
                last_error_kind="transport",
                touch_check=True,
                discovery_complete=False,
            )
            result = {
                **result,
                "ok": False,
                "server": self.get_server(server["id"]),
            }
        return result

    def on_startup(self) -> dict[str, Any]:
        reset_ready: list[str] = []
        for server in self.store.list_servers():
            if server.get("owner_kind") == "plugin":
                continue
            if server.get("connection_status") == "ready":
                self.store.update_server_status(
                    server["id"],
                    connection_status="disconnected" if server.get("enabled") else "disabled",
                )
                reset_ready.append(str(server["id"]))
        result = super().on_startup()
        notes = list(result.get("notes") or [])
        notes.extend(f"reset_status:{server_id}" for server_id in reset_ready)
        return {**result, "notes": notes}


__all__ = [
    "McpManager",
    "get_mcp_manager",
    "set_mcp_manager",
    "is_mcp_tool_metadata",
]
