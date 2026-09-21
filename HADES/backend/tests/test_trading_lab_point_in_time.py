"""Point-in-time integrity: the clock, the gateway and split isolation.

Verification note (2026-09-17): VERIFIED_ON_HOST via
`python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v`
on Linux Cloud Agent (Python 3.12). See docs/TRADING_LAB.md §8 and docs/CURRENT_STATUS.md.
"""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_lab.bar_store import BarPartitionStore
from trading_lab.clock import (
    DataAccessPolicy,
    DatasetBinding,
    HoldoutIsolationError,
    LookaheadViolation,
    PointInTimeGateway,
    SimulationClock,
    earliest_order_time,
)
from trading_lab.contracts import MarketEvent

INSTRUMENT = "crypto_spot:test:BTCUSDT"


def bars(count: int, *, delay_seconds: int = 0, start: str = "2020-01-01T00:00:00+00:00") -> list[MarketEvent]:
    first = datetime.fromisoformat(start)
    events = []
    for index in range(count):
        moment = first + timedelta(hours=index)
        price = 100.0 + index
        events.append(
            MarketEvent(
                instrument_id=INSTRUMENT,
                timeframe="1h",
                event_time=moment.isoformat(),
                available_at=(moment + timedelta(seconds=delay_seconds)).isoformat(),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price + 0.5,
                volume=10.0,
            )
        )
    return events


class SimulationClockTest(unittest.TestCase):
    def test_clock_only_moves_forward(self) -> None:
        clock = SimulationClock("2020-01-01T00:00:00+00:00")
        clock.advance_to("2020-01-01T05:00:00+00:00")
        self.assertEqual(clock.now, "2020-01-01T05:00:00+00:00")
        with self.assertRaises(LookaheadViolation):
            clock.advance_to("2020-01-01T04:00:00+00:00")

    def test_snapshot_round_trip_preserves_position(self) -> None:
        clock = SimulationClock("2020-01-01T00:00:00+00:00", end="2020-02-01T00:00:00+00:00")
        clock.advance_to("2020-01-10T00:00:00+00:00")
        restored = SimulationClock.restore(clock.snapshot())
        self.assertEqual(restored.now, clock.now)
        self.assertEqual(restored.end, clock.end)


class PointInTimeGatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = BarPartitionStore(self._tmp.name)
        self.events = bars(48, delay_seconds=60)
        self.store.write(INSTRUMENT, "1h", self.events)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def gateway(self, policy: DataAccessPolicy, *, now: str, split: str = "development") -> PointInTimeGateway:
        return PointInTimeGateway(
            bar_store=self.store,
            clock=SimulationClock(now),
            policy=policy,
            bindings={
                INSTRUMENT: DatasetBinding(
                    instrument_id=INSTRUMENT,
                    dataset_id="ds_test",
                    timeframe="1h",
                    split=split,
                    availability_delay_seconds=60,
                )
            },
        )

    def test_agent_never_sees_data_published_after_the_clock(self) -> None:
        gateway = self.gateway(DataAccessPolicy.for_agent("run1"), now="2020-01-01T05:00:00+00:00")
        observation = gateway.observe(INSTRUMENT, lookback=100)
        self.assertTrue(observation.bars, "the agent must still see the already published history")
        for event in observation.bars:
            self.assertLessEqual(event.available_at, "2020-01-01T05:00:00+00:00")
        # The 05:00 bar is only available at 05:01, so it must be withheld.
        self.assertEqual(observation.bars[-1].event_time, "2020-01-01T04:00:00+00:00")

    def test_availability_delay_is_respected_not_event_time(self) -> None:
        gateway = self.gateway(DataAccessPolicy.for_agent("run1"), now="2020-01-01T04:00:30+00:00")
        observation = gateway.observe(INSTRUMENT, lookback=100)
        self.assertEqual(observation.bars[-1].event_time, "2020-01-01T03:00:00+00:00")

    def test_sealed_split_is_closed_to_an_agent_and_open_to_an_evaluator(self) -> None:
        agent = self.gateway(DataAccessPolicy.for_agent("run1"), now="2020-01-02T00:00:00+00:00", split="sealed_test")
        with self.assertRaises(HoldoutIsolationError):
            agent.observe(INSTRUMENT)
        evaluator = self.gateway(
            DataAccessPolicy.for_evaluator("report1"), now="2020-01-02T00:00:00+00:00", split="sealed_test"
        )
        self.assertTrue(evaluator.observe(INSTRUMENT).bars)

    def test_future_events_raise_instead_of_being_returned(self) -> None:
        gateway = self.gateway(DataAccessPolicy.for_agent("run1"), now="2020-01-01T02:00:00+00:00")
        future = bars(1, start="2030-01-01T00:00:00+00:00")
        with self.assertRaises(LookaheadViolation):
            gateway._assert_no_future(future)
        self.assertTrue(gateway.violations)

    def test_caches_are_isolated_per_policy(self) -> None:
        agent = self.gateway(DataAccessPolicy.for_agent("run1"), now="2020-01-01T05:00:00+00:00")
        evaluator = self.gateway(DataAccessPolicy.for_evaluator("run1"), now="2020-01-01T05:00:00+00:00")
        self.assertNotEqual(agent.policy.cache_namespace, evaluator.policy.cache_namespace)
        agent.observe(INSTRUMENT, lookback=10)
        evaluator.observe(INSTRUMENT, lookback=10)
        self.assertEqual(len(agent._cache), 1)
        self.assertEqual(len(evaluator._cache), 1)

    def test_order_time_is_strictly_after_the_observation(self) -> None:
        gateway = self.gateway(DataAccessPolicy.for_agent("run1"), now="2020-01-01T05:00:00+00:00")
        observation = gateway.observe(INSTRUMENT, lookback=10)
        self.assertGreaterEqual(earliest_order_time(observation), observation.bars[-1].available_at)


class BarStoreTest(unittest.TestCase):
    def test_partitions_are_per_year_and_updates_do_not_destroy_other_years(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = BarPartitionStore(tmp)
            store.write(INSTRUMENT, "1h", bars(24, start="2018-01-01T00:00:00+00:00"))
            store.write(INSTRUMENT, "1h", bars(24, start="2019-01-01T00:00:00+00:00"))
            self.assertEqual(store.count(INSTRUMENT, "1h"), 48)
            self.assertEqual(len(store.partition_names(INSTRUMENT, "1h")), 2)
            checksum = store.checksum(INSTRUMENT, "1h")
            self.assertEqual(checksum, store.checksum(INSTRUMENT, "1h"), "checksums must be stable")

    def test_read_window_returns_chronological_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = BarPartitionStore(tmp)
            store.write(INSTRUMENT, "1h", bars(200))
            window = store.read_window(
                INSTRUMENT, "1h", available_until="2020-01-05T00:00:00+00:00", lookback=10
            )
            self.assertEqual(len(window), 10)
            times = [event.event_time for event in window]
            self.assertEqual(times, sorted(times))


if __name__ == "__main__":  # pragma: no cover - manual execution only
    unittest.main()
