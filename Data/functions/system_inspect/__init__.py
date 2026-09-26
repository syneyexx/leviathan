from __future__ import annotations

from typing import Any


def run(
    scope: str | None = None,
    *,
    arguments: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """GI2 — honest system self-inspection via SystemInspectService."""
    from Data.modules.cognition.system_inspect import get_system_inspect_service

    payload = dict(arguments or {})
    for key, value in kwargs.items():
        if key not in payload:
            payload[key] = value
    resolved_scope = scope if scope is not None else payload.get("scope")
    return get_system_inspect_service().inspect(scope=resolved_scope)
