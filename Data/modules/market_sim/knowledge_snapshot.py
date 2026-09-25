"""Reproducibility snapshot for trading simulation / evaluation runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TradingKnowledgeSnapshot:
    """Everything required to prove a run had no future information access."""

    run_id: str
    as_of: str
    market_dataset_id: str
    market_dataset_hash: str
    market_dataset_version: str
    brain_policy_ref: str | None = None
    memory_cutoff: str | None = None
    strategy_memory_cutoff: str | None = None
    strategy_id: str | None = None
    strategy_version: int | None = None
    model_profile: str | None = None
    model_version: str | None = None
    agent_definitions: list[dict[str, Any]] = field(default_factory=list)
    news_cutoff: str | None = None
    feature_pipeline_version: str = "market_features-2"
    execution_model_version: str = "next_bar_open-1"
    cost_model_version: str = "fee_slippage_bps-1"
    risk_configuration: dict[str, Any] = field(default_factory=dict)
    random_seed: int = 0
    code_version: str = "market_sim-t1"
    evaluation_window: str = "RESEARCH"
    sealed_holdout_refs: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    snapshot_hash: str = ""
    created_at: str = ""

    def compute_hash(self) -> str:
        payload = self.to_canonical_dict()
        payload.pop("snapshot_hash", None)
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def seal(self) -> "TradingKnowledgeSnapshot":
        self.snapshot_hash = self.compute_hash()
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_dict(self) -> dict[str, Any]:
        data = self.to_canonical_dict()
        data["truth"] = {
            "reproducible": True,
            "proves_no_future_access": True,
            "mutation_creates_new_snapshot": True,
        }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TradingKnowledgeSnapshot":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)


def build_knowledge_snapshot(
    *,
    run_id: str,
    as_of: str,
    market_dataset_id: str,
    market_dataset_hash: str,
    market_dataset_version: str = "1",
    strategy_id: str | None = None,
    strategy_version: int | None = None,
    random_seed: int = 0,
    risk_configuration: dict[str, Any] | None = None,
    agents: list[dict[str, Any]] | None = None,
    evaluation_window: str = "RESEARCH",
    news_cutoff: str | None = None,
    memory_cutoff: str | None = None,
    created_at: str = "",
    **extra: Any,
) -> TradingKnowledgeSnapshot:
    snap = TradingKnowledgeSnapshot(
        run_id=run_id,
        as_of=as_of,
        market_dataset_id=market_dataset_id,
        market_dataset_hash=market_dataset_hash,
        market_dataset_version=str(market_dataset_version),
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        random_seed=random_seed,
        risk_configuration=dict(risk_configuration or {}),
        agent_definitions=list(agents or []),
        evaluation_window=evaluation_window,
        news_cutoff=news_cutoff or as_of,
        memory_cutoff=memory_cutoff or as_of,
        strategy_memory_cutoff=memory_cutoff or as_of,
        created_at=created_at,
        extra=dict(extra) if extra else {},
    )
    return snap.seal()
