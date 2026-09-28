"""Architecture regression — voice + MarketSim/market-data externalization wave."""

from __future__ import annotations

import ast
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution import build_default_catalog
from Data.modules.execution.workload import (
    ExecutionWorkloadClass,
    api_may_execute_inline,
    classify_capability,
)
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES
from Data.modules.voice.backends import (
    BackendReadiness,
    FixtureAsrBackend,
    FixtureTtsBackend,
    UnavailableAsrBackend,
    UnavailableTtsBackend,
)
from Data.modules.voice.service import VoiceService
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


VOICE_CAPS = (
    "voice.start_session",
    "voice.transcribe",
    "voice.synthesize",
    "voice.barge_in",
    "voice.preprocess",
    "voice.postprocess",
)

MARKET_DATA_CAPS = (
    "market_sim.data.scan",
    "market_sim.data.import",
    "market_sim.data.validate",
    "market_sim.data.profile",
    "market_sim.data.convert",
    "market_sim.assurance.scan",
)

MARKET_SIM_CAPS = (
    "market_sim.advance",
    "market_sim.gym_episode",
    "market_sim.research_campaign",
    "market_sim.learning_run",
    "market_sim.qualification_run",
    "market_sim.scan_batch",
    "market_sim.portfolio_tick",
)


class VoicePoolRoutingTests(unittest.TestCase):
    def test_voice_pool_is_singleton(self) -> None:
        self.assertIn("voice", POOL_CATALOG)
        defn = POOL_CATALOG["voice"]
        self.assertEqual(defn.default_count, 1)
        self.assertEqual(defn.max_count, 1)
        for cap in VOICE_CAPS:
            self.assertTrue(
                any(cap.startswith(k.rstrip(".")) or cap == k or k.endswith(".") for k in defn.job_kinds)
                or "voice." in defn.job_kinds
            )

    def test_voice_caps_route_to_voice_not_general(self) -> None:
        for cap in VOICE_CAPS:
            self.assertEqual(pool_for_capability(cap), "voice", cap)
            self.assertNotEqual(pool_for_capability(cap), "general", cap)
            self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)

    def test_voice_caps_are_external_required(self) -> None:
        catalog = build_default_catalog()
        for cap in VOICE_CAPS:
            definition = catalog.get(cap)
            self.assertIsNotNone(definition, cap)
            assert definition is not None
            cls = classify_capability(cap, metadata=definition.metadata)
            self.assertEqual(cls, ExecutionWorkloadClass.EXTERNAL_REQUIRED, cap)
            self.assertFalse(
                api_may_execute_inline(
                    cap,
                    metadata=definition.metadata,
                    provider_kind=definition.provider_kind.value,
                ),
                cap,
            )


class VoiceBackendHonestyTests(unittest.TestCase):
    def test_fixture_never_production_ready(self) -> None:
        asr = FixtureAsrBackend()
        tts = FixtureTtsBackend()
        self.assertEqual(asr.readiness(), BackendReadiness.FIXTURE_ONLY)
        self.assertEqual(tts.readiness(), BackendReadiness.FIXTURE_ONLY)
        self.assertFalse(asr.identity().production_capable)
        self.assertFalse(tts.identity().production_capable)

    def test_unavailable_does_not_fabricate(self) -> None:
        asr = UnavailableAsrBackend()
        tts = UnavailableTtsBackend()
        a = asr.transcribe(audio_ref="x.wav")
        t = tts.synthesize(text="hello")
        self.assertEqual(a.get("error_code"), "VOICE_ASR_UNAVAILABLE")
        self.assertEqual(t.get("error_code"), "VOICE_TTS_UNAVAILABLE")
        self.assertNotIn("transcript", a)  # no fabricated transcript key as success

    def test_production_service_unavailable_without_fixture(self) -> None:
        svc = VoiceService(allow_fixture=False)
        status = svc.status()
        self.assertFalse(status.get("production_capable"))
        self.assertIn(status.get("asr_backend"), {"NOT_CONFIGURED", "UNAVAILABLE", "FIXTURE_ONLY"})
        started = svc.start_session(conversation_id="c1")
        self.assertEqual(started.get("status"), "COMPLETED")
        sid = started["session"]["session_id"]
        asr = svc.stream_asr(session_id=sid, audio_ref="/tmp/missing.wav")
        self.assertEqual(asr.get("error_code"), "VOICE_ASR_UNAVAILABLE")
        tts = svc.stream_tts(session_id=sid, text="hello world")
        self.assertEqual(tts.get("error_code"), "VOICE_TTS_UNAVAILABLE")

    def test_fixture_service_barge_in_cancels(self) -> None:
        svc = VoiceService(
            asr_backend=FixtureAsrBackend(),
            tts_backend=FixtureTtsBackend(),
            allow_fixture=True,
        )
        started = svc.start_session()
        sid = started["session"]["session_id"]
        # Start TTS then barge-in mid-flight via cancel_event
        session = svc.get_session(sid)
        assert session is not None
        session.cancel_event.set()
        out = svc.stream_tts(session_id=sid, text="one two three four five")
        self.assertEqual(out.get("status"), "CANCELLED")

    def test_session_lost_after_generation_change(self) -> None:
        svc = VoiceService(allow_fixture=True)
        started = svc.start_session()
        sid = started["session"]["session_id"]
        svc.worker_generation = "other-generation"
        lost = svc.barge_in(sid)
        self.assertEqual(lost.get("error_code"), "VOICE_SESSION_LOST")


