from __future__ import annotations

from typing import Any, Sequence

from Data.modules.verification.types import VerificationOutcome

from .registry import TrainingRegistry
from .types import TrainingJob


class PreferenceBridge:
    """Derive preference-optimization training intents from Verification + human preference.

    Does not fabricate preference labels or start training. Registers intents only
    unless a TrainingRecipeRegistry execute path is explicitly invoked by the caller.
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

    def register_human_preference(
        self,
        *,
        preferred_id: str,
        rejected_id: str,
        recipe_id: str = "pref_dpo_v1",
        note: str = "",
    ) -> TrainingJob:
        """Register a human preference pair for later DPO-style optimization."""
        preferred = preferred_id.strip()
        rejected = rejected_id.strip()
        if not preferred or not rejected:
            raise ValueError("preferred_id and rejected_id are required")
        if preferred == rejected:
            raise ValueError("preferred_id and rejected_id must differ")
        return self.registry.register(
            name=f"pref_human:{preferred[:24]}",
            objective=(
                f"recipe={recipe_id}; preferred={preferred}; rejected={rejected}; "
                f"source=human_preference; note={note.strip()[:200]}"
            ),
        )
