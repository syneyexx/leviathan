from __future__ import annotations

import asyncio
import unittest

from reasoning.events import RunEventBus


class RunEventBusBackpressureHonestyTests(unittest.TestCase):
    def test_async_terminal_event_signals_resync_when_subscriber_queue_is_full(self) -> None:
        async def _run() -> None:
            bus = RunEventBus(maxlen=1_000)
            queue = await bus.subscribe("run-1")
            for index in range(256):
                await bus.emit(
                    "run-1",
                    "stream_delta",
                    {"index": index},
                    provisional=True,
                )
            terminal = await bus.emit(
                "run-1",
                "final_outcome",
                {"status": "completed"},
                provisional=False,
            )

            events = []
            while not queue.empty():
                events.append(queue.get_nowait())
            marker = events[-1]
            self.assertIsNotNone(marker)
            assert marker is not None
            self.assertEqual(marker.type, "error")
            self.assertTrue(marker.payload.get("resync_required"))
            self.assertEqual(marker.payload.get("missed_event_id"), terminal.event_id)

        asyncio.run(_run())

    def test_provisional_stream_delta_can_still_drop_without_forcing_resync(self) -> None:
        async def _run() -> None:
            bus = RunEventBus(maxlen=1_000)
            queue = await bus.subscribe("run-2")
            for index in range(256):
                await bus.emit("run-2", "stream_delta", {"index": index}, provisional=True)
            await bus.emit("run-2", "stream_delta", {"index": 999}, provisional=True)

            events = []
            while not queue.empty():
                events.append(queue.get_nowait())
            self.assertEqual(len(events), 256)
            self.assertFalse(any(event is not None and event.payload.get("resync_required") for event in events))

        asyncio.run(_run())

    def test_reconnect_seed_overflow_contains_explicit_resync_marker(self) -> None:
        async def _run() -> None:
            bus = RunEventBus(maxlen=1_000)
            for index in range(300):
                await bus.emit("run-3", "step_completed", {"index": index})

            queue = await bus.subscribe("run-3", after_sequence=0)
            events = []
            while not queue.empty():
                events.append(queue.get_nowait())
            marker = events[-1]
            self.assertIsNotNone(marker)
            assert marker is not None
            self.assertEqual(marker.type, "error")
            self.assertTrue(marker.payload.get("resync_required"))
            self.assertEqual(marker.payload.get("reason"), "subscriber_queue_full")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
