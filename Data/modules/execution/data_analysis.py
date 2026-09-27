"""Deterministic data analysis helpers (W22) — prefer calc over hallucinated arithmetic.

Unsafe raw eval is refused. Long analysis belongs on external workers.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any


def safe_calculate(expression: str) -> dict[str, Any]:
    """Evaluate a numeric expression via the canonical NumericComputeEngine.

    Compatibility alias — do not maintain a weaker second AST evaluator here.
    """
    from Data.modules.compute.numeric import NumericComputeEngine

    src = (expression or "").strip()
    if not src:
        return {"ok": False, "error": "empty", "status": "REJECTED"}
    try:
        result = NumericComputeEngine().evaluate_expression(src)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "status": "REJECTED",
            "truth": {"no_raw_eval": True, "delegates_to": "NumericComputeEngine"},
        }
    value = result.value
    return {
        "ok": True,
        "value": float(value) if isinstance(value, (int, float)) else value,
        "status": "MEASURED",
        "truth": {
            "deterministic_calculation": True,
            "no_raw_eval": True,
            "delegates_to": "NumericComputeEngine",
        },
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
