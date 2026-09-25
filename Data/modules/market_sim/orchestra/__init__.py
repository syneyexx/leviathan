"""Trade Orchestras & Trade Agents — trading-only agents on the existing Agent Fleet.

Canonical architecture reference: Data/docs/Leviathan_system_backend.md.

- Agent definitions/missions: Agent Fleet (no second fleet). This package registers a
  kind executor for ``AgentDefinitionKind.TRADING`` and claims orchestrators whose role is
  ``trade_orchestra``.
- Risk decisions: deterministic ``Mandate`` + ``RiskGuard`` (agents explain, never decide).
- News: fetched only through the ``provider_io`` pool; every item carries ``available_at``
  and is invisible to any decision whose ``as_of`` precedes it.
- Persistence: central SQLite (migration 43) — decisions are append-only.
- Model calls: Model Control Plane via ``TradingModelAdapter``; a deterministic fake is
  used in tests. No LLM in the per-bar kernel loop.
"""

from .types import (
    AutonomyLevel,
    DecisionRecord,
    Mandate,
    MissionKind,
    NewsFeed,
    NewsItem,
    NewsSignal,
    Readiness,
)
from .service import TradingOrchestraService, TradingOrchestraError

__all__ = [
    "AutonomyLevel",
    "DecisionRecord",
    "Mandate",
    "MissionKind",
    "NewsFeed",
    "NewsItem",
    "NewsSignal",
    "Readiness",
    "TradingOrchestraError",
    "TradingOrchestraService",
]
