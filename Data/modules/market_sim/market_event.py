"""Normalized current-market event contract.

Domain owner: market_sim.
Transport DTOs in provider_io may map into this type; they must not diverge.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class MarketEventType(str, Enum):
    TRADE = "TRADE"
    QUOTE = "QUOTE"
    BAR_UPDATE = "BAR_UPDATE"
    BAR_CLOSE = "BAR_CLOSE"
    HEARTBEAT = "HEARTBEAT"
    STATUS = "STATUS"
    GAP = "GAP"
    SNAPSHOT = "SNAPSHOT"


@dataclass
class MarketBarPayload:
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    timeframe: str | None = None
    open_ts: str | None = None
    close_ts: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketEventProvenance:
    provider: str
    endpoint: str = ""
    stream: str = ""
    subscription: str = ""
    transport: str = "websocket"
    license_state: str = "PUBLIC_TERMS_APPLY"
    license_note: str = ""

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketEventTruth:
    observed_market_data: bool = True
    not_execution_fill: bool = True
    not_orderbook: bool = True
    paper_only_execution_system: bool = True

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketEvent:
    event_id: str
    provider_id: str
    connection_id: str
    symbol: str
    event_type: MarketEventType
    instrument_family: str = "crypto_spot"
    exchange_ts: str | None = None
    received_at: str | None = None
    available_at: str | None = None
    sequence: int | None = None
    sequence_source: str | None = None
    price: float | None = None
    size: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    bar: MarketBarPayload | None = None
    provider_payload_hash: str | None = None
    provenance: MarketEventProvenance | None = None
    truth: MarketEventTruth = field(default_factory=MarketEventTruth)
    status: str | None = None
    gap_from_seq: int | None = None
    gap_to_seq: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "provider_id": self.provider_id,
            "connection_id": self.connection_id,
            "symbol": self.symbol,
            "instrument_family": self.instrument_family,
            "event_type": self.event_type.value if isinstance(self.event_type, MarketEventType) else self.event_type,
            "exchange_ts": self.exchange_ts,
            "received_at": self.received_at,
            "available_at": self.available_at,
            "sequence": self.sequence,
            "sequence_source": self.sequence_source,
            "price": self.price,
            "size": self.size,
            "bid": self.bid,
            "ask": self.ask,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "bar": self.bar.public_dict() if self.bar else None,
            "provider_payload_hash": self.provider_payload_hash,
            "provenance": self.provenance.public_dict() if self.provenance else None,
            "truth": self.truth.public_dict(),
            "status": self.status,
            "gap_from_seq": self.gap_from_seq,
            "gap_to_seq": self.gap_to_seq,
            "metadata": dict(self.metadata),
        }

    def identity_hash(self) -> str:
        """Deterministic collision-safe identity when provider event IDs are absent."""
        payload = {
            "provider_id": self.provider_id,
            "symbol": self.symbol,
            "event_type": self.event_type.value if isinstance(self.event_type, MarketEventType) else self.event_type,
            "exchange_ts": self.exchange_ts,
            "sequence": self.sequence,
            "price": self.price,
            "size": self.size,
            "bid": self.bid,
            "ask": self.ask,
            "bar": self.bar.public_dict() if self.bar else None,
            "provider_payload_hash": self.provider_payload_hash,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_provider_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
