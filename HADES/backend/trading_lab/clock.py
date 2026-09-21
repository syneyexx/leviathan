"""Simulation Clock and Point-in-Time Data Gateway.

There is exactly one clock per run. Everything an agent or strategy can see goes through
:class:`PointInTimeGateway`, which filters on ``available_at <= clock.now`` and refuses reads
from splits the caller's policy does not own. This is enforced at the data, tool, cache and
retrieval boundary — not in a system prompt.

Speed only changes how fast wall-clock time is consumed by the runner. It never changes the
event order, and it never changes what ``now`` makes visible.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator, Sequence

from trading_lab.bar_store import BarPartitionStore
from trading_lab.calendars import timeframe_seconds
from trading_lab.contracts import (
    MarketEvent,
    Observation,
    SplitName,
    ViewRole,
    utc_iso,
)

MAX_CACHE_ENTRIES = 256


class LookaheadViolation(RuntimeError):
    """Raised when a caller tries to read data that is not available yet."""


class HoldoutIsolationError(RuntimeError):
    """Raised when a development-side caller tries to read a sealed split."""


@dataclass(frozen=True)
class DataAccessPolicy:
    """Who is asking, which splits they own, and which cache namespace they use."""

    role: ViewRole
    allowed_splits: frozenset[SplitName]
    cache_namespace: str
    label: str = ""

    @staticmethod
    def for_agent(namespace: str, splits: Sequence[SplitName] = ("development",)) -> "DataAccessPolicy":
        return DataAccessPolicy(
            role="agent",
            allowed_splits=frozenset(splits),
            cache_namespace=f"agent:{namespace}",
            label="agent view — only data available up to the simulation clock",
        )

    @staticmethod
    def for_evaluator(namespace: str, splits: Sequence[SplitName] = ("development", "validation", "sealed_test")) -> "DataAccessPolicy":
        return DataAccessPolicy(
            role="evaluator",
            allowed_splits=frozenset(splits),
            cache_namespace=f"evaluator:{namespace}",
            label="evaluator view — may judge outcomes, never feeds the active agent",
        )

    @staticmethod
    def for_operator_review(namespace: str) -> "DataAccessPolicy":
        return DataAccessPolicy(
            role="operator_review",
            allowed_splits=frozenset({"development", "validation", "sealed_test", "prospective_paper", "synthetic"}),
            cache_namespace=f"review:{namespace}",
            label="operator hindsight view — explicitly marked, not routed back to the agent",
        )

    @property
    def enforces_clock(self) -> bool:
        return self.role == "agent"


@dataclass
class DatasetBinding:
    """Immutable pairing of an instrument with one dataset version and split."""

    instrument_id: str
    dataset_id: str
    timeframe: str
    split: SplitName = "development"
    data_level: str = "ohlcv"
    availability_delay_seconds: int = 0
    calendar: str = "24x7"
    is_synthetic: bool = False
    checksum: str = ""
    role: str = "primary"


class SimulationClock:
    """Monotonic event-time clock.

    ``now`` is an event time, not wall-clock time. It only ever moves forward within a run;
    going back requires an explicit rewind, which the engine implements by creating a new run
    branch rather than by moving this clock backwards.
    """

    def __init__(self, start: str, *, end: str | None = None) -> None:
        self._now = _normalise(start)
        self._start = self._now
        self._end = _normalise(end) if end else None
        self._steps = 0

    @property
    def now(self) -> str:
        return utc_iso(self._now)

    @property
    def now_dt(self) -> datetime:
        return self._now

    @property
    def start(self) -> str:
        return utc_iso(self._start)

    @property
    def end(self) -> str | None:
        return utc_iso(self._end) if self._end else None

    @property
    def steps(self) -> int:
        return self._steps

    def advance_to(self, moment: str | datetime) -> str:
        target = _normalise(moment)
        if target < self._now:
            raise LookaheadViolation(
                f"clock_cannot_move_backwards: now={utc_iso(self._now)} target={utc_iso(target)}; "
                "use engine rewind, which forks a new run branch"
            )
        if target > self._now:
            self._now = target
            self._steps += 1
        return self.now

    def is_finished(self) -> bool:
        return self._end is not None and self._now >= self._end

    def snapshot(self) -> dict[str, Any]:
        return {"now": self.now, "start": self.start, "end": self.end, "steps": self._steps}

    @classmethod
    def restore(cls, snapshot: dict[str, Any]) -> "SimulationClock":
        clock = cls(snapshot["start"], end=snapshot.get("end"))
        clock._now = _normalise(snapshot["now"])
        clock._steps = int(snapshot.get("steps", 0))
        return clock


@dataclass
class SimulationControl:
    """Playback control. Affects pacing and progress reporting, never event order."""

    state: str = "paused"  # paused | playing | stepping | cancelled | finished
    speed: float = 1.0
    step_budget: int = 0
    max_events_per_ui_frame: int = 250
    events_since_frame: int = field(default=0, repr=False)

    def play(self, speed: float | None = None) -> None:
        if speed is not None:
            self.speed = max(0.1, min(float(speed), 100000.0))
        self.state = "playing"

    def pause(self) -> None:
        if self.state not in {"cancelled", "finished"}:
            self.state = "paused"

    def step(self, count: int = 1) -> None:
        self.step_budget += max(1, int(count))
        if self.state not in {"cancelled", "finished"}:
            self.state = "stepping"

    def cancel(self) -> None:
        self.state = "cancelled"

    def finish(self) -> None:
        self.state = "finished"

    @property
    def cancelled(self) -> bool:
        return self.state == "cancelled"

    @property
    def paused(self) -> bool:
        return self.state == "paused"

    def may_process_event(self) -> bool:
        if self.state == "playing":
            return True
        if self.state == "stepping" and self.step_budget > 0:
            self.step_budget -= 1
            if self.step_budget == 0:
                self.state = "paused"
            return True
        return False

    def wait_to_process(self) -> bool:
        """Block while paused. Returns False if the run was cancelled.

        Jobs start in ``playing`` at maximum speed so experiments and evaluations
        finish without a UI click. Pause, step and a lower speed are operator
        overrides; they never reorder events.
        """
        while True:
            if self.cancelled or self.state == "finished":
                return False
            if self.may_process_event():
                self._pace()
                return True
            time.sleep(0.05)

    def _pace(self) -> None:
        if self.state != "playing" or self.speed >= 10_000:
            return
        time.sleep(min(0.25, 0.002 / max(self.speed, 0.05)))

    def should_emit_frame(self) -> bool:
        """The GUI does not render every historical event."""
        self.events_since_frame += 1
        if self.events_since_frame >= max(1, self.max_events_per_ui_frame):
            self.events_since_frame = 0
            return True
        return False


class PointInTimeGateway:
    """The only read path for market data inside a run.

    Guarantees, all enforced in code:

    - an ``agent`` policy can never receive an event with ``available_at > clock.now``;
    - a caller can never read a split outside its policy's ``allowed_splits``;
    - caches are namespaced per policy **and** per clock instant, so a development read and
      an evaluator read can never share an entry;
    - ``last_observation_at`` records the newest observation actually handed out, which the
      engine uses to guarantee that an order is created strictly after the bar that produced
      the signal.
    """

    def __init__(
        self,
        *,
        bar_store: BarPartitionStore,
        clock: SimulationClock,
        policy: DataAccessPolicy,
        bindings: dict[str, DatasetBinding],
        event_store: Any | None = None,
    ) -> None:
        self.bar_store = bar_store
        self.clock = clock
        self.policy = policy
        self.bindings = dict(bindings)
        self.event_store = event_store
        self._cache: OrderedDict[tuple, Observation] = OrderedDict()
        self._last_observation_at: dict[str, str] = {}
        self._violations: list[str] = []

    # --- guards ------------------------------------------------------------------

    def _binding(self, instrument_id: str) -> DatasetBinding:
        binding = self.bindings.get(instrument_id)
        if binding is None:
            raise KeyError(f"instrument_not_bound_to_dataset:{instrument_id}")
        if binding.split not in self.policy.allowed_splits:
            self._violations.append(f"split_denied:{binding.split}:{instrument_id}")
            raise HoldoutIsolationError(
                f"split_not_available_to_role: split={binding.split} role={self.policy.role}; "
                "sealed data is only readable by an independent evaluator policy"
            )
        return binding

    def _cutoff(self) -> str:
        return self.clock.now

    def _assert_no_future(self, events: Sequence[MarketEvent]) -> None:
        if not self.policy.enforces_clock:
            return
        cutoff = self._cutoff()
        for event in events:
            if event.available_at > cutoff:
                self._violations.append(f"future_event:{event.instrument_id}@{event.available_at}")
                raise LookaheadViolation(
                    f"future_data_blocked: available_at={event.available_at} > clock={cutoff}"
                )

    @property
    def violations(self) -> list[str]:
        return list(self._violations)

    # --- reads -------------------------------------------------------------------

    def observe(self, instrument_id: str, *, lookback: int = 200) -> Observation:
        binding = self._binding(instrument_id)
        cutoff = self._cutoff()
        key = (self.policy.cache_namespace, instrument_id, int(lookback), cutoff, binding.dataset_id)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        events = self.bar_store.read_window(
            instrument_id,
            binding.timeframe,
            available_until=cutoff,
            lookback=max(1, int(lookback)),
        )
        self._assert_no_future(events)
        stale = None
        if events:
            newest = datetime.fromisoformat(events[-1].available_at)
            stale = max(0.0, (self.clock.now_dt - newest).total_seconds())
            self._last_observation_at[instrument_id] = events[-1].available_at
        observation = Observation(
            as_of=cutoff,
            instrument_id=instrument_id,
            timeframe=binding.timeframe,
            dataset_id=binding.dataset_id,
            split=binding.split,
            bars=events,
            data_level=binding.data_level,  # type: ignore[arg-type]
            stale_seconds=stale,
            truncated=len(events) >= max(1, int(lookback)),
        )
        self._cache[key] = observation
        while len(self._cache) > MAX_CACHE_ENTRIES:
            self._cache.popitem(last=False)
        return observation

    def auxiliary_events(self, instrument_id: str, *, kind: str) -> list[dict[str, Any]]:
        """Sparse point-in-time series: corporate actions, funding, news, macro revisions."""
        binding = self._binding(instrument_id)
        if self.event_store is None:
            return []
        rows = self.event_store.dataset_events(
            binding.dataset_id,
            kind=kind,
            available_until=self._cutoff() if self.policy.enforces_clock else None,
        )
        return rows

    def last_observation_at(self, instrument_id: str) -> str | None:
        return self._last_observation_at.get(instrument_id)

    def iter_timeline(
        self,
        *,
        instruments: Sequence[str] | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> Iterator[MarketEvent]:
        """Merge every bound instrument into one chronological availability timeline.

        The engine drives the clock from this. Ordering is by ``available_at`` and then by
        instrument id, so the sequence is deterministic and identical at any playback speed.
        """
        chosen = list(instruments or self.bindings.keys())
        streams: dict[str, Iterator[MarketEvent]] = {}
        heads: dict[str, MarketEvent] = {}
        for instrument_id in chosen:
            binding = self._binding(instrument_id)
            stream = self.bar_store.iter_events(
                instrument_id,
                binding.timeframe,
                start=start,
                end=end,
            )
            streams[instrument_id] = stream
            head = next(stream, None)
            if head is not None:
                heads[instrument_id] = head
        while heads:
            instrument_id = min(heads, key=lambda key: (heads[key].available_at, key))
            event = heads.pop(instrument_id)
            head = next(streams[instrument_id], None)
            if head is not None:
                heads[instrument_id] = head
            yield event

    # --- bookkeeping -------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        return {
            "role": self.policy.role,
            "role_label": self.policy.label,
            "allowed_splits": sorted(self.policy.allowed_splits),
            "enforces_clock": self.policy.enforces_clock,
            "simulation_time": self.clock.now,
            "cache_namespace": self.policy.cache_namespace,
            "cached_entries": len(self._cache),
            "violations": self.violations,
            "bindings": [
                {
                    "instrument_id": binding.instrument_id,
                    "dataset_id": binding.dataset_id,
                    "timeframe": binding.timeframe,
                    "split": binding.split,
                    "data_level": binding.data_level,
                    "is_synthetic": binding.is_synthetic,
                    "checksum": binding.checksum,
                    "availability_delay_seconds": binding.availability_delay_seconds,
                }
                for binding in self.bindings.values()
            ],
        }

    def clear_cache(self) -> None:
        self._cache.clear()


def earliest_order_time(observation: Observation) -> str:
    """The first instant an order derived from ``observation`` may exist.

    A signal computed from a closed bar cannot produce an order timestamped at or before
    that bar's availability. This is the function that closes the look-ahead hole in the
    legacy backtest, where a signal from bar *i*'s close filled at bar *i*'s close.
    """
    last = observation.last
    if last is None:
        return observation.as_of
    available = datetime.fromisoformat(last.available_at)
    return utc_iso(max(available, datetime.fromisoformat(observation.as_of)) + timedelta(seconds=1))


def expected_next_event_time(event: MarketEvent) -> str:
    step = timeframe_seconds(event.timeframe)
    return utc_iso(datetime.fromisoformat(event.event_time) + timedelta(seconds=step))


def _normalise(moment: str | datetime) -> datetime:
    if isinstance(moment, datetime):
        stamp = moment
    else:
        text = str(moment).strip().replace("Z", "+00:00")
        stamp = datetime.fromisoformat(text)
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)


__all__ = [
    "DataAccessPolicy",
    "DatasetBinding",
    "HoldoutIsolationError",
    "LookaheadViolation",
    "PointInTimeGateway",
    "SimulationClock",
    "SimulationControl",
    "earliest_order_time",
    "expected_next_event_time",
]