class MarketSimPoolRoutingTests(unittest.TestCase):
    def test_market_sim_pool_bounds(self) -> None:
        defn = POOL_CATALOG["market_sim"]
        self.assertEqual(defn.default_count, 1)
        self.assertEqual(defn.max_count, 2)

    def test_market_data_caps_route_to_market_sim(self) -> None:
        for cap in MARKET_DATA_CAPS + MARKET_SIM_CAPS:
            self.assertEqual(pool_for_capability(cap), "market_sim", cap)
            self.assertNotEqual(pool_for_capability(cap), "general", cap)
            self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)
            cls = classify_capability(cap)
            self.assertEqual(cls, ExecutionWorkloadClass.EXTERNAL_REQUIRED, cap)


class StreamingOhlcvTests(unittest.TestCase):
    def test_validate_does_not_call_load_ohlcv(self) -> None:
        from Data.modules.market_sim import ohlcv as ohlcv_mod

        csv = (
            "timestamp,open,high,low,close,volume\n"
            "2024-01-01T00:00:00Z,1,2,0.5,1.5,10\n"
            "2024-01-01T01:00:00Z,1.5,2.5,1,2,11\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "BTCUSDT_1h.csv"
            path.write_text(csv, encoding="utf-8")
            with mock.patch.object(ohlcv_mod, "load_ohlcv", side_effect=AssertionError("load_ohlcv forbidden")):
                result = ohlcv_mod.validate_ohlcv_file(path)
            self.assertTrue(result.ok)
            self.assertEqual(result.bar_count, 2)
            self.assertTrue((result.quality or {}).get("streaming"))

    def test_analyze_bars_streaming_online(self) -> None:
        from Data.modules.market_sim.dataset_pipeline import analyze_bars_streaming
        from Data.modules.market_sim.ohlcv import iter_ohlcv

        csv = (
            "timestamp,open,high,low,close,volume\n"
            "2024-01-01T00:00:00Z,1,2,0.5,1.5,10\n"
            "2024-01-01T01:00:00Z,1.5,2.5,1,2,11\n"
            "2024-01-01T02:00:00Z,2,3,1.5,2.5,12\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x_1h.csv"
            path.write_text(csv, encoding="utf-8")
            report = analyze_bars_streaming(iter_ohlcv(path), timeframe="1h", content_hash="abc")
            self.assertEqual(report.bar_count, 3)
            self.assertIn(report.quality_verdict, {"PASS", "WARN"})


class ArchitectureGuardAstTests(unittest.TestCase):
    def test_voice_route_does_not_call_gateway_execute(self) -> None:
        src = Path("Data/backend/routes/voice.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and (
                (isinstance(n.func, ast.Attribute) and n.func.attr == "execute")
                or (isinstance(n.func, ast.Name) and n.func.id == "execute")
            )
        ]
        # Allow no execution_gateway.execute in production voice route
        for call in calls:
            if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
                self.assertNotEqual(call.func.value.id, "execution_gateway")

    def test_market_sim_data_scan_route_enqueues(self) -> None:
        src = Path("Data/backend/routes/market_sim.py").read_text(encoding="utf-8")
        self.assertIn("enqueue_market_data_scan", src)
        self.assertIn("enqueue_market_data_import", src)
        self.assertIn("enqueue_assurance_scan", src)
        # scan_data must not call service.scan_market_data()
        tree = ast.parse(src)

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.bad = False

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                if node.name == "scan_data":
                    body = ast.dump(node)
                    if "scan_market_data" in body:
                        self.bad = True
                self.generic_visit(node)

        v = Visitor()
        v.visit(tree)
        self.assertFalse(v.bad, "scan_data must not call scan_market_data")

    def test_portfolio_tick_handler_has_cadence_gate(self) -> None:
        src = Path("Data/modules/workers/entrypoints/market_sim.py").read_text(encoding="utf-8")
        self.assertIn("next_tick_at", src)
        self.assertIn("no_hot_self_enqueue_loop", src)
        self.assertIn("market_sim.data.scan", src)
        self.assertIn("market_sim.assurance.scan", src)

    def test_no_process_next_in_voice_entrypoint(self) -> None:
        src = Path("Data/modules/workers/entrypoints/voice.py").read_text(encoding="utf-8")
        self.assertNotIn("process_next", src)


class MarketDataScanSliceTests(unittest.TestCase):
    def test_bounded_deterministic_scan(self) -> None:
        from Data.modules.market_sim.data_store import MarketDataStore
        from Data.modules.market_sim.store import MarketSimStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "markets"
            root.mkdir()
            for i in range(5):
                p = root / f"SYM{i}_1h.csv"
                p.write_text(
                    "timestamp,open,high,low,close,volume\n"
                    f"2024-01-0{i+1}T00:00:00Z,1,2,0.5,1.5,10\n",
                    encoding="utf-8",
                )
            db = Path(tmp) / "market.db"
            store = MarketSimStore(db)
            store.initialize()
            mds = MarketDataStore(store, root)
            first = mds.scan_slice(max_entries=2, deep_validate=True, register=True)
            self.assertEqual(first["processed"], 2)
            self.assertFalse(first["done"])
            second = mds.scan_slice(
                max_entries=10,
                cursor=first["cursor"],
                deep_validate=True,
                register=True,
            )
            self.assertTrue(second["done"])
            # Deterministic order across slices
            all_paths = [s.path for s in first["sources"]] + [s.path for s in second["sources"]]
            self.assertEqual(all_paths, sorted(all_paths))


if __name__ == "__main__":
    unittest.main()
