"""Evidence-based quality presentation for Dataset Management.

Does NOT invent decorative scores. Quality is only reported when real
validation (and optional related) evidence exists on a version.
"""

from __future__ import annotations

from typing import Any, Mapping


def quality_from_validation(validation: Mapping[str, Any] | None) -> dict[str, Any]:
    """Derive a bounded quality presentation from persisted validation.

    Formula (documented, not absolute truth):
      - If validation is missing/empty → measured=false, score=null, label="Niet gemeten"
      - Else score = clamp(0..100, 100 - 8*errorCount - 2*warningCount - 1*emptyContentCount)
        using only fields present on the validation blob.
      - Segments: five buckets of 20 points for UI bars (filled when score known).

    Constituent measurements are always exposed so operators can audit the bar.
    """
    if not isinstance(validation, dict) or not validation:
        return {
            "measured": False,
            "score": None,
            "label": "Niet gemeten",
            "segments": [False, False, False, False, False],
            "tone": "unknown",
            "constituents": {},
            "truth": {
                "qualityRequiresValidationEvidence": True,
                "unmeasuredIsNotPerfect": True,
                "scoreIsHeuristicNotAbsolute": True,
            },
        }

    errors = _as_nonneg_int(validation.get("errorCount", validation.get("errors")))
    warnings = _as_nonneg_int(validation.get("warningCount", validation.get("warnings")))
    empty = _as_nonneg_int(validation.get("emptyContentCount"))
    row_count = _as_nonneg_int(validation.get("rowCount"))
    valid_flag = validation.get("valid")

    penalty = 8 * errors + 2 * warnings + 1 * empty
    score = max(0, min(100, 100 - penalty))
    if valid_flag is False and errors == 0:
        score = min(score, 40)

    if score >= 80:
        tone = "good"
        label = "Goed"
    elif score >= 55:
        tone = "fair"
        label = "Matig"
    elif score >= 25:
        tone = "poor"
        label = "Zwak"
    else:
        tone = "critical"
        label = "Kritiek"

    segments = [score > i * 20 for i in range(5)]

    return {
        "measured": True,
        "score": score,
        "label": label,
        "segments": segments,
        "tone": tone,
        "constituents": {
            "errorCount": errors,
            "warningCount": warnings,
            "emptyContentCount": empty,
            "rowCount": row_count,
            "valid": valid_flag if isinstance(valid_flag, bool) else None,
            "formula": "clamp(0,100, 100 - 8*errors - 2*warnings - 1*emptyContent)",
        },
        "truth": {
            "qualityRequiresValidationEvidence": True,
            "unmeasuredIsNotPerfect": True,
            "scoreIsHeuristicNotAbsolute": True,
        },
    }


def _as_nonneg_int(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, n)
