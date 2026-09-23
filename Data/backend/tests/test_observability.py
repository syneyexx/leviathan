"""Observability Round 1 — durable events, redaction, operator, stream."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from Data.modules.observability import (
    ObservabilityHub,
    build_default_operator_registry,
    redact_payload,
)
from Data.modules.observability.event_store import EventStore
from Data.modules.observability.operator import OperatorCommandRegistry
from Data.modules.metrics import TimeSeriesStore


class RedactionTests(unittest.TestCase):
    def test_secret_key_redacted(self) -> None:
        payload = {
            "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
            "nested": {"password": "hunter2", "ok": 1},
            "note": "bearer FAKESECRET_e1f2g3h4i5j6k7l8m9n0",
        }
        out = redact_payload(payload)
        self.assertEqual(out["api_key"], "[REDACTED]")
        self.assertEqual(out["nested"]["password"], "[REDACTED]")
        self.assertEqual(out["nested"]["ok"], 1)
        self.assertNotIn("ABCDEF", out["note"])
        self.assertIn("[REDACTED]", out["note"])


class EventStoreTests(unittest.TestCase):
    def test_append_query_retention_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "obs.sqlite", max_rows=100, retention_days=14)
            store.initialize()
            import time

            now = time.time() * 1000
            for i in range(5):
                store.append(
                    {
                        "event_id": f"e{i}",
                        "created_at_ms": now + i,
                        "level": "INFO" if i % 2 == 0 else "ERROR",
                        "category": "test",
                        "subsystem": "test",
                        "name": "tick",
                        "message": f"msg-{i}",
                        "payload": {"i": i, "token": "secret-value-should-stay-caller-redacted"},
                        "source": "unit",
                        "correlation_id": "corr-1" if i > 2 else None,
                    }
                )
            latest = store.latest_sequence()
            self.assertEqual(latest, 5)
            newest = store.query(limit=2, newest_first=True)
            self.assertEqual(len(newest), 2)
            self.assertEqual(newest[0]["sequence"], 5)
            after = store.get_after(2, limit=10)
            self.assertEqual([e["sequence"] for e in after], [3, 4, 5])
            errors = store.query(level="ERROR", limit=10)
            self.assertTrue(all(e["level"] == "ERROR" for e in errors))
            corr = store.query(correlation_id="corr-1", limit=10)
            self.assertEqual(len(corr), 2)


class ObservabilityHubTests(unittest.TestCase):
    def test_emit_and_recent(self) -> None:
        hub = ObservabilityHub(capacity=20, persist=False)
        hub.emit("chat", "started", payload={"n": 1})
        hub.emit("capability", "execute", payload={"id": "file.read"}, level="warn")
        snap = hub.snapshot()
        self.assertEqual(snap["buffered"], 2)
        self.assertEqual(snap["counters"]["chat.started"], 1)
        recent = hub.recent(limit=10, category="capability")
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].name, "execute")
        self.assertEqual(recent[0].level, "WARNING")
        self.assertTrue(recent[0].public_dict()["payload"]["id"])

    def test_durable_emit_redacts_and_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hub = ObservabilityHub(capacity=50, db_path=Path(tmp) / "db.sqlite")
            e1 = hub.emit(
                "mcp",
                "call",
                level="success",
                message="mcp tool ok",
                payload={"api_key": "sk-abcdefghijklmnopqrstuvwxyz", "tool": "search"},
                correlation_id="c-9",
                mcp_server_id="srv-1",
                duration_ms=12.5,
                success=True,
            )
            self.assertEqual(e1.level, "SUCCESS")
            self.assertEqual(e1.payload.get("api_key"), "[REDACTED]")
            self.assertGreaterEqual(e1.sequence, 1)
            hist = hub.query_history(limit=10, correlation_id="c-9")
            self.assertEqual(len(hist), 1)
            self.assertEqual(hist[0]["payload"]["api_key"], "[REDACTED]")
            after = hub.events_after(0, limit=10)
            self.assertEqual(len(after), 1)

    def test_success_level_normalization(self) -> None:
        hub = ObservabilityHub(capacity=10, persist=False)
        e = hub.emit("job", "completed", level="ok", success=True)
        self.assertEqual(e.level, "SUCCESS")


class OperatorRegistryTests(unittest.TestCase):
    def test_help_and_unknown_and_shell_rejection(self) -> None:
        reg = OperatorCommandRegistry()
        reg.register("ping", lambda args: {"pong": True}, help_text="ping")
        help_result = reg.execute("help")
        self.assertTrue(help_result.ok)
        unknown = reg.execute("rm -rf /")
        self.assertFalse(unknown.ok)
        self.assertIn("unknown_command", unknown.error or "")
        shellish = reg.execute("ping; echo hi")
        self.assertFalse(shellish.ok)

    def test_default_registry_status(self) -> None:
        hub = ObservabilityHub(capacity=20, persist=False)
        hub.emit("console", "boot", level="info")
        reg = build_default_operator_registry(
            deps={"observability": hub, "health_fn": lambda: {"ok": True}}
        )
        result = reg.execute("health")
        self.assertTrue(result.ok)
        events = reg.execute("events 5")
        self.assertTrue(events.ok)
        self.assertGreaterEqual(events.output["count"], 1)


class TimeSeriesTests(unittest.TestCase):
    def test_percentiles_and_missing_not_zero(self) -> None:
        ts = TimeSeriesStore(max_points_per_series=100)
        empty = ts.percentiles("http.request")
        self.assertIsNone(empty["p95"])
        self.assertEqual(empty["count"], 0)
        for v in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
            ts.observe_latency_ms("http.request", float(v))
        stats = ts.percentiles("http.request")
        self.assertEqual(stats["count"], 10)
        self.assertIsNotNone(stats["p50"])
        self.assertGreaterEqual(stats["p95"], stats["p50"])
        hot = ts.hot_paths(limit=5)
        self.assertEqual(hot[0]["name"], "http.request")


class EventStreamBrokerTests(unittest.TestCase):
    def test_publish_and_subscribe(self) -> None:
        from Data.modules.observability.stream import EventStreamBroker

        broker = EventStreamBroker(queue_size=8)

        async def _run() -> list[str]:
            chunks: list[str] = []

            async def reader():
                async for chunk in broker.stream(heartbeat_seconds=0.05):
                    chunks.append(chunk)
                    if "hello" in chunk:
                        break

            task = asyncio.create_task(reader())
            await asyncio.sleep(0.01)
            broker.publish({"sequence": 1, "message": "hello"})
            await asyncio.wait_for(task, timeout=2.0)
            broker.shutdown()
            return chunks

        chunks = asyncio.run(_run())
        self.assertTrue(any("hello" in c for c in chunks))


if __name__ == "__main__":
    unittest.main()
