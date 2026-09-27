"""Trading Center frontend action × capability matrix (backend-authored)."""

from __future__ import annotations

from typing import Any


# Explicit action matrix — consumed by API/frontend; live money always BLOCKED.
TRADING_ACTION_MATRIX: list[dict[str, Any]] = [
    {
        "action": "historical_simulate",
        "requires": "HISTORICAL_SIM_AVAILABLE=AVAILABLE for instrument family",
        "blocked_when": ["UNSUPPORTED", "NOT_IMPLEMENTED", "FEATURE_GATED"],
        "live_money": "BLOCKED",
    },
    {
        "action": "paper_order",
        "requires": "LIVE_PAPER_AVAILABLE=AVAILABLE",
        "blocked_when": ["NOT_IMPLEMENTED", "UNAVAILABLE", "kill_switch"],
        "live_money": "BLOCKED",
    },
    {
        "action": "shadow_observe",
        "requires": "paper/shadow session + realtime feed lineage",
        "blocked_when": ["DEGRADED_GAP without policy", "provider_degraded"],
        "live_money": "BLOCKED",
    },
    {
        "action": "learning_train",
        "requires": "split binding TRAIN + objective version",
        "blocked_when": ["SEALED contamination", "missing split manifest"],
        "live_money": "BLOCKED",
    },
    {
        "action": "sealed_qualify",
        "requires": "SealedAttemptBinder + unused holdout lineage",
        "blocked_when": ["second_attempt", "adapted_strategy_same_holdout"],
        "live_money": "BLOCKED",
    },
    {
        "action": "live_broker_order",
        "requires": "IMPOSSIBLE — LiveTradingGuard",
        "blocked_when": ["always"],
        "live_money": "BLOCKED",
    },
    {
        "action": "l2_book_execute",
        "requires": "BOOK_L2 SUPPORTED with real depth",
        "blocked_when": ["OHLCV-only", "synthetic_l2"],
        "live_money": "BLOCKED",
    },
]


def trading_action_matrix() -> dict[str, Any]:
    return {
        "actions": list(TRADING_ACTION_MATRIX),
        "truth": {
            "backend_authored": True,
            "frontend_must_not_infer": True,
            "live_money_always_blocked": True,
        },
    }
