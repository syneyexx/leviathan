from __future__ import annotations

from typing import Any, Sequence

from Data.modules.verification.types import VerificationOutcome

from .preference_schema import PreferenceRecord, build_preference_record
from .preference_store import PreferenceStore
from .registry import TrainingRegistry
from .types import TrainingJob


class PreferenceBridge:
    """Derive preference-optimization training intents from Verification + human preference.

    Does not fabricate preference labels or start training. Registers intents only
    unless a TrainingRecipeRegistry execute path is explicitly invoked by the caller.
    Durable PreferenceRecord rows are stored when a PreferenceStore is attached.
    """

    def __init__(
        self,
        registry: TrainingRegistry,
        *,
        preference_store: PreferenceStore | None = None,
    ) -> None:
        self.registry = registry
        self.preference_store = preference_store

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
        preferred_id: str | None = None,
        rejected_id: str | None = None,
        preferred_text: str | None = None,
        rejected_text: str | None = None,
        prompt: str = "",
        recipe_id: str = "pref_dpo_v1",
        note: str = "",
        annotator: str | None = None,
        rubric: str | None = None,
        profile: str | None = None,
    ) -> TrainingJob:
        """Register a human preference pair for later DPO-style optimization.

        Accepts either opaque ids (legacy) or full preferred/rejected texts (Wave 9 schema).
        When texts are provided and a PreferenceStore is attached, a durable PreferenceRecord
        is saved and exposed via ``last_preference_record``.
        """
        self.last_preference_record: PreferenceRecord | None = None
        if preferred_text and rejected_text:
            record = build_preference_record(
                prompt=prompt or "human preference",
                preferred_text=preferred_text,
                rejected_text=rejected_text,
                rubric=rubric,
                profile=profile,
                annotator=annotator,
                source="human",
                metadata={"note": note.strip()[:200], "recipe_id": recipe_id},
            )
            if self.preference_store is not None:
                self.preference_store.save(record)
            self.last_preference_record = record
            preferred = record.preferred_id or ""
            rejected = record.rejected_id or ""
        else:
            preferred = (preferred_id or "").strip()
            rejected = (rejected_id or "").strip()
            if not preferred or not rejected:
                raise ValueError("preferred/rejected ids or texts are required")
            if preferred == rejected:
                raise ValueError("preferred and rejected must differ")
        return self.registry.register(
            name=f"pref_human:{(preferred or '')[:24]}",
            objective=(
                f"recipe={recipe_id}; preferred={preferred}; rejected={rejected}; "
                f"source=human_preference; note={note.strip()[:200]}"
                + (
                    f"; preference_id={self.last_preference_record.preference_id}"
                    if self.last_preference_record
                    else ""
                )
            ),
        )
