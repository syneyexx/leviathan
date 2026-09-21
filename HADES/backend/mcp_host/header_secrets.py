"""Secure handling for sensitive custom MCP HTTP headers.

Header values whose names look credential-bearing never belong in SQLite.
They are stored in the OS-backed MCP secret store and represented in persisted
server config only by a masked value plus an opaque secret ref.

SQLite and an OS keyring cannot share one ACID transaction. Updates therefore
use a small two-phase protocol: write new secrets under new refs first, commit
the SQLite row, and only then delete superseded refs. A failed SQLite write can
roll back every newly-created ref without invalidating the still-committed row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mcp_host.secrets import SecretStorageUnavailable, secret_store

HEADER_SECRET_PREFIX = "__mcp_http_header__:"
HEADER_CLEANUP_PENDING_KEY = "header_secret_cleanup_pending"
HEADER_CLEANUP_FAILURES_KEY = "header_secret_cleanup_failures"
_SECRET_TOKENS = (
    "authorization",
    "token",
    "secret",
    "password",
    "credential",
    "bearer",
    "api-key",
    "api_key",
    "apikey",
)


def _normalized_header_name(name: str) -> str:
    return str(name or "").strip().lower()


def is_sensitive_header_name(name: str) -> bool:
    lower = _normalized_header_name(name)
    compact = re.sub(r"[-_\s]+", "", lower)
    return any(token in lower for token in _SECRET_TOKENS) or any(
        token.replace("-", "").replace("_", "") in compact for token in _SECRET_TOKENS
    )


def header_secret_key(name: str) -> str:
    return HEADER_SECRET_PREFIX + _normalized_header_name(name)


def _validate_header(name: str, value: str) -> tuple[str, str]:
    key = str(name or "").strip()
    val = str(value or "")
    if not key:
        raise ValueError("HTTP header name may not be empty")
    if "\r" in key or "\n" in key or ":" in key:
        raise ValueError(f"Invalid HTTP header name: {key!r}")
    if "\r" in val or "\n" in val:
        raise ValueError(f"HTTP header value contains a newline: {key}")
    return key, val


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


@dataclass
class HeaderSecretStage:
    """Keyring side of a two-phase HTTP-header secret update."""

    new_refs: list[str] = field(default_factory=list)
    cleanup_after_commit: list[str] = field(default_factory=list)
    finished: bool = False

    def rollback(self) -> None:
        """Delete only newly-created refs; old DB-referenced refs remain intact."""
        if self.finished:
            return
        failures: list[str] = []
        for ref in reversed(_unique(self.new_refs)):
            result = secret_store.delete(ref, missing_ok=True)
            if not result.get("ok"):
                failures.append(f"{ref}:{result.get('error') or result.get('error_type') or 'delete_failed'}")
        self.finished = True
        if failures:
            raise SecretStorageUnavailable(
                "Header-secret rollback kon nieuwe keyring refs niet volledig opruimen: " + "; ".join(failures)
            )

    def commit(self) -> list[dict[str, str]]:
        """Delete superseded refs after SQLite committed; return durable-cleanup failures."""
        if self.finished:
            return []
        failures: list[dict[str, str]] = []
        for ref in _unique(self.cleanup_after_commit):
            result = secret_store.delete(ref, missing_ok=True)
            if not result.get("ok"):
                failures.append(
                    {
                        "ref": ref,
                        "error": str(result.get("error") or result.get("error_type") or "delete_failed"),
                    }
                )
        self.finished = True
        return failures


def stage_sensitive_headers(
    *,
    server_id: str,
    headers: dict[str, Any],
    existing_secret_refs: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str], HeaderSecretStage]:
    """Prepare masked headers and new refs without deleting any committed secret.

    New/changed credential values always receive a fresh ref. This is important:
    overwriting the old ref before SQLite commits would silently change the
    effective credential even if the database update later rolled back.
    """
    refs = {str(k): str(v) for k, v in (existing_secret_refs or {}).items() if k and v}
    clean: dict[str, str] = {}
    present_secret_keys: set[str] = set()
    stage = HeaderSecretStage()

    try:
        for raw_name, raw_value in headers.items():
            name, value = _validate_header(str(raw_name), str(raw_value))
            if not is_sensitive_header_name(name):
                clean[name] = value
                continue
            ref_key = header_secret_key(name)
            present_secret_keys.add(ref_key)
            existing_ref = refs.get(ref_key)
            if value in {"", "***"}:
                if existing_ref:
                    clean[name] = "***"
                continue

            new_ref = secret_store.new_ref(server_id, f"header_{_normalized_header_name(name)}")
            secret_store.store(new_ref, value)
            stage.new_refs.append(new_ref)
            refs[ref_key] = new_ref
            if existing_ref and existing_ref != new_ref:
                stage.cleanup_after_commit.append(existing_ref)
            clean[name] = "***"

        for ref_key in list(refs):
            if not ref_key.startswith(HEADER_SECRET_PREFIX) or ref_key in present_secret_keys:
                continue
            old_ref = refs.pop(ref_key, None)
            if old_ref:
                stage.cleanup_after_commit.append(str(old_ref))
        return clean, refs, stage
    except Exception as exc:
        try:
            stage.rollback()
        except Exception as rollback_exc:
            raise SecretStorageUnavailable(
                f"Header-secret staging mislukt en rollback was incompleet: {rollback_exc}"
            ) from exc
        raise


def normalize_sensitive_headers(
    *,
    server_id: str,
    headers: dict[str, Any],
    existing_secret_refs: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Immediate helper for callers without a separate SQLite commit phase."""
    clean, refs, stage = stage_sensitive_headers(
        server_id=server_id,
        headers=headers,
        existing_secret_refs=existing_secret_refs,
    )
    failures = stage.commit()
    if failures:
        raise SecretStorageUnavailable(f"HTTP-header-secret cleanup mislukt: {failures}")
    return clean, refs


