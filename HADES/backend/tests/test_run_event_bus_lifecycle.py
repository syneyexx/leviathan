"""RunEventBus evicts terminal run history after a reconnect grace period."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.events import RunEventBus


class RunEventBusLifecycleTests(unittest.TestCase):
    def test_terminal_runs_compact_after_grace(self) -> None:
        bus = RunEventBus(maxlen=1000, terminal_grace_s=0.01, compact_keep=2)
        for i in range(40):
            run_id = f"run_{i}"
            for n in range(25):
                bus.emit_sync(run_id, "stream_delta", {"n": n}, provisional=True)
            bus.emit_sync(run_id, "final_outcome", {"ok": True})
        live = bus.stats()
        self.assertEqual(live["runs"], 40)
        self.assertGreater(live["events"], 40)
        removed = bus.reap(now=1e12, force=True)
        self.assertEqual(removed, 40)
        after = bus.stats()
        self.assertLessEqual(after["events"], 40 * 8)
        history = bus.history("run_0")
        self.assertTrue(history)
        self.assertEqual(history[-1].type, "final_outcome")
        # Sequence remains so reconnect can still see the terminal event.
        self.assertGreaterEqual(history[-1].sequence, 1)

    def test_active_subscriber_blocks_eviction(self) -> None:
        bus = RunEventBus(maxlen=100, terminal_grace_s=0.01, compact_keep=1)

        async def _run() -> None:
            import asyncio

            queue = await bus.subscribe("live")
            bus.emit_sync("live", "final_outcome", {})
            self.assertEqual(bus.reap(now=1e12, force=True), 0)
            self.assertGreaterEqual(len(bus.history("live")), 1)
            await bus.unsubscribe("live", queue)

        import asyncio

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
