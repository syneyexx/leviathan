"""Playback control, rewind-branch selection and pause honesty.

Verification note (2026-09-17): VERIFIED_ON_HOST via
`python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v`
on Linux Cloud Agent (Python 3.12). See docs/TRADING_LAB.md §8 and docs/CURRENT_STATUS.md.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_lab.clock import SimulationControl
from trading_lab.engine import select_checkpoint_for_rewind


class SimulationControlTest(unittest.TestCase):
    def test_cancelled_and_paused_are_readable_properties(self) -> None:
        control = SimulationControl()
        self.assertTrue(control.paused)
        self.assertFalse(control.cancelled)
        control.play(100_000)
        self.assertFalse(control.paused)
        control.cancel()
        self.assertTrue(control.cancelled)
        self.assertFalse(control.paused)

    def test_step_budget_pauses_after_the_requested_events(self) -> None:
        control = SimulationControl()
        control.step(2)
        self.assertTrue(control.may_process_event())
        self.assertTrue(control.may_process_event())
        self.assertTrue(control.paused)
        self.assertFalse(control.may_process_event())

    def test_wait_to_process_returns_false_when_cancelled(self) -> None:
        control = SimulationControl()
        control.cancel()
        self.assertFalse(control.wait_to_process())

    def test_high_speed_does_not_sleep(self) -> None:
        control = SimulationControl()
        control.play(100_000)
        self.assertTrue(control.may_process_event())
        control._pace()


class RewindSelectionTest(unittest.TestCase):
    def test_picks_the_nearest_checkpoint_at_or_before_the_requested_time(self) -> None:
        checkpoints = [
            ("2020-01-01T00:00:00+00:00", {"last_event_time": "2020-01-01T00:00:00+00:00", "n": 1}),
            ("2020-01-02T00:00:00+00:00", {"last_event_time": "2020-01-02T00:00:00+00:00", "n": 2}),
            ("2020-01-04T00:00:00+00:00", {"last_event_time": "2020-01-04T00:00:00+00:00", "n": 4}),
        ]
        chosen = select_checkpoint_for_rewind("2020-01-03T12:00:00+00:00", checkpoints)
        self.assertEqual(chosen["n"], 2)

    def test_refuses_when_nothing_exists_at_or_before_the_requested_time(self) -> None:
        checkpoints = [("2020-02-01T00:00:00+00:00", {"n": 1})]
        self.assertIsNone(select_checkpoint_for_rewind("2020-01-01T00:00:00+00:00", checkpoints))

    def test_falls_back_to_the_latest_run_checkpoint_when_it_is_not_in_the_future(self) -> None:
        latest = {"last_event_time": "2020-01-10T00:00:00+00:00", "n": "latest"}
        chosen = select_checkpoint_for_rewind("2020-01-12T00:00:00+00:00", [], latest=latest)
        self.assertEqual(chosen["n"], "latest")

    def test_does_not_use_a_latest_checkpoint_from_after_the_requested_time(self) -> None:
        latest = {"last_event_time": "2020-02-01T00:00:00+00:00"}
        self.assertIsNone(select_checkpoint_for_rewind("2020-01-01T00:00:00+00:00", [], latest=latest))

    def test_empty_payloads_are_ignored(self) -> None:
        checkpoints = [("2020-01-01T00:00:00+00:00", {})]
        self.assertIsNone(select_checkpoint_for_rewind("2020-01-01T00:00:00+00:00", checkpoints))


if __name__ == "__main__":  # pragma: no cover - manual execution only
    unittest.main()
