from __future__ import annotations

from typing import Any


def run(
    deployment_id: str | None = None,
    portfolio_id: str | None = None,
    *,
    limit: int = 20,
    arguments: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from Data.modules.market_sim.chat_capabilities import handle_paper_drift

    payload = dict(arguments or {})
    for key, value in kwargs.items():
        if key not in payload:
            payload[key] = value
    return handle_paper_drift(
        deployment_id=payload.get("deployment_id") if deployment_id is None else deployment_id,
        portfolio_id=payload.get("portfolio_id") if portfolio_id is None else portfolio_id,
        limit=int(payload.get("limit") if payload.get("limit") is not None else limit),
    )
