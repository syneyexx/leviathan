"""Durable ResearchCampaign — multi-step strategy research that can pause/resume (T7 / G25)."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .experiments import walk_forward_splits
from .types import MarketSimError


CAMPAIGN_STATUSES = frozenset(
    {"proposed", "running", "paused", "completed", "failed", "cancelled"}
)
CAMPAIGN_PHASES = (
    "design",
    "validation",
    "holdout",
    "acceptance",
    "done",
)


@dataclass
class ResearchCampaign:
    campaign_id: str
    strategy_id: str
    hypothesis: str
    status: str  # proposed | running | paused | completed | failed | cancelled
    phase: str  # design | validation | holdout | acceptance | done
    proposer_agent_id: str = "human"
    source_id: str | None = None
    data_hash: str = ""
    seed: int = 42
    config: dict[str, Any] = field(default_factory=dict)
    split: dict[str, Any] = field(default_factory=dict)
    checkpoint: dict[str, Any] = field(default_factory=dict)
    trial_ids: list[str] = field(default_factory=list)
    acceptance_criteria: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    paused_at: str | None = None
    resumed_at: str | None = None
    finished_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["truth"] = {
            "durable": True,
            "resumable": True,
            "checkpointed": True,
            "paper_never_auto_approves_live": True,
        }
        return payload


def new_campaign(
    *,
    strategy_id: str,
    hypothesis: str,
    proposer_agent_id: str = "human",
    source_id: str | None = None,
    data_hash: str = "",
    seed: int = 42,
    config: dict[str, Any] | None = None,
    acceptance_criteria: dict[str, Any] | None = None,
    n_bars: int | None = None,
    created_at: str,
) -> ResearchCampaign:
    cfg = dict(config or {})
    split: dict[str, Any] = {}
    if n_bars is not None:
        window = int(cfg.get("window") or max(20, int(n_bars) // 5))
        step = int(cfg.get("step") or max(5, window // 2))
        split = walk_forward_splits(int(n_bars), window=window, step=step)
    return ResearchCampaign(
        campaign_id=str(uuid.uuid4()),
        strategy_id=strategy_id,
        hypothesis=hypothesis,
        status="proposed",
        phase="design",
        proposer_agent_id=proposer_agent_id,
        source_id=source_id,
        data_hash=data_hash,
        seed=seed,
        config=cfg,
        split=split,
        checkpoint={
            "windows_total": len(split.get("windows") or []),
            "windows_done": 0,
            "last_window_index": -1,
        },
        acceptance_criteria=dict(
            acceptance_criteria or {"min_trades": 5, "max_drawdown_pct": 25.0}
        ),
        created_at=created_at,
        updated_at=created_at,
        metadata={},
    )


class ResearchCampaignController:
    """State machine helpers for durable campaign lifecycle."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def create(self, campaign: ResearchCampaign) -> dict[str, Any]:
        return self.store.save_research_campaign(campaign.public_dict())

    def get(self, campaign_id: str) -> dict[str, Any]:
        row = self.store.get_research_campaign(campaign_id)
        if row is None:
            raise MarketSimError("CAMPAIGN_NOT_FOUND", campaign_id, http_status=404)
        return row

    def start(self, campaign_id: str, *, now: str) -> dict[str, Any]:
        c = self.get(campaign_id)
        if c["status"] not in {"proposed", "paused"}:
            raise MarketSimError(
                "CAMPAIGN_NOT_STARTABLE",
                f"status={c['status']}",
                http_status=409,
            )
        c["status"] = "running"
        c["started_at"] = c.get("started_at") or now
        if c.get("paused_at"):
            c["resumed_at"] = now
        c["paused_at"] = None
        c["updated_at"] = now
        c["phase"] = c.get("phase") or "design"
        return self.store.save_research_campaign(c)

    def pause(self, campaign_id: str, *, now: str) -> dict[str, Any]:
        c = self.get(campaign_id)
        if c["status"] != "running":
            raise MarketSimError(
                "CAMPAIGN_NOT_PAUSABLE",
                f"status={c['status']}",
                http_status=409,
            )
        c["status"] = "paused"
        c["paused_at"] = now
        c["updated_at"] = now
        return self.store.save_research_campaign(c)

    def resume(self, campaign_id: str, *, now: str) -> dict[str, Any]:
        c = self.get(campaign_id)
        if c["status"] != "paused":
            raise MarketSimError(
                "CAMPAIGN_NOT_RESUMABLE",
                f"status={c['status']}",
                http_status=409,
            )
        c["status"] = "running"
        c["resumed_at"] = now
        c["paused_at"] = None
        c["updated_at"] = now
        return self.store.save_research_campaign(c)

    def advance(self, campaign_id: str, *, now: str, trial_id: str | None = None) -> dict[str, Any]:
        """Advance one checkpoint step (window / phase). Durable across pause/resume."""
        c = self.get(campaign_id)
        if c["status"] != "running":
            raise MarketSimError(
                "CAMPAIGN_NOT_RUNNING",
                f"status={c['status']} — start or resume first",
                http_status=409,
            )
        checkpoint = dict(c.get("checkpoint") or {})
        windows = list((c.get("split") or {}).get("windows") or [])
        done = int(checkpoint.get("windows_done") or 0)
        last = int(checkpoint.get("last_window_index") or -1)

        if trial_id:
            trials = list(c.get("trial_ids") or [])
            if trial_id not in trials:
                trials.append(trial_id)
            c["trial_ids"] = trials

        if windows and done < len(windows):
            last = done
            done += 1
            checkpoint["windows_done"] = done
            checkpoint["last_window_index"] = last
            checkpoint["last_advanced_at"] = now
            # Phase progression by window thirds.
            frac = done / max(1, len(windows))
            if frac < 0.5:
                c["phase"] = "design"
            elif frac < 0.75:
                c["phase"] = "validation"
            elif frac < 1.0:
                c["phase"] = "holdout"
            else:
                c["phase"] = "acceptance"
        else:
            # No rolling windows — step through named phases.
            phase = str(c.get("phase") or "design")
            try:
                idx = CAMPAIGN_PHASES.index(phase)
            except ValueError:
                idx = 0
            next_phase = CAMPAIGN_PHASES[min(idx + 1, len(CAMPAIGN_PHASES) - 1)]
            c["phase"] = next_phase
            checkpoint["phase_index"] = CAMPAIGN_PHASES.index(next_phase)
            checkpoint["last_advanced_at"] = now
            if next_phase == "done":
                c["status"] = "completed"
                c["finished_at"] = now

        if windows and done >= len(windows) and c["status"] == "running":
            c["phase"] = "acceptance"
            # Auto-complete after all windows when no further acceptance step required.
            if bool((c.get("config") or {}).get("auto_complete_on_windows", True)):
                c["phase"] = "done"
                c["status"] = "completed"
                c["finished_at"] = now

        c["checkpoint"] = checkpoint
        c["updated_at"] = now
        return self.store.save_research_campaign(c)

    def fail(self, campaign_id: str, *, now: str, error: str) -> dict[str, Any]:
        c = self.get(campaign_id)
        c["status"] = "failed"
        c["error"] = error
        c["finished_at"] = now
        c["updated_at"] = now
        return self.store.save_research_campaign(c)

    def cancel(self, campaign_id: str, *, now: str) -> dict[str, Any]:
        c = self.get(campaign_id)
        if c["status"] in {"completed", "failed", "cancelled"}:
            raise MarketSimError(
                "CAMPAIGN_ALREADY_TERMINAL",
                f"status={c['status']}",
                http_status=409,
            )
        c["status"] = "cancelled"
        c["finished_at"] = now
        c["updated_at"] = now
        return self.store.save_research_campaign(c)
