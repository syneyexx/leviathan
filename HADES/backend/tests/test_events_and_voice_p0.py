"""P0 event bus: emit_sync notifies subscribers; sequence bootstrap; subscribe seed."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.events import RunEventBus


class EmitSyncSubscriberTests(unittest.IsolatedAsyncioTestCase):
    async def test_emit_sync_reaches_async_subscriber(self) -> None:
        bus = RunEventBus(maxlen=100)
        queue = await bus.subscribe("run_a")
        event = bus.emit_sync("run_a", "step_started", {"step_id": "s1"})
        self.assertEqual(bus.history("run_a")[-1].event_id, event.event_id)
        got = await asyncio.wait_for(queue.get(), timeout=1.0)
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.event_id, event.event_id)
        self.assertEqual(queue.qsize(), 0)
        await bus.unsubscribe("run_a", queue)

    async def test_emit_sync_from_worker_thread_reaches_waiting_subscriber(self) -> None:
        bus = RunEventBus(maxlen=100)
        queue = await bus.subscribe("run_threaded")
        loop = asyncio.get_running_loop()
        previous_debug = loop.get_debug()
        loop.set_debug(True)
        waiter = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        try:
            event = await asyncio.to_thread(
                bus.emit_sync,
                "run_threaded",
                "step_started",
                {"step_id": "worker"},
            )
            got = await asyncio.wait_for(waiter, timeout=1.0)
            self.assertIsNotNone(got)
            assert got is not None
            self.assertEqual(got.event_id, event.event_id)
            self.assertEqual(got.sequence, event.sequence)
        finally:
            if not waiter.done():
                waiter.cancel()
            await bus.unsubscribe("run_threaded", queue)
            loop.set_debug(previous_debug)

    async def test_subscribe_seeds_history_without_gap(self) -> None:
        bus = RunEventBus(maxlen=100)
        bus.emit_sync("run_b", "step_started", {"n": 1})
        bus.emit_sync("run_b", "step_completed", {"n": 2})
        queue = await bus.subscribe("run_b", after_sequence=0)
        first = await asyncio.wait_for(queue.get(), timeout=1.0)
        second = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert first is not None and second is not None
        self.assertEqual(first.sequence, 1)
        self.assertEqual(second.sequence, 2)
        await bus.unsubscribe("run_b", queue)

    def test_sequence_bootstrap_after_restart(self) -> None:
        bus = RunEventBus(maxlen=100)
        bus.set_sequence_bootstrap(lambda _run_id: 5)
        event = bus.emit_sync("run_c", "step_started", {})
        self.assertEqual(event.sequence, 6)


class VoiceProviderSelectionTests(unittest.TestCase):
    def test_resolve_voicestudio_from_tts_provider(self) -> None:
        from voice.providers import resolve_tts_provider_id

        self.assertEqual(resolve_tts_provider_id({"tts_provider": "voicestudio"}), "voicestudio")
        self.assertEqual(resolve_tts_provider_id({"voice_tts_provider": "piper"}), "piper")
        self.assertEqual(resolve_tts_provider_id({"voice_tts_provider": "browser"}), "browser")

    def test_synthesize_response_segments_does_not_force_piper_literal(self) -> None:
        src = (Path(__file__).resolve().parents[1] / "voice" / "runtime.py").read_text(encoding="utf-8")
        self.assertNotIn('"voice_tts_provider": "piper"', src)
        self.assertIn("resolve_tts_provider_id", src)


if __name__ == "__main__":
    unittest.main()