def resolve_sensitive_headers(
    headers: dict[str, Any] | None,
    secret_refs: dict[str, str] | None,
) -> dict[str, str]:
    """Resolve masked custom header values immediately before an HTTP request."""
    resolved: dict[str, str] = {}
    original_case: dict[str, str] = {}
    for raw_name, raw_value in (headers or {}).items():
        name, value = _validate_header(str(raw_name), str(raw_value))
        original_case[_normalized_header_name(name)] = name
        if value != "***":
            resolved[name] = value
    for ref_key, ref in (secret_refs or {}).items():
        if not str(ref_key).startswith(HEADER_SECRET_PREFIX):
            continue
        normalized_name = str(ref_key)[len(HEADER_SECRET_PREFIX) :]
        name = original_case.get(normalized_name, normalized_name)
        value = secret_store.get(str(ref))
        if not value:
            raise SecretStorageUnavailable(f"Secret ontbreekt voor MCP HTTP header {name}")
        resolved[name] = value
    return resolved


def _persist_cleanup_failures(store: Any, server_id: str, failures: list[dict[str, str]]) -> None:
    server = store.get_server(server_id)
    if not server:
        raise SecretStorageUnavailable(
            "Header-secret cleanup faalde nadat de serverrij verdween; cleanup refs konden niet duurzaam worden gekoppeld"
        )
    metadata = dict(server.get("metadata") or {})
    if failures:
        metadata[HEADER_CLEANUP_PENDING_KEY] = [item["ref"] for item in failures]
        metadata[HEADER_CLEANUP_FAILURES_KEY] = failures
    else:
        metadata.pop(HEADER_CLEANUP_PENDING_KEY, None)
        metadata.pop(HEADER_CLEANUP_FAILURES_KEY, None)
    server["metadata"] = metadata
    env = server.get("env") if isinstance(server.get("env"), dict) else {}
    server["env"] = {"plain": env.get("plain") or {}, "secret_refs": env.get("secret_refs") or {}}
    store.upsert_server(server)


# Public name used by manager CRUD after the SQLite commit boundary.
persist_header_cleanup_failures = _persist_cleanup_failures


def retry_pending_header_secret_cleanup(store: Any) -> dict[str, Any]:
    """Retry durable old-secret cleanup from prior post-commit keyring failures."""
    attempted = 0
    remaining_total = 0
    for server in store.list_servers():
        metadata = dict(server.get("metadata") or {})
        pending = [str(ref) for ref in (metadata.get(HEADER_CLEANUP_PENDING_KEY) or []) if ref]
        if not pending:
            continue
        attempted += len(pending)
        remaining: list[dict[str, str]] = []
        for ref in _unique(pending):
            result = secret_store.delete(ref, missing_ok=True)
            if not result.get("ok"):
                remaining.append(
                    {
                        "ref": ref,
                        "error": str(result.get("error") or result.get("error_type") or "delete_failed"),
                    }
                )
        _persist_cleanup_failures(store, str(server["id"]), remaining)
        remaining_total += len(remaining)
    if remaining_total:
        raise SecretStorageUnavailable(
            f"{remaining_total} oude MCP HTTP-header-secret(s) konden niet veilig worden opgeruimd"
        )
    return {"ok": True, "attempted": attempted, "remaining": 0}


def migrate_plaintext_sensitive_headers(store: Any) -> dict[str, Any]:
    """Move legacy sensitive header values out of SQLite with staged keyring writes."""
    migrated_servers = 0
    migrated_headers = 0
    for server in store.list_servers():
        if server.get("transport") != "streamable_http":
            continue
        headers = dict(server.get("headers") or {})
        sensitive_plain = {
            str(k): str(v)
            for k, v in headers.items()
            if is_sensitive_header_name(str(k)) and str(v) not in {"", "***"}
        }
        if not sensitive_plain:
            continue
        env = server.get("env") if isinstance(server.get("env"), dict) else {}
        refs = dict(env.get("secret_refs") or {})
        clean, refs, stage = stage_sensitive_headers(
            server_id=str(server["id"]),
            headers=headers,
            existing_secret_refs=refs,
        )
        patch = dict(server)
        patch["headers"] = clean
        patch["env"] = {"plain": env.get("plain") or {}, "secret_refs": refs}
        try:
            store.upsert_server(patch)
        except Exception as exc:
            try:
                stage.rollback()
            except Exception as rollback_exc:
                raise SecretStorageUnavailable(
                    f"Legacy header migration DB-write faalde en keyring rollback was incompleet: {rollback_exc}"
                ) from exc
            raise
        failures = stage.commit()
        if failures:
            _persist_cleanup_failures(store, str(server["id"]), failures)
        migrated_servers += 1
        migrated_headers += len(sensitive_plain)
    return {"ok": True, "servers": migrated_servers, "headers": migrated_headers}
