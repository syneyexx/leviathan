"""A01 release thresholds — fixed BEFORE live measurement.

Do not lower these after a measurement run to manufacture a pass.
Missing live metrics remain UNMEASURED; they are not treated as failures of
software/infra layers.
"""

from __future__ import annotations

from typing import Any

# Bump only when intentionally changing the contract (never to chase a score).
THRESHOLD_VERSION = "a01_release_thresholds_v2"

RELEASE_THRESHOLDS: dict[str, Any] = {
    "version": THRESHOLD_VERSION,
    "layers": {
        "software": {
            "description": "Deterministic software/unit fixtures and harness wiring",
            "pass_rate_min": 1.0,
            "false_success_rate_max": 0.0,
            "required": True,
        },
        "infra_smoke": {
            "description": "LM Studio / provider reachability smoke (not model quality)",
            "pass_when_available": True,
            "unmeasured_allowed_when_unavailable": True,
            "required": False,
        },
        "model_answer": {
            "description": "Strict live judges on model answers",
            "first_attempt_success_min": 0.5,
            "false_success_rate_max": 0.0,
            # T12: when measured, regressions fail the gate. UNMEASURED stays allowed
            # without LM Studio so offline CI remains honest.
            "unmeasured_allowed_when_unavailable": True,
            "required": True,
        },
        "agent_task": {
            "description": "Complete agent tasks via production route; evidence-backed",
            "first_attempt_success_min": 0.4,
            "repeated_reliability_min": 0.3,
            "false_success_rate_max": 0.0,
            "policy_violation_rate_max": 0.0,
            "unmeasured_allowed_when_unavailable": True,
            "required": True,
        },
    },
    "metrics_required_fields": [
        "first_attempt_success",
        "repeated_reliability",
        "false_success_rate",
        "policy_violations",
        "duration_seconds",
        "tokens",
        "error_categories",
        "tool_success_ratio",
        "task_completion",
        "model_calls",
        "latency_ms",
    ],
    "honesty": {
        "missing_values": "report_null_with_reason",
        "retries_preserve_prior_failures": True,
        "do_not_lower_after_measurement": True,
    },
}


def evaluate_thresholds(layer_reports: dict[str, Any]) -> dict[str, Any]:
    """Compare layer summaries against fixed thresholds.

    Returns gate result without mutating thresholds.
    """
    results: list[dict[str, Any]] = []
    overall = True
    for layer, spec in RELEASE_THRESHOLDS["layers"].items():
        report = layer_reports.get(layer) or {}
        status = report.get("status") or report.get("measurement_status")
        row: dict[str, Any] = {
            "layer": layer,
            "required": bool(spec.get("required")),
            "status": status,
            "passed_gate": True,
            "reasons": [],
        }
        if status in {"unmeasured", "UNMEASURED", "not_attempted"}:
            if spec.get("unmeasured_allowed_when_unavailable"):
                row["passed_gate"] = True
                row["reasons"].append("unmeasured_allowed")
            elif spec.get("required"):
                row["passed_gate"] = False
                row["reasons"].append("required_layer_unmeasured")
                overall = False
            results.append(row)
            continue

        if "pass_rate_min" in spec and report.get("pass_rate") is not None:
            if float(report["pass_rate"]) < float(spec["pass_rate_min"]):
                row["passed_gate"] = False
                row["reasons"].append(
                    f"pass_rate {report['pass_rate']} < {spec['pass_rate_min']}"
                )
                overall = False
        for key, thresh_key in (
            ("first_attempt_success", "first_attempt_success_min"),
            ("repeated_reliability", "repeated_reliability_min"),
        ):
            if thresh_key in spec and report.get(key) is not None:
                if float(report[key]) < float(spec[thresh_key]):
                    row["passed_gate"] = False
                    row["reasons"].append(f"{key} {report[key]} < {spec[thresh_key]}")
                    if spec.get("required"):
                        overall = False
                    elif not spec.get("unmeasured_allowed_when_unavailable"):
                        overall = False
        for key, thresh_key in (
            ("false_success_rate", "false_success_rate_max"),
            ("policy_violation_rate", "policy_violation_rate_max"),
        ):
            if thresh_key in spec and report.get(key) is not None:
                if float(report[key]) > float(spec[thresh_key]):
                    row["passed_gate"] = False
                    row["reasons"].append(f"{key} {report[key]} > {spec[thresh_key]}")
                    overall = False
        if not row["passed_gate"] and not spec.get("required"):
            # Soft layers fail their own gate but do not fail overall software release
            # unless false-success / policy violated.
            if not any("false_success" in r or "policy_violation" in r for r in row["reasons"]):
                pass
        results.append(row)

    return {
        "threshold_version": THRESHOLD_VERSION,
        "overall_software_release_ok": overall,
        "layers": results,
        "note": (
            "Live model/agent layers may be UNMEASURED without LM Studio. "
            "Thresholds are fixed in THRESHOLD_VERSION; do not lower after measurement."
        ),
    }
