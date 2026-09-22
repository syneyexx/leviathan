"""Recursive structured redaction for observability payloads."""

from __future__ import annotations

from typing import Any

from Data.modules.common.secrets import looks_like_secret, redact_secrets

# Keys whose values are always treated as secrets (case-insensitive match on leaf key).
_SECRET_KEYS = frozenset(
    {
        "authorization",
        "auth",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "password",
        "passwd",
        "cookie",
        "set-cookie",
        "session",
        "session_token",
        "private_key",
        "privatekey",
        "client_secret",
        "connection_string",
        "dsn",
        "credentials",
        "hf_token",
        "openai_api_key",
        "bearer",
    }
)

_MAX_DEPTH = 12
_MAX_LIST = 200
_MAX_DICT_KEYS = 200
_MAX_STRING = 8_000


def _key_is_secret(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    if normalized in _SECRET_KEYS:
        return True
    return any(part in _SECRET_KEYS for part in normalized.split("_") if part)


def redact_value(value: Any, *, depth: int = 0, key: str | None = None) -> Any:
    """Recursively redact secrets from structured payloads.

    - Secret-named keys → ``[REDACTED]``
    - Strings matching known secret patterns → redacted in-place
    - Depth/size bounded to avoid unbounded memory from hostile payloads
    """
    if depth > _MAX_DEPTH:
        return "[TRUNCATED_DEPTH]"

    if key is not None and _key_is_secret(key):
        return "[REDACTED]"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        text = value if len(value) <= _MAX_STRING else value[:_MAX_STRING] + "…[TRUNCATED]"
        if looks_like_secret(text) or (key is not None and _key_is_secret(key)):
            return redact_secrets(text)
        redacted = redact_secrets(text)
        return redacted

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_DICT_KEYS:
                out["__truncated__"] = True
                break
            sk = str(k)
            out[sk] = redact_value(v, depth=depth + 1, key=sk)
        return out

    if isinstance(value, (list, tuple)):
        items = list(value[:_MAX_LIST])
        result = [redact_value(item, depth=depth + 1, key=key) for item in items]
        if len(value) > _MAX_LIST:
            result.append("[TRUNCATED_LIST]")
        return result

    # Fallback: stringify unknown objects safely
    try:
        text = str(value)
    except Exception:
        return "[UNREPRESENTABLE]"
    return redact_value(text, depth=depth + 1, key=key)


def redact_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    redacted = redact_value(payload)
    return redacted if isinstance(redacted, dict) else {"value": redacted}
