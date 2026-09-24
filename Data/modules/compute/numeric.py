"""Deterministic numeric / table compute — Tier 0 offload for the main LLM."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence


@dataclass
class ComputeResult:
    operation: str
    value: Any
    unit: str | None = None
    details: dict[str, Any] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "value": self.value,
            "unit": self.unit,
            "details": self.details or {},
            "tier": 0,
            "truth": {"deterministic": True, "not_llm": True},
        }


class NumericComputeEngine:
    """Exact calculations the main reasoning model must not perform."""

    def cagr(self, start: float, end: float, periods: float) -> ComputeResult:
        if periods <= 0:
            raise ValueError("periods must be > 0")
        if start == 0:
            raise ValueError("start must be non-zero")
        ratio = float(end) / float(start)
        if ratio < 0:
            raise ValueError("CAGR undefined for negative ratio")
        value = ratio ** (1.0 / float(periods)) - 1.0
        return ComputeResult("cagr", value, details={"start": start, "end": end, "periods": periods})

    def percent_change(self, start: float, end: float) -> ComputeResult:
        if start == 0:
            raise ValueError("start must be non-zero")
        return ComputeResult("percent_change", (float(end) - float(start)) / float(start))

    def mean(self, values: Sequence[float]) -> ComputeResult:
        vals = [float(v) for v in values]
        if not vals:
            raise ValueError("values required")
        return ComputeResult("mean", statistics.fmean(vals), details={"n": len(vals)})

    def median(self, values: Sequence[float]) -> ComputeResult:
        vals = [float(v) for v in values]
        if not vals:
            raise ValueError("values required")
        return ComputeResult("median", statistics.median(vals), details={"n": len(vals)})

    def stdev(self, values: Sequence[float], *, sample: bool = True) -> ComputeResult:
        vals = [float(v) for v in values]
        if len(vals) < 2:
            raise ValueError("need at least 2 values")
        fn = statistics.stdev if sample else statistics.pstdev
        return ComputeResult("stdev", fn(vals), details={"n": len(vals), "sample": sample})

    def correlation(self, xs: Sequence[float], ys: Sequence[float]) -> ComputeResult:
        x = [float(v) for v in xs]
        y = [float(v) for v in ys]
        if len(x) != len(y) or len(x) < 2:
            raise ValueError("xs/ys length mismatch or too short")
        return ComputeResult("correlation", statistics.correlation(x, y), details={"n": len(x)})

    def sum_(self, values: Sequence[float]) -> ComputeResult:
        return ComputeResult("sum", float(sum(float(v) for v in values)), details={"n": len(values)})

    def min_max(self, values: Sequence[float]) -> ComputeResult:
        vals = [float(v) for v in values]
        if not vals:
            raise ValueError("values required")
        return ComputeResult("min_max", {"min": min(vals), "max": max(vals)}, details={"n": len(vals)})

    def unit_convert(self, value: float, *, from_unit: str, to_unit: str) -> ComputeResult:
        key = (from_unit.lower(), to_unit.lower())
        factors = {
            ("m", "km"): 0.001,
            ("km", "m"): 1000.0,
            ("g", "kg"): 0.001,
            ("kg", "g"): 1000.0,
            ("usd", "cents"): 100.0,
            ("cents", "usd"): 0.01,
        }
        if key not in factors:
            raise ValueError(f"unsupported conversion {from_unit}->{to_unit}")
        return ComputeResult(
            "unit_convert",
            float(value) * factors[key],
            unit=to_unit,
            details={"from_unit": from_unit, "to_unit": to_unit},
        )

    def date_delta_days(self, start_iso: str, end_iso: str) -> ComputeResult:
        a = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        return ComputeResult("date_delta_days", (b - a).total_seconds() / 86400.0)

    def safe_div(self, numerator: float, denominator: float) -> ComputeResult:
        if float(denominator) == 0.0:
            raise ValueError("division by zero")
        return ComputeResult("div", float(numerator) / float(denominator))

    def dispatch(self, operation: str, arguments: dict[str, Any]) -> ComputeResult:
        op = str(operation or "").lower()
        args = dict(arguments or {})
        if op == "cagr":
            return self.cagr(float(args["start"]), float(args["end"]), float(args["periods"]))
        if op in {"percent_change", "pct_change"}:
            return self.percent_change(float(args["start"]), float(args["end"]))
        if op == "mean":
            return self.mean(args["values"])
        if op == "median":
            return self.median(args["values"])
        if op == "stdev":
            return self.stdev(args["values"], sample=bool(args.get("sample", True)))
        if op == "correlation":
            return self.correlation(args["xs"], args["ys"])
        if op == "sum":
            return self.sum_(args["values"])
        if op in {"min_max", "minmax"}:
            return self.min_max(args["values"])
        if op == "unit_convert":
            return self.unit_convert(
                float(args["value"]),
                from_unit=str(args["from_unit"]),
                to_unit=str(args["to_unit"]),
            )
        if op == "date_delta_days":
            return self.date_delta_days(str(args["start"]), str(args["end"]))
        if op in {"div", "divide"}:
            return self.safe_div(float(args["numerator"]), float(args["denominator"]))
        raise ValueError(f"unknown compute operation: {operation}")
