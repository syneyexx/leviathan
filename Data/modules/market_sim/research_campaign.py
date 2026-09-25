"""ResearchCampaign — durable, resumable trading research loops (P3B / G25).

Long campaigns are EXTERNAL_REQUIRED on the market_sim worker.
Crash/resume continues from checkpoint_iteration (never rewind from zero).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .store import utc_now
from .types import MarketSimError

CAMPAIGN_STATUSES = frozenset(
    {
        "CREATED",
        "QUEUED",
        "RUNNING",
        "PAUSED",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    }
)


@dataclass
class ResearchCampaign:
    campaign_id: str
    name: str
    strategy_id: str
    strategy_version: int
    source_id: str
    status: str = "CREATED"
    max_iterations: int = 10
    checkpoint_iteration: int = 0
    current_iteration: int = 0
    seed: int = 42
    hypothesis: str = ""
    acceptance_criteria: dict[str, Any] = field(default_factory=dict)
    trial_ids: list[str] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)
    scorecard: dict[str, Any] = field(default_factory=dict)
    promotion: dict[str, Any] = field(default_factory=dict)
    autonomy_ceiling: str = "A2"
    as_of: str = ""
    job_id: str | None = None
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "source_id": self.source_id,
            "status": self.status,
            "max_iterations": self.max_iterations,
            "checkpoint_iteration": self.checkpoint_iteration,
            "current_iteration": self.current_iteration,
            "seed": self.seed,
            "hypothesis": self.hypothesis,
            "acceptance_criteria": dict(self.acceptance_criteria),
            "trial_ids": list(self.trial_ids),
            "results": dict(self.results),
            "scorecard": dict(self.scorecard),
            "promotion": dict(self.promotion),
            "autonomy_ceiling": self.autonomy_ceiling,
            "as_of": self.as_of,
            "job_id": self.job_id,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "truth": {
                "durable": True,
                "resumable": True,
                "no_rewind_on_crash": True,
                "external_worker_required": True,
                "live_money": "BLOCKED",
            },
        }


def new_campaign(
    *,
    name: str,
    strategy_id: str,
    strategy_version: int,
    source_id: str,
    max_iterations: int = 10,
    seed: int = 42,
    hypothesis: str = "",
    acceptance_criteria: dict[str, Any] | None = None,
    autonomy_ceiling: str = "A2",
    as_of: str = "",
    metadata: dict[str, Any] | None = None,
) -> ResearchCampaign:
    from .readiness import assert_not_live_level, normalize_autonomy

    ceiling = normalize_autonomy(autonomy_ceiling, default="A2")
    assert_not_live_level(ceiling)
    now = utc_now()
    return ResearchCampaign(
        campaign_id=str(uuid.uuid4()),
        name=(name or "research").strip() or "research",
        strategy_id=strategy_id,
        strategy_version=int(strategy_version),
        source_id=source_id,
        max_iterations=max(1, int(max_iterations)),
        seed=int(seed),
        hypothesis=hypothesis or "",
        acceptance_criteria=dict(acceptance_criteria or {}),
        autonomy_ceiling=ceiling,
        as_of=as_of or now,
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )


def advance_campaign_iteration(
    campaign: ResearchCampaign,
    *,
    trial_id: str | None = None,
    iteration_result: dict[str, Any] | None = None,
) -> ResearchCampaign:
    """Advance one iteration and checkpoint (resume point = checkpoint_iteration)."""
    if campaign.status in {"COMPLETED", "CANCELLED"}:
        raise MarketSimError(
            "CAMPAIGN_TERMINAL",
            f"campaign {campaign.campaign_id} is {campaign.status}",
            http_status=409,
        )
    nxt = campaign.checkpoint_iteration + 1
    if nxt > campaign.max_iterations:
        campaign.status = "COMPLETED"
        campaign.updated_at = utc_now()
        return campaign
    campaign.current_iteration = nxt
    campaign.checkpoint_iteration = nxt
    campaign.status = "RUNNING"
    if trial_id:
        campaign.trial_ids.append(trial_id)
    if iteration_result is not None:
        iters = list(campaign.results.get("iterations") or [])
        iters.append({"iteration": nxt, **dict(iteration_result)})
        campaign.results = {**dict(campaign.results), "iterations": iters}
    campaign.updated_at = utc_now()
    if campaign.checkpoint_iteration >= campaign.max_iterations:
        campaign.status = "COMPLETED"
    return campaign
