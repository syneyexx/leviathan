from __future__ import annotations

from typing import Any


def run(
    lab_id: str | None = None,
    *,
    arguments: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from Data.modules.market_sim.chat_capabilities import handle_lab_best_candidate

    payload = dict(arguments or {})
    for key, value in kwargs.items():
        if key not in payload:
            payload[key] = value
    lid = lab_id if lab_id is not None else payload.get("lab_id")
    return handle_lab_best_candidate(lab_id=str(lid or ""))
