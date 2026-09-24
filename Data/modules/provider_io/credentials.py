"""Resolve provider credentials in-worker — never from durable job payloads."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResolvedCredential:
    credential_ref: str
    api_key: str | None = None
    headers: dict[str, str] | None = None
    extra: dict[str, Any] | None = None


_ENV_MAP: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY", "LEVIATHAN_LLM_API_KEY", "LEVIATHAN_OPENAI_API_KEY"),
    "llm": ("LEVIATHAN_LLM_API_KEY", "OPENAI_API_KEY"),
    "web_search": ("LEVIATHAN_WEB_SEARCH_API_KEY", "WEB_SEARCH_API_KEY"),
    "huggingface": ("HF_TOKEN", "HUGGINGFACE_HUB_TOKEN", "LEVIATHAN_HF_TOKEN"),
    "alpaca": ("ALPACA_API_KEY", "ALPACA_API_KEY_ID"),
    "alpaca_secret": ("ALPACA_API_SECRET", "ALPACA_SECRET_KEY"),
}


def _ephemeral_dir() -> Path:
    raw = (os.environ.get("LEVIATHAN_PROVIDER_CREDENTIAL_DIR") or "").strip()
    if raw:
        root = Path(raw)
    else:
        try:
            from Data.backend.config import load_settings

            root = Path(load_settings().database_path).resolve().parent / "provider_credentials"
        except Exception:  # noqa: BLE001
            root = Path("Data/state/provider_credentials")
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_ephemeral_token(token: str, *, prefix: str = "tok") -> str:
    """Persist a short-lived token as a file reference (not in job JSON)."""
    name = f"{prefix}-{uuid.uuid4().hex}.cred"
    path = _ephemeral_dir() / name
    path.write_text(token, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return f"ephemeral:{name}"


def _read_ephemeral(ref: str) -> str | None:
    if not ref.startswith("ephemeral:"):
        return None
    name = ref.split(":", 1)[1]
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    path = _ephemeral_dir() / name
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def resolve_credential(credential_ref: str | None) -> ResolvedCredential:
    """Resolve a logical credential reference from process environment / settings.

    Job payloads must carry ``credential_ref`` only — never raw secrets.
    """
    ref = (credential_ref or "").strip() or "default"
    if ref == "none" or ref == "anonymous":
        return ResolvedCredential(credential_ref=ref)

    if ref.startswith("ephemeral:"):
        return ResolvedCredential(credential_ref=ref, api_key=_read_ephemeral(ref))

    # Allow explicit settings-backed LLM key without inventing a second secret store.
    if ref in {"llm", "openai", "default"}:
        try:
            from Data.backend.config import load_settings

            settings = load_settings()
            key = (getattr(settings, "llm_api_key", None) or "").strip() or None
            if key:
                return ResolvedCredential(credential_ref=ref, api_key=key)
        except Exception:  # noqa: BLE001
            pass

    env_keys = _ENV_MAP.get(ref, ())
    for env_name in env_keys:
        val = (os.environ.get(env_name) or "").strip()
        if val:
            return ResolvedCredential(credential_ref=ref, api_key=val)

    # Generic: LEVIATHAN_PROVIDER_<REF>_API_KEY
    generic = (os.environ.get(f"LEVIATHAN_PROVIDER_{ref.upper()}_API_KEY") or "").strip()
    if generic:
        return ResolvedCredential(credential_ref=ref, api_key=generic)

    return ResolvedCredential(credential_ref=ref, api_key=None)


def assert_no_secrets_in_payload(payload: dict[str, Any]) -> None:
    """Reject job arguments that embed raw API keys."""
    banned = {
        "api_key",
        "apiKey",
        "authorization",
        "Authorization",
        "token",
        "access_token",
        "secret",
        "password",
        "hf_token",
        "hfToken",
    }
    for key in payload:
        if key in banned or key.lower().endswith("_api_key") or key.lower().endswith("apikey"):
            raise ValueError(
                f"Provider job payload must not contain secret field {key!r}; "
                "use credential_ref instead"
            )
        val = payload.get(key)
        if isinstance(val, str) and val.startswith(("sk-", "hf_", "Bearer ")):
            raise ValueError(
                f"Provider job payload field {key!r} looks like a raw secret"
            )
