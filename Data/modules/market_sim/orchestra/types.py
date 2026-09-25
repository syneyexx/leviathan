"""Typed contracts for trade orchestras, trade agents, decisions and news signals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AutonomyLevel(str, Enum):
    """Readiness ladder (frontier_program.md §Y). A5 (live) does not exist by design."""

    A0_GYM = "A0"
    A1_VALIDATION = "A1"
    A2_SEALED_ONCE = "A2"
    A3_SHADOW_PAPER = "A3"
    A4_AUTONOMOUS_PAPER = "A4"

    @property
    def rank(self) -> int:
        return int(self.value[1])

    @classmethod
    def parse(cls, raw: Any, default: "AutonomyLevel | None" = None) -> "AutonomyLevel":
        text = str(raw or "").strip().upper()
        for level in cls:
            if text in {level.value, level.name}:
                return level
        if default is not None:
            return default
        raise ValueError(f"Unknown autonomy level: {raw!r} (allowed A0..A4; live is never a level)")


class Readiness(str, Enum):
    UNMEASURED = "UNMEASURED"
    MEASURED = "MEASURED"


class MissionKind(str, Enum):
    DELIBERATION_ROUND = "deliberation_round"
    NEWS_DIGEST = "news_digest"
    POST_MORTEM = "post_mortem"

    @classmethod
    def parse(cls, raw: Any) -> "MissionKind":
        text = str(raw or "").strip().lower()
        for kind in cls:
            if text == kind.value:
                return kind
        raise ValueError(f"Unknown trading mission kind: {raw!r}")


TRADING_ROLES: tuple[str, ...] = (
    "trade_orchestra",
    "signal_analyst",
    "news_analyst",
    "macro_regime_analyst",
    "strategy_author",
    "critic",
    "risk_officer",
    "execution_agent",
    "evaluator",
    "postmortem_agent",
    # legacy role keys kept for compatibility with existing fleet rows
    "market_analyst",
    "strategy_researcher",
    "risk_agent",
    "portfolio_manager",
    "trading_orchestrator",
)


@dataclass(frozen=True)
class Mandate:
    """Deterministic limits owned by the operator. Loosening is approval-gated (service)."""

    universe: tuple[str, ...] = ()
    paper_capital: float = 100_000.0
    max_gross_exposure_pct: float = 100.0
    max_symbol_exposure_pct: float = 25.0
    per_trade_risk_pct: float = 1.0
    max_orders_per_day: int = 20
    max_drawdown_pct: float = 20.0
    allowed_order_types: tuple[str, ...] = ("MARKET",)
    allowed_families: tuple[str, ...] = ("equity", "crypto_spot")
    autonomy_level: AutonomyLevel = AutonomyLevel.A0_GYM
    readiness_ceiling: AutonomyLevel = AutonomyLevel.A4_AUTONOMOUS_PAPER
    decision_cadence: str = "daily_close"  # daily_close | hourly | every_n_bars | event_driven
    max_model_calls_per_mission: int = 24
    max_tokens_per_mission: int = 24_000
    # Immutable by construction: a mandate can never grant live trading.
    cannot_enable_live: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "universe": list(self.universe),
            "paperCapital": self.paper_capital,
            "maxGrossExposurePct": self.max_gross_exposure_pct,
            "maxSymbolExposurePct": self.max_symbol_exposure_pct,
            "perTradeRiskPct": self.per_trade_risk_pct,
            "maxOrdersPerDay": self.max_orders_per_day,
            "maxDrawdownPct": self.max_drawdown_pct,
            "allowedOrderTypes": list(self.allowed_order_types),
            "allowedFamilies": list(self.allowed_families),
            "autonomyLevel": self.autonomy_level.value,
            "readinessCeiling": self.readiness_ceiling.value,
            "decisionCadence": self.decision_cadence,
            "maxModelCallsPerMission": self.max_model_calls_per_mission,
            "maxTokensPerMission": self.max_tokens_per_mission,
            "cannotEnableLive": True,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "Mandate":
        data = dict(raw or {})

        def _get(*keys: str, default: Any = None) -> Any:
            for key in keys:
                if key in data and data[key] is not None:
                    return data[key]
            return default

        universe = _get("universe", default=[]) or []
        if isinstance(universe, str):
            universe = [part.strip() for part in universe.split(",") if part.strip()]
        order_types = _get("allowedOrderTypes", "allowed_order_types", default=["MARKET"]) or ["MARKET"]
        families = _get("allowedFamilies", "allowed_families", default=["equity", "crypto_spot"])
        mandate = cls(
            universe=tuple(str(s).strip().upper() for s in universe if str(s).strip()),
            paper_capital=float(_get("paperCapital", "paper_capital", default=100_000.0)),
            max_gross_exposure_pct=float(_get("maxGrossExposurePct", "max_gross_exposure_pct", default=100.0)),
            max_symbol_exposure_pct=float(_get("maxSymbolExposurePct", "max_symbol_exposure_pct", default=25.0)),
            per_trade_risk_pct=float(_get("perTradeRiskPct", "per_trade_risk_pct", default=1.0)),
            max_orders_per_day=int(_get("maxOrdersPerDay", "max_orders_per_day", default=20)),
            max_drawdown_pct=float(_get("maxDrawdownPct", "max_drawdown_pct", default=20.0)),
            allowed_order_types=tuple(str(o).upper() for o in order_types),
            allowed_families=tuple(str(f).lower() for f in (families or [])),
            autonomy_level=AutonomyLevel.parse(
                _get("autonomyLevel", "autonomy_level", default="A0"), AutonomyLevel.A0_GYM
            ),
            readiness_ceiling=AutonomyLevel.parse(
                _get("readinessCeiling", "readiness_ceiling", default="A4"), AutonomyLevel.A4_AUTONOMOUS_PAPER
            ),
            decision_cadence=str(_get("decisionCadence", "decision_cadence", default="daily_close")),
            max_model_calls_per_mission=int(_get("maxModelCallsPerMission", "max_model_calls_per_mission", default=24)),
            max_tokens_per_mission=int(_get("maxTokensPerMission", "max_tokens_per_mission", default=24_000)),
        )
        mandate.validate()
        return mandate

    def validate(self) -> None:
        if self.paper_capital <= 0:
            raise ValueError("paperCapital must be > 0")
        for name, value, hi in (
            ("maxGrossExposurePct", self.max_gross_exposure_pct, 300.0),
            ("maxSymbolExposurePct", self.max_symbol_exposure_pct, 100.0),
            ("perTradeRiskPct", self.per_trade_risk_pct, 10.0),
            ("maxDrawdownPct", self.max_drawdown_pct, 100.0),
        ):
            if value <= 0 or value > hi:
                raise ValueError(f"{name} must be in (0, {hi}]")
        if self.max_orders_per_day < 0:
            raise ValueError("maxOrdersPerDay must be >= 0")
        if self.autonomy_level.rank > self.readiness_ceiling.rank:
            raise ValueError("autonomyLevel cannot exceed readinessCeiling")
        if self.decision_cadence not in {"daily_close", "hourly", "every_n_bars", "event_driven"}:
            raise ValueError(f"Unsupported decisionCadence: {self.decision_cadence}")
        for order_type in self.allowed_order_types:
            if order_type not in {"MARKET", "LIMIT", "STOP", "STOP_LIMIT"}:
                raise ValueError(f"Unsupported order type: {order_type}")

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.public_dict(), sort_keys=True).encode("utf-8")).hexdigest()[:16]

    def is_loosening_of(self, other: "Mandate") -> bool:
        """True when this mandate grants more room than ``other`` on any axis."""
        return (
            self.max_gross_exposure_pct > other.max_gross_exposure_pct
            or self.max_symbol_exposure_pct > other.max_symbol_exposure_pct
            or self.per_trade_risk_pct > other.per_trade_risk_pct
            or self.max_orders_per_day > other.max_orders_per_day
            or self.max_drawdown_pct > other.max_drawdown_pct
            or self.autonomy_level.rank > other.autonomy_level.rank
            or self.readiness_ceiling.rank > other.readiness_ceiling.rank
            or set(self.allowed_order_types) - set(other.allowed_order_types)
            or set(self.allowed_families) - set(other.allowed_families)
            or (bool(other.universe) and (set(self.universe) - set(other.universe) or not self.universe))
        )


@dataclass
class NewsFeed:
    feed_id: str
    name: str
    url: str
    kind: str = "rss"  # rss | atom | http_json
    enabled: bool = True
    declared_latency_seconds: int = 0
    license_state: str = "UNKNOWN"  # UNKNOWN | DECLARED_FREE | DECLARED_RESTRICTED
    symbols_hint: list[str] = field(default_factory=list)
    last_polled_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "feedId": self.feed_id,
            "name": self.name,
            "url": self.url,
            "kind": self.kind,
            "enabled": self.enabled,
            "declaredLatencySeconds": self.declared_latency_seconds,
            "licenseState": self.license_state,
            "symbolsHint": list(self.symbols_hint),
            "lastPolledAt": self.last_polled_at,
            "lastStatus": self.last_status,
            "lastError": self.last_error,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class NewsItem:
    item_id: str
    feed_id: str
    source: str
    url: str
    title: str
    summary: str
    content_hash: str
    published_at: str | None
    fetched_at: str
    available_at: str
    license_state: str = "UNKNOWN"
    symbols_hint: list[str] = field(default_factory=list)
    knowledge_document_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "itemId": self.item_id,
            "feedId": self.feed_id,
            "source": self.source,
            "url": self.url,
            "title": self.title,
            "summary": self.summary,
            "contentHash": self.content_hash,
            "publishedAt": self.published_at,
            "fetchedAt": self.fetched_at,
            "availableAt": self.available_at,
            "licenseState": self.license_state,
            "symbolsHint": list(self.symbols_hint),
            "knowledgeDocumentId": self.knowledge_document_id,
            "truth": {"available_at_is_causal_boundary": True, "text_is_untrusted_context": True},
        }


@dataclass
class NewsSignal:
    signal_id: str
    item_id: str
    agent_id: str
    mission_id: str | None
    instruments: list[str]
    event_type: str
    direction: str  # bullish | bearish | neutral
    magnitude: float  # 0..1
    confidence: float  # 0..1
    horizon: str  # intraday | days | weeks
    rationale: str
    as_of: str  # == item.available_at
    model_id: str | None
    created_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "signalId": self.signal_id,
            "itemId": self.item_id,
            "agentId": self.agent_id,
            "missionId": self.mission_id,
            "instruments": list(self.instruments),
            "eventType": self.event_type,
            "direction": self.direction,
            "magnitude": self.magnitude,
            "confidence": self.confidence,
            "horizon": self.horizon,
            "rationale": self.rationale,
            "asOf": self.as_of,
            "modelId": self.model_id,
            "createdAt": self.created_at,
            "truth": {"signal_is_data_not_authority": True},
        }


@dataclass
class DecisionRecord:
    """One append-only step in the proposal → critique → risk → intent → fill → post-mortem chain."""

    decision_id: str
    orchestra_id: str
    mission_id: str | None
    agent_id: str
    role: str
    stage: str  # proposal | critique | risk_decision | order_intent | fill | post_mortem | digest
    as_of: str
    payload: dict[str, Any]
    parent_decision_id: str | None
    model_id: str | None
    prompt_artifact_id: str | None
    output_artifact_id: str | None
    mandate_fingerprint: str
    created_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "decisionId": self.decision_id,
            "orchestraId": self.orchestra_id,
            "missionId": self.mission_id,
            "agentId": self.agent_id,
            "role": self.role,
            "stage": self.stage,
            "asOf": self.as_of,
            "payload": dict(self.payload),
            "parentDecisionId": self.parent_decision_id,
            "modelId": self.model_id,
            "promptArtifactId": self.prompt_artifact_id,
            "outputArtifactId": self.output_artifact_id,
            "mandateFingerprint": self.mandate_fingerprint,
            "createdAt": self.created_at,
        }
