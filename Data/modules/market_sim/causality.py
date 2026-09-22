"""Strict causality clock — no future bar access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .types import Bar, CausalityViolation


@dataclass
class SimulationClock:
    """Single source of truth for simulated time.

    At bar index i, only bars[0..i] inclusive are observable.
    Any attempt to read index > i fails hard.
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


def assert_no_future(timestamps: Sequence[str], clock_ts: str) -> None:
    """Fail if any timestamp is strictly after the clock."""
    for ts in timestamps:
        if ts > clock_ts:
            raise CausalityViolation(f"Event {ts} is after clock {clock_ts}")
