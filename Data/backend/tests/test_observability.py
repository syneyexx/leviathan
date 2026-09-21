from __future__ import annotations

import unittest

from Data.modules.observability import ObservabilityHub


class ObservabilityHubTests(unittest.TestCase):
    def test_emit_and_recent(self) -> None:
        hub = ObservabilityHub(capacity=20)
        hub.emit("chat", "started", payload={"n": 1})
        hub.emit("capability", "execute", payload={"id": "file.read"}, level="warn")
        snap = hub.snapshot()
        self.assertEqual(snap["buffered"], 2)
        self.assertEqual(snap["counters"]["chat.started"], 1)
        recent = hub.recent(limit=10, category="capability")
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].name, "execute")
        self.assertTrue(recent[0].public_dict()["payload"]["id"])


if __name__ == "__main__":
    unittest.main()
