"""Autonomous Research Director mandate runner (W22)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class ResearchMandate:
    mandate_id: str
    objective: str
    max_campaigns: int = 1
    families: tuple[str, ...] = ("equity",)
    sealed_holdout_required: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "mandateId": self.mandate_id,
            "objective": self.objective,
            "maxCampaigns": self.max_campaigns,
            "families": list(self.families),
            "sealedHoldoutRequired": self.sealed_holdout_required,
            "truth": {"knowledge_is_hypothesis_source": True},
        }


@dataclass
class ResearchDirector:
    director_id: str = "research_director"
    campaigns_run: list[dict[str, Any]] = field(default_factory=list)

    def run_under_mandate(
        self,
        mandate: ResearchMandate,
        *,
        campaign_factory: Any,
    ) -> dict[str, Any]:
        """Execute up to max_campaigns via injected factory (no silent live trading)."""
        results: list[dict[str, Any]] = []
        for i in range(max(0, mandate.max_campaigns)):
            campaign = campaign_factory(
                mandate_id=mandate.mandate_id,
                index=i,
                families=list(mandate.families),
                sealed_holdout_required=mandate.sealed_holdout_required,
            )
            payload = campaign if isinstance(campaign, dict) else getattr(campaign, "public_dict", lambda: {"campaign": str(campaign)})()
            results.append(payload)
            self.campaigns_run.append(payload)
        return {
            "directorId": self.director_id,
            "mandate": mandate.public_dict(),
            "campaigns": results,
            "count": len(results),
            "truth": {
                "director_does_not_unlock_live_trading": True,
                "sealed_holdout_honoured": mandate.sealed_holdout_required,
            },
        }
