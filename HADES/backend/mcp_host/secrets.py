"""Secure MCP secret storage — fail closed when no OS secret backend is available.

Prefers the `keyring` package (Windows Credential Manager / macOS Keychain /
Secret Service). Never stores tokens in SQLite plaintext and never falls back
to a hardcoded or fake encryption key.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from typing import Any

SERVICE_NAME = "HADES-MCP"


class SecretStorageUnavailable(RuntimeError):
    """Raised when a secret must be stored/retrieved but no secure backend exists."""


class McpSecretStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._memory_test_override: dict[str, str] | None = None

    def _backend(self) -> Any:
        try:
            import keyring  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency missing
            raise SecretStorageUnavailable(
                "Veilige secret-opslag (keyring) is niet beschikbaar. "
                "Installeer het keyring-pakket; tokens worden niet in SQLite opgeslagen."
            ) from exc
        return keyring

    def available(self) -> dict[str, Any]:
        try:
            backend = self._backend()
            name = type(backend.get_keyring()).__name__
            # keyring's fail backend cannot persist secrets.
            if "fail" in name.lower() or "null" in name.lower():
                return {"ok": False, "backend": name, "error": "keyring backend cannot persist secrets"}
            return {"ok": True, "backend": name}
        except SecretStorageUnavailable as exc:
            return {"ok": False, "backend": None, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "backend": None, "error": str(exc)}

    @staticmethod
    def _best_effort_backend_delete(backend: Any, ref: str) -> None:
        """Compensate a possibly-partial set without masking the original failure."""
        try:
            backend.delete_password(SERVICE_NAME, ref)
        except Exception:
            pass

    def store(self, ref: str, value: str) -> str:
        if not ref or not value:
            raise ValueError("secret ref and value are required")
        with self._lock:
            if self._memory_test_override is not None:
                self._memory_test_override[ref] = value
                return ref
            backend = self._backend()
            try:
                backend.set_password(SERVICE_NAME, ref, value)
            except Exception as exc:
                # Some backends can fail after partially writing. Try to remove
                # the candidate ref before reporting failure to the caller.
                self._best_effort_backend_delete(backend, ref)
                raise SecretStorageUnavailable(f"Kon secret niet veilig opslaan: {exc}") from exc
            # Verify round-trip so we never claim storage succeeded silently.
            try:
                stored = backend.get_password(SERVICE_NAME, ref)
            except Exception as exc:
                self._best_effort_backend_delete(backend, ref)
                raise SecretStorageUnavailable(f"Secret-opslag niet verifieerbaar: {exc}") from exc
            if stored != value:
                self._best_effort_backend_delete(backend, ref)
                raise SecretStorageUnavailable("Secret-opslag verificatie mislukt (waarde komt niet overeen).")
        return ref

    def get(self, ref: str | None) -> str | None:
        if not ref:
            return None
        with self._lock:
            if self._memory_test_override is not None:
                return self._memory_test_override.get(ref)
            backend = self._backend()
            try:
                return backend.get_password(SERVICE_NAME, ref)
            except Exception as exc:
                raise SecretStorageUnavailable(f"Kon secret niet lezen: {exc}") from exc

    def delete(self, ref: str | None, *, missing_ok: bool = True) -> dict[str, Any]:
        if not ref:
            return {"ok": True, "deleted": False, "reason": "empty_ref"}
        with self._lock:
            if self._memory_test_override is not None:
                existed = ref in self._memory_test_override
                self._memory_test_override.pop(ref, None)
                return {"ok": True, "deleted": existed}
            backend = self._backend()
            try:
                backend.delete_password(SERVICE_NAME, ref)
                return {"ok": True, "deleted": True}
            except Exception as exc:
                # keyring raises PasswordDeleteError when missing on some backends.
                name = type(exc).__name__
                if missing_ok and ("PasswordDelete" in name or "not found" in str(exc).lower() or "NotFound" in name):
                    return {"ok": True, "deleted": False, "reason": "missing"}
                return {"ok": False, "deleted": False, "error": str(exc), "error_type": name}

    def new_ref(self, server_id: str, kind: str) -> str:
        digest = hashlib.sha256(f"{server_id}:{kind}:{secrets.token_hex(8)}".encode("utf-8")).hexdigest()[:24]
        return f"mcp/{server_id}/{kind}/{digest}"

    def enable_memory_backend_for_tests(self) -> None:
        """Test-only in-process store — never used in production paths."""
        self._memory_test_override = {}


secret_store = McpSecretStore()
