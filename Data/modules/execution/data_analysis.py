"""Deterministic data analysis helpers (W22) — prefer calc over hallucinated arithmetic.

Unsafe raw eval is refused. Long analysis belongs on external workers.
"""

from __future__ import annotations

import ast
import csv
import io
import math
from dataclasses import dataclass
from typing import Any


ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv)
ALLOWED_UNARY = (ast.UAdd, ast.USub)


def safe_calculate(expression: str) -> dict[str, Any]:
    """Evaluate a numeric expression via AST — no names, attrs, or calls."""
    src = (expression or "").strip()
    if not src:
        return {"ok": False, "error": "empty", "status": "REJECTED"}
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as exc:
        return {"ok": False, "error": str(exc), "status": "REJECTED"}

    def _check(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            _check(node.body)
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return
        if isinstance(node, ast.BinOp) and isinstance(node.op, ALLOWED_BINOPS):
            _check(node.left)
            _check(node.right)
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ALLOWED_UNARY):
            _check(node.operand)
            return
        raise ValueError(f"disallowed node {type(node).__name__}")

    try:
        _check(tree)
        value = eval(compile(tree, "<safe_calculate>", "eval"), {"__builtins__": {}}, {})  # noqa: S307
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "status": "REJECTED", "truth": {"no_raw_eval": True}}
    return {
        "ok": True,
        "value": float(value) if isinstance(value, (int, float)) else value,
        "status": "MEASURED",
        "truth": {"deterministic_calculation": True, "no_raw_eval": True},
    }


def summarize_csv(text: str, *, max_rows: int = 100) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for i, row in enumerate(reader):
        if i >= max_rows:
            break
        rows.append(dict(row))
    cols = list(reader.fieldnames or [])
    return {
        "columns": cols,
        "row_count": len(rows),
        "preview": rows[:10],
        "status": "MEASURED" if cols else "UNMEASURED",
        "truth": {"tabular_only": True, "no_unsafe_eval": True},
    }


@dataclass
class AutomationBinding:
    """Schedules/events reuse JobRuntime — no AutomationRuntime2."""

    schedule_id: str | None = None
    job_kind: str = ""
    status: str = "FEATURE_GATED"

    def public_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "job_kind": self.job_kind,
            "status": self.status,
            "truth": {
                "no_automation_runtime_v2": True,
                "uses_job_runtime_schedules": True,
            },
        }


def mcp_trust_policy() -> dict[str, Any]:
    return {
        "content_trust": "external_untrusted_data",
        "tool_description_is_metadata_not_system_authority": True,
        "requires_execution_gateway": True,
        "truth": {"mcp_is_not_private_side_effect_channel": True},
    }


# silence unused math import if any
_ = math
