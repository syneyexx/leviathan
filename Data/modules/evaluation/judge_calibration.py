"""LLM judge calibration — judge only where necessary; else UNMEASURED (W12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence


@dataclass(frozen=True)
class LabeledJudgeExample:
    example_id: str
    prediction: str  # judge output label
    gold: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JudgeCalibrationReport:
    judge_id: str
    n: int
    accuracy: float | None
    agreement_with_gold: float | None
    threshold: float
    reliable: bool
    measurement: str  # PASSED | UNMEASURED | FAILED
    detail: str = ""
    examples_used: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "judge_id": self.judge_id,
            "n": self.n,
            "accuracy": self.accuracy,
            "agreement_with_gold": self.agreement_with_gold,
            "threshold": self.threshold,
            "reliable": self.reliable,
            "measurement": self.measurement,
            "detail": self.detail,
            "examples_used": self.examples_used,
            "truth": {
                "uncalibrated_judge_is_unmeasured": not self.reliable,
                "deterministic_scorer_preferred": True,
                "llm_judge_only_when_necessary": True,
            },
        }


def calibrate_judge(
    examples: Sequence[LabeledJudgeExample],
    *,
    judge_id: str = "default",
    threshold: float = 0.7,
    min_examples: int = 5,
) -> JudgeCalibrationReport:
    """Calibrate against labeled examples. Below threshold → UNMEASURED."""
    n = len(examples)
    if n < min_examples:
        return JudgeCalibrationReport(
            judge_id=judge_id,
            n=n,
            accuracy=None,
            agreement_with_gold=None,
            threshold=threshold,
            reliable=False,
            measurement="UNMEASURED",
            detail=f"need>={min_examples} labeled examples; got {n}",
            examples_used=n,
        )
    matches = sum(
        1
        for ex in examples
        if str(ex.prediction).strip().lower() == str(ex.gold).strip().lower()
    )
    acc = matches / n
    reliable = acc >= threshold
    return JudgeCalibrationReport(
        judge_id=judge_id,
        n=n,
        accuracy=acc,
        agreement_with_gold=acc,
        threshold=threshold,
        reliable=reliable,
        measurement="PASSED" if reliable else "UNMEASURED",
        detail=(
            f"accuracy={acc:.3f} threshold={threshold}"
            if reliable
            else f"judge reliability {acc:.3f} below threshold {threshold} → UNMEASURED"
        ),
        examples_used=n,
    )


def judge_or_unmeasured(
    *,
    calibrated: JudgeCalibrationReport,
    judge_fn: Callable[[str], str] | None,
    text: str,
) -> dict[str, Any]:
    """Invoke LLM judge only when calibration says reliable; else UNMEASURED."""
    if not calibrated.reliable or judge_fn is None:
        return {
            "label": None,
            "measurement": "UNMEASURED",
            "reason": calibrated.detail or "judge_not_reliable",
            "truth": {"uncalibrated_judge_is_unmeasured": True},
        }
    label = judge_fn(text)
    return {
        "label": label,
        "measurement": "MEASURED",
        "calibration": calibrated.public_dict(),
        "truth": {"uncalibrated_judge_is_unmeasured": False},
    }
