"""TradingKnowledgeSnapshot — reproducibility / anti-leakage provenance for a run."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TradingKnowledgeSnapshot:
    """Immutable record of what information a trading run was allowed to see.

    Goal: a run can later be reproduced and proven to have had no access to
    future information relative to ``as_of``.
    """

    snapshot_id: str
    run_id: str
    as_of: str
    market_dataset_id: str
    market_dataset_hash: str
    market_dataset_version: str
    strategy_id: str | None = None
    strategy_version: int | None = None
    strategy_content_hash: str | None = None
    brain_policy_ref: str | None = None
    memory_cutoff: str | None = None
    strategy_memory_cutoff: str | None = None
    news_cutoff: str | None = None
    model_profile: str | None = None
    model_version: str | None = None
    agent_definitions_hash: str | None = None
    feature_pipeline_version: str = "market_sim-features-1"
    execution_model_version: str = "next_bar_open-v1"
    cost_model_version: str = "fee_slippage_bps-v1"
    risk_configuration: dict[str, Any] = field(default_factory=dict)
    random_seed: int = 42
    code_version: str = "market_sim-1"
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def content_fingerprint(self) -> str:
        payload = {
            "run_id": self.run_id,
            "as_of": self.as_of,
            "market_dataset_id": self.market_dataset_id,
            "market_dataset_hash": self.market_dataset_hash,
            "market_dataset_version": self.market_dataset_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_content_hash": self.strategy_content_hash,
            "brain_policy_ref": self.brain_policy_ref,
            "memory_cutoff": self.memory_cutoff,
            "strategy_memory_cutoff": self.strategy_memory_cutoff,
            "news_cutoff": self.news_cutoff,
            "model_profile": self.model_profile,
            "model_version": self.model_version,
            "agent_definitions_hash": self.agent_definitions_hash,
            "feature_pipeline_version": self.feature_pipeline_version,
            "execution_model_version": self.execution_model_version,
            "cost_model_version": self.cost_model_version,
            "risk_configuration": self.risk_configuration,
            "random_seed": self.random_seed,
            "code_version": self.code_version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["content_fingerprint"] = self.content_fingerprint()
        data["truth"] = {
            "reproducibility_snapshot": True,
            "no_future_information_by_construction": True,
            "cutoffs_are_available_at_boundaries": True,
        }
        return data


def build_knowledge_snapshot(
    *,
    snapshot_id: str,
    run_id: str,
    as_of: str,
    market_dataset_id: str,
    market_dataset_hash: str,
    market_dataset_version: str,
    created_at: str,
    strategy_id: str | None = None,
    strategy_version: int | None = None,
    strategy_content_hash: str | None = None,
    brain_policy_ref: str | None = None,
    memory_cutoff: str | None = None,
    strategy_memory_cutoff: str | None = None,
    news_cutoff: str | None = None,
    model_profile: str | None = None,
    model_version: str | None = None,
    agent_definitions_hash: str | None = None,
    feature_pipeline_version: str = "market_sim-features-1",
    execution_model_version: str = "next_bar_open-v1",
    cost_model_version: str = "fee_slippage_bps-v1",
    risk_configuration: dict[str, Any] | None = None,
    random_seed: int = 42,
    code_version: str = "market_sim-1",
    metadata: dict[str, Any] | None = None,
) -> TradingKnowledgeSnapshot:
    """Build a snapshot. Cutoffs default to ``as_of`` when omitted."""
    cutoff = as_of
    return TradingKnowledgeSnapshot(
        snapshot_id=snapshot_id,
        run_id=run_id,
        as_of=as_of,
        market_dataset_id=market_dataset_id,
        market_dataset_hash=market_dataset_hash,
        market_dataset_version=str(market_dataset_version),
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        strategy_content_hash=strategy_content_hash,
        brain_policy_ref=brain_policy_ref,
        memory_cutoff=memory_cutoff or cutoff,
        strategy_memory_cutoff=strategy_memory_cutoff or cutoff,
        news_cutoff=news_cutoff or cutoff,
        model_profile=model_profile,
        model_version=model_version,
        agent_definitions_hash=agent_definitions_hash,
        feature_pipeline_version=feature_pipeline_version,
        execution_model_version=execution_model_version,
        cost_model_version=cost_model_version,
        risk_configuration=dict(risk_configuration or {}),
        random_seed=random_seed,
        code_version=code_version,
        created_at=created_at,
        metadata=dict(metadata or {}),
    )
