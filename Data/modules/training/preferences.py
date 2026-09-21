from __future__ import annotations

from typing import Any, Sequence

from Data.modules.verification.types import VerificationOutcome

from .registry import TrainingRegistry
from .types import TrainingJob


class PreferenceBridge:
    """Derive preference-optimization training intents from Verification reports.

    Does not fabricate preference labels or start training. Registers intents only.
    """

    def __init__(self, registry: TrainingRegistry) -> None:
        self.registry = registry

    def register_from_verification_reports(
        self,
        reports: Sequence[Any],
        *,
        recipe_id: str = "pref_dpo_v1",
    ) -> list[TrainingJob]:
        created: list[TrainingJob] = []
        for report in reports:
            outcome = getattr(report, "outcome", None)
            report_id = getattr(report, "report_id", None) or (
                report.get("report_id") if isinstance(report, dict) else None
            )
            if outcome is None and isinstance(report, dict):
                outcome = report.get("outcome")
            outcome_value = outcome.value if hasattr(outcome, "value") else str(outcome or "")
            if outcome_value not in {
                VerificationOutcome.PASSED.value,
                VerificationOutcome.FAILED.value,
                "PASSED",
                "FAILED",
            }:
                continue
            job = self.registry.register(
                name=f"pref_from_verify:{report_id}",
                objective=(
                    f"recipe={recipe_id}; verification_report={report_id}; "
                    f"outcome={outcome_value}; preference_pair_pending_human_or_policy"
                ),
            )
            created.append(job)
        return created
