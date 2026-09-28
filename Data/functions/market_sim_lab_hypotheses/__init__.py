from __future__ import annotations

from typing import Any


def run(
    lab_id: str | None = None,
    *,
    limit: int = 50,
    arguments: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from Data.modules.market_sim.chat_capabilities import handle_lab_hypotheses

    payload = dict(arguments or {})
    for key, value in kwargs.items():
        if key not in payload:
            payload[key] = value
    lid = lab_id if lab_id is not None else payload.get("lab_id")
    lim = int(payload.get("limit") if payload.get("limit") is not None else limit)
    return handle_lab_hypotheses(lab_id=str(lid or ""), limit=lim)
