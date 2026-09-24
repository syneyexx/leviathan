"""Live trading guard — real broker orders remain blocked by default."""

from __future__ import annotations

import os
from typing import Any

from .types import MarketSimError


class LiveTradingGuard:
    """Agents/prompts cannot enable live mode or raise limits."""

    def public_status(self) -> dict[str, Any]:
        unlock = os.environ.get("LEVIATHAN_LIVE_TRADING_UNLOCK", "").strip().lower() in {
            "1", "true", "yes"
        }
        adapter = os.environ.get("LEVIATHAN_LIVE_BROKER_ADAPTER", "").strip()
        return {
            "LIVE_TRADING_AVAILABLE": "BLOCKED",
            "unlock_env_set": unlock,
            "adapter_configured": bool(adapter),
            "human_authorization_required": True,
            "agent_cannot_enable": True,
            "credentials_separated": True,
            "detail": (
                "Live broker orders are intentionally blocked. "
                "Paper trading and historical simulation remain available. "
                "Enabling live trading requires a verified adapter, separated credentials, "
                "explicit human authorization, deterministic risk checks, order preview, "
                "kill switch, and idempotent client order ids — not present in this build."
            ),
        }

    def place_live_order(self, **_: Any) -> None:
        raise MarketSimError(
            "LIVE_TRADING_BLOCKED",
            "Real broker orders are blocked. Use historical simulation or live paper trading.",
            http_status=501,
        )
