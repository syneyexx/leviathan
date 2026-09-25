from __future__ import annotations

from typing import Any


def run(
    url: str | None = None,
    *,
    timeout_seconds: float = 20.0,
    max_bytes: int = 2_000_000,
    arguments: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """GI7 — web.fetch via bound WebResearchProvider (direct URL; no fabrication)."""
    from Data.modules.research.web_capabilities import execute_web_fetch

    payload = dict(arguments or {})
    for key, value in kwargs.items():
        if key not in payload:
            payload[key] = value
    target = url if url is not None else payload.get("url")
    timeout = float(
        payload.get("timeout_seconds")
        if payload.get("timeout_seconds") is not None
        else timeout_seconds
    )
    nbytes = int(
        payload.get("max_bytes") if payload.get("max_bytes") is not None else max_bytes
    )
    return execute_web_fetch(
        str(target or ""),
        timeout_seconds=timeout,
        max_bytes=nbytes,
    )
