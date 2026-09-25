"""Python code strategies — FEATURE_GATED / NOT_AVAILABLE (P2C).

Master Program §20: AST filtering alone is insufficient. Existing isolation
architecture is the security boundary. Until an escape suite proves safe
execution under IsolationSandbox, Python strategies remain unavailable and
DSL v2 remains the supported path.
"""

from __future__ import annotations

from typing import Any

from .types import MarketSimError

PYTHON_STRATEGY_STATUS = "FEATURE_GATED"
PYTHON_STRATEGY_AVAILABILITY = "NOT_AVAILABLE"
PYTHON_STRATEGY_REASON = (
    "Python strategy execution requires a proven IsolationSandbox escape suite; "
    "AST filtering alone is insufficient. Use Strategy Spec DSL v2."
)


def python_strategy_capability() -> dict[str, Any]:
    return {
        "status": PYTHON_STRATEGY_STATUS,
        "availability": PYTHON_STRATEGY_AVAILABILITY,
        "reason": PYTHON_STRATEGY_REASON,
        "dsl_available": True,
        "truth": {
            "ast_filtering_insufficient": True,
            "isolation_required": True,
            "not_claimed_available": True,
        },
    }


def evaluate_python_strategy(*_args: Any, **_kwargs: Any) -> None:
    """Refuse Python strategy execution until sandbox escape suite PASSes."""
    raise MarketSimError(
        "PYTHON_STRATEGY_NOT_AVAILABLE",
        PYTHON_STRATEGY_REASON,
        http_status=503,
    )


def assert_not_python_strategy(entry_rules: dict[str, Any] | None) -> None:
    kind = str((entry_rules or {}).get("kind") or "").lower()
    lang = str((entry_rules or {}).get("language") or "").lower()
    if kind in {"python", "code", "py"} or lang in {"python", "py"}:
        evaluate_python_strategy()
