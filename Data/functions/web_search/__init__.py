from __future__ import annotations

from typing import Any


def run(
    query: str | None = None,
    *,
    limit: int = 5,
    arguments: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """GI7 — web.search via bound WebResearchProvider (never fabricates results)."""
    from Data.modules.research.web_capabilities import execute_web_search

    payload = dict(arguments or {})
    for key, value in kwargs.items():
        if key not in payload:
            payload[key] = value
    q = query if query is not None else payload.get("query")
    lim = int(payload.get("limit") if payload.get("limit") is not None else limit)
    return execute_web_search(str(q or ""), limit=lim)
