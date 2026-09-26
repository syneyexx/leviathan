"""W184–W185 — native market.ohlcv_validate parity + Parquet analytical export."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from Data.backend.migrations import MigrationRunner
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.native_ohlcv import try_native_ohlcv_validate
from Data.modules.market_sim.ohlcv import (
    load_ohlcv,
    storage_format_for_path,
    validate_ohlcv_file,
    write_ohlcv_analytical,
)
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.workers.native_compute import (
    MARKET_OPERATIONS,
    SUPPORTED_OPERATIONS,
    build_task_document,
    resolve_native_binary,
    run_native_task,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "market_data" / "BTCUSDT_1h.csv"


def _maybe_build_binary() -> Path | None:
    existing = resolve_native_binary()
    if existing is not None:
        return existing
    script = Path(__file__).resolve().parents[3] / "scripts" / "build_native_data_plane.py"
    if not script.is_file():
        return None
    cargo = subprocess.run(["cargo", "--version"], capture_output=True, check=False)
    if cargo.returncode != 0:
        return None
    proc = subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    if proc.returncode != 0:
        proc2 = subprocess.run(
            [os.environ.get("PYTHON", "python3"), str(script), "--unlocked"],
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
        )
        if proc2.returncode != 0:
            return None
    return resolve_native_binary()


BINARY = _maybe_build_binary()


def _skip_without_binary() -> None:
    if BINARY is None:
        raise unittest.SkipTest(
            "leviathan-data-plane binary missing — skipping market.ohlcv_validate parity honestly"
        )


class TestMarketOhlcvAllowlist(unittest.TestCase):
    def test_op_registered(self) -> None:
        self.assertIn("market.ohlcv_validate", SUPPORTED_OPERATIONS)
        self.assertIn("market.ohlcv_validate", MARKET_OPERATIONS)


class TestOhlcvValidateParity(unittest.TestCase):
    def test_native_matches_python_streaming_fixture(self) -> None:
        _skip_without_binary()
        self.assertTrue(FIXTURE.is_file(), f"missing fixture {FIXTURE}")
        py = validate_ohlcv_file(FIXTURE)
        self.assertTrue(py.ok, py.error)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "validate.json"
            task = build_task_document(
                task_id="ohlcv-parity-1",
                operation="market.ohlcv_validate",
                input_path=FIXTURE,
                temporary_path=out,
                allowed_roots=[str(FIXTURE.parent.resolve()), str(root)],
                input_format="csv",
            )
            result = run_native_task(task, binary=BINARY, work_dir=root / "work")
            self.assertTrue(result.ok, result.error_message or result.stderr)
            assert result.receipt is not None
            report = result.receipt.get("result") or {}
            if not report and out.is_file():
                report = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(report.get("ok"), report)
            self.assertEqual(int(report["barCount"]), py.bar_count)
            self.assertEqual(report.get("startTs"), py.start_ts)
            self.assertEqual(report.get("endTs"), py.end_ts)
            self.assertEqual(result.receipt["recordsIn"], py.bar_count)

        helper = try_native_ohlcv_validate(FIXTURE, binary=BINARY)
        self.assertIsNotNone(helper)
        assert helper is not None
        self.assertTrue(helper.ok)
        self.assertEqual(helper.bar_count, py.bar_count)
        self.assertEqual(helper.start_ts, py.start_ts)
        self.assertEqual(helper.end_ts, py.end_ts)

    def test_native_rejects_bad_ohlc_like_python(self) -> None:
        _skip_without_binary()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00+00:00,1,0.5,0.4,1.5,10\n",
                encoding="utf-8",
            )
            py = validate_ohlcv_file(path)
            self.assertFalse(py.ok)
            native = try_native_ohlcv_validate(path, binary=BINARY)
            self.assertIsNotNone(native)
            assert native is not None
            self.assertFalse(native.ok)
            self.assertIn("OHLC", (native.error or ""))


class TestParquetAnalyticalExportW185(unittest.TestCase):
    def test_prefer_parquet_when_available(self) -> None:
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("pyarrow not installed")
        with tempfile.TemporaryDirectory() as tmp:
            bars = load_ohlcv(FIXTURE)
            written = write_ohlcv_analytical(
                Path(tmp) / "BTCUSDT_1h",
                bars,
                prefer_parquet=True,
                symbol="BTCUSDT",
            )
            self.assertEqual(written["storageFormat"], "parquet")
            out = Path(written["path"])
            self.assertEqual(out.suffix, ".parquet")
            self.assertEqual(storage_format_for_path(out), "parquet")
            roundtrip = load_ohlcv(out)
            self.assertEqual(len(roundtrip), len(bars))
            self.assertEqual(roundtrip[0].ts, bars[0].ts)

    def test_market_datastore_reports_storage_format(self) -> None:
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("pyarrow not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            db = root / "leviathan.db"
            MigrationRunner(db).apply_all()
            store = MarketSimStore(db)
            data = MarketDataStore(store, markets)
            bars = load_ohlcv(FIXTURE)
            pq_path = markets / "BTCUSDT_1h.parquet"
            write_ohlcv_analytical(pq_path, bars, prefer_parquet=True, symbol="BTCUSDT")
            source = data.inspect_path("BTCUSDT_1h.parquet", register=True)
            self.assertEqual(source.metadata.get("storageFormat"), "parquet")
            exported = data.export_analytical(source.source_id, root / "export")
            self.assertEqual(exported["storageFormat"], "parquet")

            # Native parquet_validate can scan market parquet
            _skip_without_binary()
            out = root / "pq_validate.json"
            task = build_task_document(
                task_id="pq-market-1",
                operation="dataset.parquet_validate",
                input_path=pq_path,
                temporary_path=out,
                allowed_roots=[str(root)],
                input_format="parquet",
            )
            result = run_native_task(task, binary=BINARY, work_dir=root / "work")
            self.assertTrue(result.ok, result.error_message or result.stderr)
            assert result.receipt is not None
            report = result.receipt.get("result") or {}
            self.assertEqual(report.get("rowKind"), "market")
            self.assertEqual(int(report.get("rowCount") or 0), len(bars))

    def test_dataset_version_storage_format_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = root / "markets"
            markets.mkdir()
            src = markets / "BTCUSDT_1h.csv"
            src.write_bytes(FIXTURE.read_bytes())
            db = root / "leviathan.db"
            MigrationRunner(db).apply_all()
            store = MarketSimStore(db)
            data = MarketDataStore(store, markets)
            result = data.import_and_validate(src, symbol="BTCUSDT", timeframe="1h", seal=True)
            ds = result["dataset"]
            self.assertIsNotNone(ds)
            assert ds is not None
            self.assertEqual(ds.get("storageFormat"), "csv")
            self.assertEqual(ds["metadata"].get("storageFormat"), "csv")


class TestNativeHelperFallback(unittest.TestCase):
    def test_returns_none_without_binary(self) -> None:
        with mock.patch(
            "Data.modules.market_sim.native_ohlcv.resolve_native_binary",
            return_value=None,
        ):
            self.assertIsNone(try_native_ohlcv_validate(FIXTURE))


if __name__ == "__main__":
    unittest.main()
