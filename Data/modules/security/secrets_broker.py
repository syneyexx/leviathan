"""Scoped short-lived credential broker for workers (U171 / U199).

Raw long-lived tokens must never be inserted into model prompts.
Workers receive lease handles; plaintext is resolved only at use time.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from Data.modules.mcp.secrets import resolve_secret_ref


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


@dataclass(frozen=True)
class CredentialLease:
    lease_id: str
    secret_ref: str
    scope: str
    issued_to: str
    expires_at: str
    created_at: str
    revoked: bool = False
    run_id: str | None = None
    job_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Never include plaintext in public_dict / logs.
    _token_fingerprint: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "secret_ref": self.secret_ref,
            "scope": self.scope,
            "issued_to": self.issued_to,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "revoked": self.revoked,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "token_fingerprint": self._token_fingerprint,
            "metadata": self.metadata,
            "truth": {
                "lease_is_not_plaintext": True,
                "raw_tokens_never_in_model_prompts": True,
                "credentials_not_in_transcripts": True,
            },
        }


class SecretsBroker:
    """Issues scoped, short-lived credential leases to workers."""

    def __init__(
        self,
        db_path: Path,
        *,
        overrides: Mapping[str, str] | None = None,
        default_ttl_seconds: int = 300,
    ) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.overrides = dict(overrides or {})
        self.default_ttl_seconds = max(30, int(default_ttl_seconds))
        self._plaintext: dict[str, str] = {}

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS secret_credential_leases (
                    lease_id TEXT PRIMARY KEY,
                    secret_ref TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    issued_to TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    run_id TEXT,
                    job_id TEXT,
                    token_fingerprint TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_secret_leases_expires "
                "ON secret_credential_leases(expires_at, revoked)"
            )

    def issue(
        self,
        secret_ref: str,
        *,
        scope: str,
        issued_to: str,
        ttl_seconds: int | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CredentialLease:
        """Resolve a secret ref once and mint a short-lived lease handle."""
        plaintext = resolve_secret_ref(secret_ref, overrides=self.overrides)
        ttl = max(30, int(ttl_seconds or self.default_ttl_seconds))
        now = _utc_now()
        lease_id = f"lease_{uuid.uuid4().hex[:16]}"
        # Mix a nonce so fingerprints are not stable across leases of the same secret.
        fingerprint = hashlib.sha256(
            f"{secrets.token_hex(8)}:{plaintext}".encode("utf-8")
        ).hexdigest()[:16]
        lease = CredentialLease(
            lease_id=lease_id,
            secret_ref=secret_ref,
            scope=scope,
            issued_to=issued_to,
            expires_at=_iso(now + timedelta(seconds=ttl)),
            created_at=_iso(now),
            run_id=run_id,
            job_id=job_id,
            metadata=dict(metadata or {}),
            _token_fingerprint=fingerprint,
        )
        self._plaintext[lease_id] = plaintext
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO secret_credential_leases(
                    lease_id, secret_ref, scope, issued_to, expires_at, created_at,
                    revoked, run_id, job_id, token_fingerprint, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    lease.lease_id,
                    lease.secret_ref,
                    lease.scope,
                    lease.issued_to,
                    lease.expires_at,
                    lease.created_at,
                    lease.run_id,
                    lease.job_id,
                    lease._token_fingerprint,
                    json.dumps(lease.metadata),
                ),
            )
        return lease

    def resolve_lease(self, lease_id: str, *, issued_to: str | None = None) -> str:
        """Return plaintext for an active lease. Raises if expired/revoked/mismatched."""
        lease = self.get(lease_id)
        if lease is None:
            raise KeyError(f"Unknown credential lease: {lease_id}")
        if lease.revoked:
            raise PermissionError(f"Credential lease revoked: {lease_id}")
        if issued_to is not None and lease.issued_to != issued_to:
            raise PermissionError("Credential lease issued_to mismatch")
        expires = datetime.fromisoformat(lease.expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if _utc_now() >= expires:
            raise PermissionError(f"Credential lease expired: {lease_id}")
        plaintext = self._plaintext.get(lease_id)
        if plaintext is None:
            # Process restart: re-resolve from ref (still never logged).
            plaintext = resolve_secret_ref(lease.secret_ref, overrides=self.overrides)
            self._plaintext[lease_id] = plaintext
        return plaintext

    def revoke(self, lease_id: str) -> CredentialLease | None:
        lease = self.get(lease_id)
        if lease is None:
            return None
        with self.connect() as conn:
            conn.execute(
                "UPDATE secret_credential_leases SET revoked = 1 WHERE lease_id = ?",
                (lease_id,),
            )
        self._plaintext.pop(lease_id, None)
        return self.get(lease_id)

    def get(self, lease_id: str) -> CredentialLease | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM secret_credential_leases WHERE lease_id = ?",
                (lease_id,),
            ).fetchone()
        if row is None:
            return None
        return CredentialLease(
            lease_id=row["lease_id"],
            secret_ref=row["secret_ref"],
            scope=row["scope"],
            issued_to=row["issued_to"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            revoked=bool(row["revoked"]),
            run_id=row["run_id"],
            job_id=row["job_id"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            _token_fingerprint=row["token_fingerprint"],
        )

    def redact_for_prompt(self, text: str) -> str:
        """Strip any currently leased plaintext values from model-visible text."""
        redacted = text
        for value in self._plaintext.values():
            if value and value in redacted:
                redacted = redacted.replace(value, "[REDACTED_SECRET]")
        return redacted
