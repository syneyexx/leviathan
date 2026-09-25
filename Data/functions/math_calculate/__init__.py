from __future__ import annotations

from typing import Any


def run(*, expression: str = "", **kwargs: Any) -> dict[str, Any]:
    """Safe AST calculator — no eval(user_string)."""
    from Data.modules.compute.numeric import NumericComputeEngine

    expr = str(expression or kwargs.get("expr") or kwargs.get("formula") or "").strip()
    return NumericComputeEngine().evaluate_expression(expr).public_dict()
