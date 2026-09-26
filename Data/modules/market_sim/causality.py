"""Strict causality clock — no future bar access.

SimulationClock remains the source of historical time.
Agents must observe markets through MarketView, not raw bar lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .epistemic import assert_no_future_ts, compare_ts
from .types import Bar, CausalityViolation

# Re-export for existing importers (engine, __init__, tests).
__all__ = [
    "CausalityViolation",
    "SimulationClock",
    "MarketView",
    "assert_no_future",
]


@dataclass
class SimulationClock:
    """Single source of truth for simulated time.

    At bar index i, only bars[0..i] inclusive are observable.
    Any attempt to read index > i fails hard via observe()/window().
    Prefer MarketView for agent-facing access — do not hand agents this clock's
    full bar sequence.
    """

    bars: Sequence[Bar]
    index: int = -1  # before first bar
    violations: int = 0

    @property
    def current_ts(self) -> str | None:
        if self.index < 0 or self.index >= len(self.bars):
            return None
        return self.bars[self.index].ts

    @property
    def current_bar(self) -> Bar | None:
        if self.index < 0 or self.index >= len(self.bars):
            return None
        return self.bars[self.index]

    @property
    def bar_count(self) -> int:
        return len(self.bars)

    @property
    def done(self) -> bool:
        return self.index >= len(self.bars) - 1 and len(self.bars) > 0 and self.index >= 0

    def advance(self) -> Bar | None:
        if not self.bars:
            return None
        if self.index >= len(self.bars) - 1:
            return None
        self.index += 1
        return self.bars[self.index]

    def set_index(self, index: int) -> None:
        if index < -1 or index >= len(self.bars):
            raise CausalityViolation(f"Illegal clock index {index} (bar_count={len(self.bars)})")
        self.index = index

    def observe(self, at_index: int) -> Bar:
        """Return bar at_index if and only if at_index <= current index."""
        if self.index < 0:
            self.violations += 1
            raise CausalityViolation("No bars visible before clock starts")
        if at_index < 0 or at_index >= len(self.bars):
            self.violations += 1
            raise CausalityViolation(f"Bar index {at_index} out of range")
        if at_index > self.index:
            self.violations += 1
            raise CausalityViolation(
                f"Look-ahead refused: requested bar {at_index} while clock is at {self.index}"
            )
        return self.bars[at_index]

    def window(self, lookback: int) -> list[Bar]:
        """Causal rolling window ending at current bar (inclusive)."""
        if self.index < 0:
            self.violations += 1
            raise CausalityViolation("No window before clock starts")
        if lookback < 1:
            raise ValueError("lookback must be >= 1")
        start = max(0, self.index - lookback + 1)
        # Explicitly only slice up to index inclusive — never beyond.
        return [self.bars[i] for i in range(start, self.index + 1)]

    def closes(self, lookback: int) -> list[float]:
        return [b.close for b in self.window(lookback)]


@dataclass
class MarketView:
    """Bounded market observation surface for agents and strategies.

    Never exposes future bars. Historical views are governed by SimulationClock.
    """

    clock: SimulationClock
    instrument: str = ""
    timeframe: str = ""
    violations: int = 0
    _feature_cache: dict[str, object] = field(default_factory=dict, repr=False)

    @property
    def as_of(self) -> str | None:
        return self.clock.current_ts

    @property
    def index(self) -> int:
        return self.clock.index

    def current(self) -> Bar:
        bar = self.clock.current_bar
        if bar is None:
            self.violations += 1
            raise CausalityViolation("No current bar before clock starts")
        return bar

    def history(self, window: int) -> list[Bar]:
        return self.clock.window(window)

    def closes(self, window: int) -> list[float]:
        return self.clock.closes(window)

    def observe(self, at_index: int) -> Bar:
        return self.clock.observe(at_index)

    def bar_at_or_before(self, ts: str) -> Bar | None:
        """Return the latest visible bar with ts <= requested (causal)."""
        if self.clock.index < 0:
            return None
        as_of = self.clock.current_ts
        assert as_of is not None
        if compare_ts(ts, as_of) > 0:
            self.violations += 1
            raise CausalityViolation(
                f"MarketView refused future timestamp {ts} (as_of={as_of})"
            )
        chosen: Bar | None = None
        for i in range(self.clock.index + 1):
            bar = self.clock.bars[i]
            if compare_ts(bar.ts, ts) <= 0:
                chosen = bar
            else:
                break
        return chosen

    def visible_bars(self) -> list[Bar]:
        """Copy of bars visible at the current clock (never future)."""
        if self.clock.index < 0:
            return []
        return [self.clock.bars[i] for i in range(self.clock.index + 1)]

    def feature(self, name: str, *, window: int | None = None, period: int | None = None) -> object:
        """Deterministic causal feature (delegates to FeatureEngine in T2).

        Legacy aliases: ``close``, ``closes``, ``return`` remain supported.
        Cache entries are bound to the current simulation index/as_of so a
        reused view cannot return a prior bar's feature after the clock advances.
        """
        p = period if period is not None else window
        key = f"{name}:{p}:{self.index}:{self.as_of}"
        if key in self._feature_cache:
            return self._feature_cache[key]
        if name == "close":
            value: object = self.current().close
        elif name == "closes":
            if p is None or p < 1:
                raise ValueError("closes feature requires window/period >= 1")
            value = self.closes(int(p))
        else:
            from .features import FeatureEngine

            if self.as_of is None:
                self.violations += 1
                raise CausalityViolation("No feature before clock starts")
            # Use all visible bars so indicators have full causal history.
            bars = self.visible_bars()
            engine = FeatureEngine()
            feat_name = "return" if name == "return" else name
            result = engine.compute(bars, feat_name, as_of=self.as_of, period=p)
            if name == "return" and result.value is not None:
                value = result.value
            else:
                value = result
        self._feature_cache[key] = value
        return value

    def market_state(self, **kwargs: object):
        """Build a deterministic MarketState from this causal view."""
        from .market_state import build_market_state

        return build_market_state(self, **kwargs)  # type: ignore[arg-type]

    def public_dict(self) -> dict:
        cur = self.clock.current_bar
        return {
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "as_of": self.as_of,
            "index": self.index,
            "visible_bar_count": max(0, self.index + 1),
            "current": cur.public_dict() if cur else None,
            "violations": self.violations + self.clock.violations,
            "truth": {
                "future_bars_hidden": True,
                "agents_must_use_market_view": True,
            },
        }


def assert_no_future(timestamps: Sequence[str], clock_ts: str) -> None:
    """Fail if any timestamp is strictly after the clock (datetime-aware)."""
    assert_no_future_ts(timestamps, clock_ts)
