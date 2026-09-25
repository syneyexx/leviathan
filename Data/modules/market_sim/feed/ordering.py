"""Ordering, dedupe, and sequence/time gap detection for MarketEvents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from Data.modules.market_sim.market_event import MarketEvent, MarketEventType
from Data.modules.market_sim.feed.types import OrderingDisposition


@dataclass
class SymbolOrderingState:
    last_sequence: int | None = None
    last_exchange_ts: str | None = None
    seen_ids: dict[str, int] = field(default_factory=dict)
    duplicate_count: int = 0
    gap_count: int = 0
    out_of_order_count: int = 0
    late_count: int = 0
    max_seen_ids: int = 4096

    def remember(self, event_id: str) -> None:
        self.seen_ids[event_id] = self.seen_ids.get(event_id, 0) + 1
        if len(self.seen_ids) > self.max_seen_ids:
            # Drop oldest half (dict preserves insertion order on 3.7+).
            keys = list(self.seen_ids.keys())[: len(self.seen_ids) // 2]
            for k in keys:
                self.seen_ids.pop(k, None)


@dataclass
class OrderingResult:
    disposition: OrderingDisposition
    event: MarketEvent | None
    gap_from: int | None = None
    gap_to: int | None = None
    detail: str = ""


class EventOrderer:
    """Bounded reorder/dedupe window per symbol — never buffers indefinitely."""

    def __init__(self, *, max_reorder_window_ms: float = 2000.0) -> None:
        self.max_reorder_window_ms = max_reorder_window_ms
        self._states: dict[str, SymbolOrderingState] = {}

    def state_for(self, symbol: str) -> SymbolOrderingState:
        if symbol not in self._states:
            self._states[symbol] = SymbolOrderingState()
        return self._states[symbol]

    def accept(self, event: MarketEvent) -> OrderingResult:
        st = self.state_for(event.symbol)
        eid = event.event_id or event.identity_hash()
        if eid in st.seen_ids:
            st.duplicate_count += 1
            st.remember(eid)
            return OrderingResult(
                disposition=OrderingDisposition.DUPLICATE_DROPPED,
                event=None,
                detail="duplicate event_id",
            )
        st.remember(eid)

        if event.sequence is not None and st.last_sequence is not None:
            expected = st.last_sequence + 1
            if event.sequence < expected:
                st.out_of_order_count += 1
                st.late_count += 1
                # Late within window → accept with LATE; far behind → drop.
                lag = expected - event.sequence
                # Sequence lag without timestamps: treat large lag as out-of-window.
                if lag > 1000:
                    return OrderingResult(
                        disposition=OrderingDisposition.OUT_OF_WINDOW_DROPPED,
                        event=None,
                        detail=f"sequence lag {lag}",
                    )
                st.last_sequence = max(st.last_sequence, event.sequence)
                if event.exchange_ts:
                    st.last_exchange_ts = max(st.last_exchange_ts or "", event.exchange_ts)
                return OrderingResult(
                    disposition=OrderingDisposition.LATE_ACCEPTED,
                    event=event,
                    detail="late sequence",
                )
            if event.sequence > expected:
                st.gap_count += 1
                gap_from = expected
                gap_to = event.sequence - 1
                st.last_sequence = event.sequence
                if event.exchange_ts:
                    st.last_exchange_ts = event.exchange_ts
                return OrderingResult(
                    disposition=OrderingDisposition.GAP_DETECTED,
                    event=event,
                    gap_from=gap_from,
                    gap_to=gap_to,
                    detail=f"missing sequences {gap_from}-{gap_to}",
                )

        if event.sequence is not None:
            st.last_sequence = event.sequence
        if event.exchange_ts:
            if st.last_exchange_ts and event.exchange_ts < st.last_exchange_ts:
                st.out_of_order_count += 1
                st.late_count += 1
                return OrderingResult(
                    disposition=OrderingDisposition.LATE_ACCEPTED,
                    event=event,
                    detail="exchange_ts went backwards",
                )
            st.last_exchange_ts = event.exchange_ts

        return OrderingResult(disposition=OrderingDisposition.ORDERED, event=event)

    def detect_bar_gap(
        self,
        symbol: str,
        *,
        prev_open_ts: str | None,
        next_open_ts: str | None,
        timeframe_seconds: int,
    ) -> OrderingResult | None:
        if not prev_open_ts or not next_open_ts or timeframe_seconds <= 0:
            return None
        # Compare ISO timestamps lexicographically when both are UTC ISO.
        # For gap detection we only flag when next is more than one step ahead.
        from datetime import datetime

        def _parse(ts: str) -> datetime:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))

        try:
            prev = _parse(prev_open_ts)
            nxt = _parse(next_open_ts)
        except ValueError:
            return None
        delta = (nxt - prev).total_seconds()
        if delta > timeframe_seconds * 1.5:
            st = self.state_for(symbol)
            st.gap_count += 1
            return OrderingResult(
                disposition=OrderingDisposition.GAP_DETECTED,
                event=None,
                detail=f"bar gap {prev_open_ts} -> {next_open_ts}",
            )
        return None
