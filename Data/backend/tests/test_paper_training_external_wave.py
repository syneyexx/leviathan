"""Architecture regression — paper/news/charts/training externalization wave."""

from __future__ import annotations

import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.modules.execution.builtins import build_default_catalog
from Data.modules.jobs.runtime import EXTERNAL_WORKER_CAPABILITIES
from Data.modules.training.env_policy import build_trainer_child_env
from Data.modules.training.execution_gate import (
    allow_trainer_ownership,
    production_requires_external,
)
from Data.modules.training.supervisor import resolve_resume_checkpoint_path
from Data.modules.workers.pools import POOL_CATALOG, pool_for_capability


class TrainingLifecycleArchitectureTests(unittest.TestCase):
    def test_training_capabilities_routed_to_training_control(self) -> None:
        caps = (
            "training.control",
            "training.integrity.verify",
            "training.checkpoint.verify",
            "training.dataset.hash",
        )
        for cap in caps:
            self.assertEqual(pool_for_capability(cap), "training_control", msg=cap)
            self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)
            self.assertNotEqual(pool_for_capability(cap), "general")

    def test_training_control_pool_is_singleton(self) -> None:
        pool = POOL_CATALOG["training_control"]
        self.assertEqual(pool.default_count, 1)
        self.assertEqual(pool.max_count, 1)
        self.assertIn("GPU_EXCLUSIVE", pool.resource_classes)
        self.assertIn("IO_HEAVY", pool.resource_classes)
        self.assertIn("CPU_HEAVY", pool.resource_classes)

    def test_control_handler_supervises_full_lifetime(self) -> None:
        import Data.modules.workers.entrypoints.training_control as ep

        src = inspect.getsource(ep)
        self.assertIn("execute_control_start", src)
        self.assertIn("full_trainer_supervision", src)
        self.assertIn("supervision", src)
        # Must complete only after supervision outcome is known.
        self.assertIn("JobState.COMPLETED", src)
        self.assertIn("JobState.CANCELLED", src)

    def test_launcher_uses_scrubbed_env(self) -> None:
        from Data.modules.training.launcher import TrainingLauncher

        src = inspect.getsource(TrainingLauncher.spawn)
        self.assertIn("build_trainer_child_env", src)
        self.assertNotIn("os.environ.copy()", src)

    def test_trainer_env_redacts_secrets(self) -> None:
        base = {
            "PATH": "/usr/bin",
            "CUDA_VISIBLE_DEVICES": "0",
            "OPENAI_API_KEY": "sk-secret",
            "ALPACA_API_KEY_ID": "AKIA",
            "ALPACA_API_SECRET_KEY": "secret",
            "GITHUB_TOKEN": "ghp_x",
            "HF_HUB_OFFLINE": "0",
            "TORCH_HOME": "/tmp/torch",
        }
        env = build_trainer_child_env(base=base)
        self.assertEqual(env.get("PATH"), "/usr/bin")
        self.assertEqual(env.get("CUDA_VISIBLE_DEVICES"), "0")
        self.assertEqual(env.get("TORCH_HOME"), "/tmp/torch")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("ALPACA_API_KEY_ID", env)
        self.assertNotIn("ALPACA_API_SECRET_KEY", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        # Offline defaults for production training.
        self.assertEqual(env.get("HF_HUB_OFFLINE"), "1")
        self.assertEqual(env.get("TRANSFORMERS_OFFLINE"), "1")

    def test_resume_checkpoint_path_directory_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ckpt_dir = Path(tmp) / "checkpoint-cancel"
            ckpt_dir.mkdir()
            # Directory → use as-is (not parent).
            self.assertEqual(resolve_resume_checkpoint_path(ckpt_dir), str(ckpt_dir))
            state = ckpt_dir / "state.json"
            state.write_text("{}", encoding="utf-8")
            # File → parent directory.
            self.assertEqual(resolve_resume_checkpoint_path(state), str(ckpt_dir))

    def test_production_api_cannot_own_trainer_when_externalized(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "LEVIATHAN_WORKERS_EXTERNALIZE_API": "1",
                "LEVIATHAN_TRAINING_ALLOW_INLINE_TEST": "0",
                "PYTEST_CURRENT_TEST": "",
            },
            clear=False,
        ):
            # Force non-pytest gate by patching pytest_session_active.
            with mock.patch(
                "Data.modules.training.execution_gate.pytest_session_active",
                return_value=False,
            ):
                with mock.patch(
                    "Data.modules.execution.workload.running_in_worker_process",
                    return_value=False,
                ):
                    self.assertTrue(production_requires_external())
                    self.assertFalse(allow_trainer_ownership())

    def test_integrity_and_hash_not_gpu_exclusive_by_default(self) -> None:
        from Data.modules.training.service import TrainingService

        src = inspect.getsource(TrainingService.enqueue_integrity_verify)
        self.assertIn('resource_class="IO_HEAVY"', src)
        src2 = inspect.getsource(TrainingService.enqueue_dataset_hash)
        self.assertIn('resource_class="IO_HEAVY"', src2)
        src3 = inspect.getsource(TrainingService.start_job)
        # Production training still uses GPU_EXCLUSIVE; fixture uses CPU_HEAVY.
        self.assertIn("GPU_EXCLUSIVE", src3)
        self.assertIn("CPU_HEAVY", src3)
        self.assertIn("is_fixture", src3)

    def test_catalog_registers_new_training_caps(self) -> None:
        catalog = build_default_catalog()
        for cap in (
            "training.control",
            "training.integrity.verify",
            "training.checkpoint.verify",
            "training.dataset.hash",
        ):
            self.assertIsNotNone(catalog.get(cap), msg=cap)


