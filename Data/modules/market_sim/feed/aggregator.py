"""Deterministic trade → OHLCV bar aggregation for current-market feeds."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from Data.modules.market_sim.market_event import (
    MarketBarPayload,
    MarketEvent,
    MarketEventProvenance,
    MarketEventType,
    MarketEventTruth,
    hash_provider_payload,
)
from Data.modules.market_sim.types import Bar


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def timeframe_seconds(tf: str) -> int:
    mapping = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
        "1D": 86400,
    }
    return mapping.get(tf, 60)


def bar_open_floor(ts: datetime, timeframe: str) -> datetime:
    sec = timeframe_seconds(timeframe)
    epoch = int(ts.timestamp())
    floored = epoch - (epoch % sec)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


@dataclass
class BuildingBar:
    symbol: str
    timeframe: str
    open_ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    trade_count: int = 0

    def apply_trade(self, price: float, size: float | None) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += float(size or 0.0)
        self.trade_count += 1

    def to_bar(self) -> Bar:
        return Bar(
            ts=self.open_ts,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )

    def to_payload(self, *, close_ts: str | None = None) -> MarketBarPayload:
        return MarketBarPayload(
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            timeframe=self.timeframe,
            open_ts=self.open_ts,
            close_ts=close_ts,
        )


@dataclass
class BarAggregator:
    timeframe: str = "1m"
    late_policy: str = "accept_if_building"  # or drop_late
    _building: dict[str, BuildingBar] = field(default_factory=dict)
    _closed: dict[str, list[Bar]] = field(default_factory=dict)
    _last_closed_open_ts: dict[str, str] = field(default_factory=dict)
    corrections: list[dict[str, Any]] = field(default_factory=list)

    def on_trade(
        self,
        *,
        symbol: str,
        price: float,
        size: float | None,
        exchange_ts: str | None,
        received_at: str,
        available_at: str,
        provider_id: str,
        connection_id: str,
        provenance: MarketEventProvenance | None = None,
    ) -> list[MarketEvent]:
        if exchange_ts is None:
            # Cannot place trade into a causal bar without exchange time.
            return []
        ts = _parse_ts(exchange_ts)
        open_dt = bar_open_floor(ts, self.timeframe)
        open_ts = _iso(open_dt)
        out: list[MarketEvent] = []
        current = self._building.get(symbol)

        if current and current.open_ts != open_ts:
            # Close previous bar at boundary.
            close_ts = current.open_ts  # open of new bar is close boundary
            # Prefer actual next open as close marker.
            close_ts = open_ts
            closed = self._finalize(symbol, current, close_ts=close_ts)
            out.append(
                self._bar_event(
                    closed,
                    event_type=MarketEventType.BAR_CLOSE,
                    provider_id=provider_id,
                    connection_id=connection_id,
                    received_at=received_at,
                    available_at=available_at,
                    provenance=provenance,
                )
            )
            current = None

        if current is None:
            # Late trade into already-closed bar?
            last_closed = self._last_closed_open_ts.get(symbol)
            if last_closed and open_ts <= last_closed:
                if self.late_policy == "drop_late":
                    return out
                self.corrections.append(
                    {
                        "symbol": symbol,
                        "open_ts": open_ts,
                        "price": price,
                        "size": size,
                        "exchange_ts": exchange_ts,
                        "note": "late trade after bar close — recorded as correction provenance only",
                    }
                )
                return out
            current = BuildingBar(
                symbol=symbol,
                timeframe=self.timeframe,
                open_ts=open_ts,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=float(size or 0.0),
                trade_count=1,
            )
            self._building[symbol] = current
        else:
            current.apply_trade(price, size)

        out.append(
            self._bar_event(
                current,
                event_type=MarketEventType.BAR_UPDATE,
                provider_id=provider_id,
                connection_id=connection_id,
                received_at=received_at,
                available_at=available_at,
                provenance=provenance,
            )
        )
        return out

    def ingest_closed_bar(
        self,
        *,
        symbol: str,
        bar: Bar,
        timeframe: str,
        provider_id: str,
        connection_id: str,
        received_at: str,
        available_at: str,
        exchange_ts: str | None = None,
        provenance: MarketEventProvenance | None = None,
    ) -> MarketEvent:
        self._closed.setdefault(symbol, []).append(bar)
        self._last_closed_open_ts[symbol] = bar.ts
        building = BuildingBar(
            symbol=symbol,
            timeframe=timeframe,
            open_ts=bar.ts,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        return self._bar_event(
            building,
            event_type=MarketEventType.BAR_CLOSE,
            provider_id=provider_id,
            connection_id=connection_id,
            received_at=received_at,
            available_at=available_at,
            provenance=provenance,
            exchange_ts=exchange_ts or bar.ts,
        )

    def closed_bars(self, symbol: str) -> list[Bar]:
        return list(self._closed.get(symbol, []))

    def building(self, symbol: str) -> BuildingBar | None:
        return self._building.get(symbol)

    def _finalize(self, symbol: str, building: BuildingBar, *, close_ts: str) -> BuildingBar:
        self._closed.setdefault(symbol, []).append(building.to_bar())
        self._last_closed_open_ts[symbol] = building.open_ts
        self._building.pop(symbol, None)
        return building

    def _bar_event(
        self,
        building: BuildingBar,
        *,
        event_type: MarketEventType,
        provider_id: str,
        connection_id: str,
        received_at: str,
        available_at: str,
        provenance: MarketEventProvenance | None,
        exchange_ts: str | None = None,
    ) -> MarketEvent:
        payload = building.to_payload(
            close_ts=None if event_type == MarketEventType.BAR_UPDATE else building.open_ts
        )
        body = payload.public_dict()
        eid = hash_provider_payload(
            {
                "provider": provider_id,
                "symbol": building.symbol,
                "type": event_type.value,
                "open_ts": building.open_ts,
                "close": building.close,
                "volume": building.volume,
            }
        )
        return MarketEvent(
            event_id=eid,
            provider_id=provider_id,
            connection_id=connection_id,
            symbol=building.symbol,
            event_type=event_type,
            exchange_ts=exchange_ts or building.open_ts,
            received_at=received_at,
            available_at=available_at,
            price=building.close,
            bar=payload,
            provider_payload_hash=hash_provider_payload(body),
            provenance=provenance
            or MarketEventProvenance(provider=provider_id, transport="aggregate"),
            truth=MarketEventTruth(not_orderbook=True),
        )
