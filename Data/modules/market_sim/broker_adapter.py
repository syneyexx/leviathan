"""Broker adapter boundary — paper only; live broker UNSUPPORTED (P4B / G35)."""

from __future__ import annotations

from typing import Any, Protocol

from .types import MarketSimError


class BrokerAdapter(Protocol):
    broker_id: str

    def place(self, **kwargs: Any) -> Any: ...

    def account(self, **kwargs: Any) -> dict[str, Any]: ...


class LiveBrokerAdapter:
    """Explicitly unsupported — A5 / live money never available."""

    broker_id = "live_broker"

    def place(self, **_: Any) -> None:
        raise MarketSimError(
            "LIVE_BROKER_UNSUPPORTED",
            "Live broker adapter is UNSUPPORTED. Use local_paper or alpaca_paper only.",
            http_status=501,
        )

    def account(self, **_: Any) -> dict[str, Any]:
        raise MarketSimError(
            "LIVE_BROKER_UNSUPPORTED",
            "Live broker adapter is UNSUPPORTED",
            http_status=501,
        )

    def public_status(self) -> dict[str, Any]:
        return {
            "broker_id": self.broker_id,
            "availability": "UNSUPPORTED",
            "live_trading": "BLOCKED",
            "truth": {
                "a5_impossible": True,
                "paper_only_adapters": True,
            },
        }


def resolve_broker_adapter(broker_id: str) -> str:
    """Return normalized paper broker id or raise for live."""
    text = str(broker_id or "").strip().lower()
    if text in {"live", "live_broker", "real", "production"}:
        LiveBrokerAdapter().place()
    if text in {"local_paper", "alpaca_paper", "paper"}:
        return "local_paper" if text == "paper" else text
    raise MarketSimError(
        "UNKNOWN_BROKER",
        f"Unknown broker_id={broker_id!r}; supported: local_paper, alpaca_paper",
        http_status=400,
    )
