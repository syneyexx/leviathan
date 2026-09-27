"""Wave 21 — production provider I/O boundary: no in-process remote fallback."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import MarketSimError


class ProductionProviderIoBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_ext = os.environ.get("LEVIATHAN_WORKERS_EXTERNALIZE_API")
        self._prev_runner = os.environ.get("LEVIATHAN_MARKET_SIM_RUNNER")
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "1"
        os.environ.pop("LEVIATHAN_MARKET_SIM_RUNNER", None)

    def tearDown(self) -> None:
        if self._prev_ext is None:
            os.environ.pop("LEVIATHAN_WORKERS_EXTERNALIZE_API", None)
        else:
            os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = self._prev_ext
        if self._prev_runner is None:
            os.environ.pop("LEVIATHAN_MARKET_SIM_RUNNER", None)
        else:
            os.environ["LEVIATHAN_MARKET_SIM_RUNNER"] = self._prev_runner

    def _plane(self, tmp: Path) -> MarketSimControlPlane:
        markets = tmp / "markets"
        markets.mkdir(exist_ok=True)
        store = MarketSimStore(tmp / "lev.db")
        store.initialize()
        data = MarketDataStore(store, markets)
        return MarketSimControlPlane(store=store, data=data, enabled=True)

    def test_externalized_without_job_runtime_refuses_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = self._plane(Path(td))
            # Any provider that would hit the network if called.
            net = MagicMock()
            net.provider_id = "binance_public"
            net.license_note = "test"
            net.license_state = "PUBLIC"
            net.fetch_historical = MagicMock(side_effect=AssertionError("network must not be called"))
            net.fetch_quote = MagicMock(side_effect=AssertionError("network must not be called"))
            plane.providers = MagicMock()
            plane.providers.get.return_value = net
            plane.job_runtime = None

            with self.assertRaises(MarketSimError) as ctx:
                plane.fetch_market_bars(
                    provider_id="binance_public", symbol="BTCUSDT", timeframe="1h", limit=20
                )
            err = ctx.exception
            self.assertIn("job_runtime", str(err).lower() + str(getattr(err, "code", "")).lower())
            net.fetch_historical.assert_not_called()

    def test_externalized_transport_never_invoked_in_process(self) -> None:
        """Monkeypatch urllib / httpx — production externalized path must not use them."""
        with tempfile.TemporaryDirectory() as td:
            plane = self._plane(Path(td))
            plane.job_runtime = None

            with patch("urllib.request.urlopen") as urlopen:
                urlopen.side_effect = AssertionError("urllib must not run in-process")
                with self.assertRaises(MarketSimError):
                    plane.fetch_market_bars(
                        provider_id="binance_public", symbol="BTCUSDT", timeframe="1h", limit=10
                    )
                urlopen.assert_not_called()

    def test_legacy_inline_labeled_when_externalize_off(self) -> None:
        os.environ["LEVIATHAN_WORKERS_EXTERNALIZE_API"] = "0"
        os.environ["LEVIATHAN_MARKET_SIM_RUNNER"] = "inprocess"
        with tempfile.TemporaryDirectory() as td:
            plane = self._plane(Path(td))
            from Data.modules.market_sim.providers import ProviderRegistry, ProviderStatus
            from Data.modules.market_sim.types import Bar

            class _Stub:
                provider_id = "stub_public"
                license_note = "test"
                license_state = "TEST"

                def ping(self) -> bool:
                    return True

                def status(self) -> ProviderStatus:
                    return ProviderStatus(reachable=True, latency_ms=1, detail="ok")

                def fetch_historical(self, symbol, timeframe, limit=200):
                    return [
                        Bar(
                            ts=f"2024-01-01T{i:02d}:00:00Z",
                            open=100,
                            high=101,
                            low=99,
                            close=100.5,
                            volume=10,
                        )
                        for i in range(min(limit, 5))
                    ]

                def fetch_quote(self, symbol: str):
                    return {"price": 100.0, "provider": self.provider_id, "symbol": symbol}

            reg = ProviderRegistry()
            reg.register(_Stub())  # type: ignore[arg-type]
            plane.providers = reg
            out = plane.fetch_market_bars(
                provider_id="stub_public", symbol="BTCUSDT", timeframe="1h", limit=5
            )
            self.assertGreaterEqual(out["count"], 1)
            # Legacy inline path must be explicitly labeled when present.
            via = out.get("executed_via") or out.get("truth", {}).get("executed_via")
            if via:
                self.assertIn("legacy", str(via).lower() + "inline")


if __name__ == "__main__":
    unittest.main()