class PaperNewsChartArchitectureTests(unittest.TestCase):
    def test_market_sim_caps_routed(self) -> None:
        caps = {
            "market_sim.news.poll": "market_sim",
            "market_sim.autonomous_step": "market_sim",
            "market_sim.paper_forward_step": "market_sim",
            "market_sim.chart.render_batch": "market_sim",
            "market_sim.portfolio_tick": "market_sim",
            "provider.alpaca.paper": "provider_io",
            "provider.market.fetch": "provider_io",
        }
        for cap, pool in caps.items():
            self.assertEqual(pool_for_capability(cap), pool, msg=cap)
            self.assertIn(cap, EXTERNAL_WORKER_CAPABILITIES)

    def test_no_chart_worker_pool(self) -> None:
        self.assertNotIn("chart", POOL_CATALOG)
        self.assertNotIn("chart_render", POOL_CATALOG)
        self.assertEqual(pool_for_capability("market_sim.chart.render_batch"), "market_sim")

    def test_autonomous_step_route_enqueues(self) -> None:
        from Data.backend.routes import market_sim as routes

        src = inspect.getsource(routes)
        self.assertIn("request_autonomous_step", src)

    def test_market_sim_worker_handles_new_caps(self) -> None:
        import Data.modules.workers.entrypoints.market_sim as ep

        src = inspect.getsource(ep)
        for needle in (
            "market_sim.autonomous_step",
            "market_sim.paper_forward_step",
            "market_sim.chart.render_batch",
            "market_sim.news.poll",
        ):
            self.assertIn(needle, src)

    def test_paper_quotes_fail_closed_to_provider_io(self) -> None:
        from Data.modules.market_sim.service import MarketSimControlPlane

        src = inspect.getsource(MarketSimControlPlane._fetch_paper_quote)
        self.assertIn("provider_io", src)
        self.assertIn("PROVIDER_EXECUTION_UNAVAILABLE", src)
        self.assertIn("refusing Control Plane quote fallback", src)

    def test_news_schedule_helper_exists(self) -> None:
        from Data.modules.market_sim.orchestra.service import TradingOrchestraService

        self.assertTrue(hasattr(TradingOrchestraService, "ensure_news_poll_schedule"))
        src = inspect.getsource(TradingOrchestraService.ensure_news_poll_schedule)
        self.assertIn("market_sim.news.poll", src)
        self.assertIn("ScheduleTargetKind.JOB", src)

    def test_chart_batch_continuation_bounded(self) -> None:
        from Data.modules.market_sim.chart_batch import (
            DEFAULT_CHART_BATCH_LIMIT,
            MAX_CHART_BATCH_LIMIT,
            clamp_batch_limit,
            render_chart_batch_slice,
        )

        self.assertEqual(clamp_batch_limit(None), DEFAULT_CHART_BATCH_LIMIT)
        self.assertEqual(clamp_batch_limit(10_000), MAX_CHART_BATCH_LIMIT)
        self.assertLessEqual(MAX_CHART_BATCH_LIMIT, 100)

        # Causality: future bar hard-fails one chart without aborting batch identity.
        bars = [
            {"ts": "2024-01-01T00:00:00Z", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
            {"ts": "2024-01-02T00:00:00Z", "open": 1.5, "high": 3, "low": 1, "close": 2, "volume": 10},
        ]
        specs = [
            {
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "as_of": "2024-01-01T12:00:00Z",
                "start_ts": "2024-01-01T00:00:00Z",
                "end_ts": "2024-01-01T12:00:00Z",
                "bars": bars,
            },
            {
                "symbol": "ETHUSDT",
                "timeframe": "1h",
                "as_of": "2024-01-01T12:00:00Z",
                "start_ts": "2024-01-01T00:00:00Z",
                "end_ts": "2024-01-01T12:00:00Z",
                "bars": [bars[0]],
            },
        ]
        manifest = render_chart_batch_slice(specs, limit=10)
        self.assertEqual(manifest["total"], 2)
        self.assertTrue(manifest["complete"])
        # First spec has a future bar relative to as_of → failure; second succeeds.
        self.assertGreaterEqual(manifest["failed"] + manifest["rendered"], 1)

    def test_live_money_still_blocked(self) -> None:
        from Data.modules.market_sim.trading_live_guard import LiveTradingGuard

        guard = LiveTradingGuard()
        status = guard.public_status()
        self.assertEqual(status.get("LIVE_TRADING_AVAILABLE"), "BLOCKED")
        with self.assertRaises(Exception):
            guard.place_live_order(symbol="BTCUSDT", side="BUY", qty=1)


class CheckpointDatasetHashUnitTests(unittest.TestCase):
    def test_partial_checkpoint_not_resumable(self) -> None:
        from Data.modules.training.checkpoint_verify import verify_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            partial = Path(tmp) / "checkpoint-1.partial"
            partial.mkdir()
            (partial / "weights.bin").write_bytes(b"abc")
            report = verify_checkpoint(partial)
            self.assertEqual(report["state"], "INCOMPLETE")
            self.assertFalse(report["resumable"])

    def test_valid_fixture_checkpoint(self) -> None:
        from Data.modules.training.checkpoint_verify import verify_checkpoint

        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "checkpoint-5"
            ckpt.mkdir()
            (ckpt / "state.json").write_text('{"step": 5}', encoding="utf-8")
            report = verify_checkpoint(ckpt)
            self.assertEqual(report["state"], "VALID")
            self.assertTrue(report["resumable"])

    def test_dataset_hash_streaming_and_change_detect(self) -> None:
        from Data.modules.training.dataset_hash import hash_training_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            root.mkdir()
            (root / "a.txt").write_text("hello", encoding="utf-8")
            (root / "b.txt").write_text("world", encoding="utf-8")
            report = hash_training_dataset(root)
            self.assertFalse(report["changed"])
            self.assertEqual(report["file_count"], 2)
            self.assertTrue(report["content_hash"])
            # Deterministic order.
            report2 = hash_training_dataset(root)
            self.assertEqual(report["content_hash"], report2["content_hash"])


if __name__ == "__main__":
    unittest.main()
