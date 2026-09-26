"""WAVES 09–12 — FX spot, futures/perps, options, fixed income models."""

from __future__ import annotations

import unittest
from decimal import Decimal

from Data.modules.market_sim.capabilities import build_market_capabilities
from Data.modules.market_sim.fixed_income import FixedIncomeSpec, US10Y
from Data.modules.market_sim.futures_contracts import BTCUSDT_PERP, ES_CME
from Data.modules.market_sim.fx import CurrencyPair, fx_notional, is_likely_fx_symbol
from Data.modules.market_sim.instruments import (
    FOREX_EURUSD,
    FUTURES_ES_STUB,
    CapabilityState,
    InstrumentFamily,
    assert_family_implemented,
    compute_notional,
    family_capability,
    registry_lookup,
    spec_for_symbol,
    support_matrix,
    validate_intent_rules,
)
from Data.modules.market_sim.options_contracts import OptionContractSpec, parse_option_right
from Data.modules.market_sim.types import MarketSimError


class FxSpotW09Tests(unittest.TestCase):
    def test_currency_pair_pips(self) -> None:
        eurusd = CurrencyPair.parse("EUR/USD")
        self.assertEqual(eurusd.symbol, "EURUSD")
        self.assertEqual(eurusd.pip_size(), Decimal("0.0001"))
        usdjpy = CurrencyPair.parse("USDJPY")
        self.assertEqual(usdjpy.pip_size(), Decimal("0.01"))
        self.assertTrue(is_likely_fx_symbol("EURUSD"))
        self.assertFalse(is_likely_fx_symbol("AAPL"))

    def test_forex_supported_and_tradeable(self) -> None:
        self.assertEqual(family_capability(InstrumentFamily.FOREX), CapabilityState.AVAILABLE)
        assert_family_implemented(InstrumentFamily.FOREX)
        self.assertIs(registry_lookup("EURUSD"), FOREX_EURUSD)
        spec = spec_for_symbol("GBPUSD", metadata={"family": "forex"})
        self.assertEqual(spec.family, InstrumentFamily.FOREX)
        self.assertEqual(spec.metadata.get("pip_size"), "0.0001")
        ok, reason, qty = validate_intent_rules(spec=FOREX_EURUSD, side="buy", qty=1000, price="1.1000")
        self.assertTrue(ok, reason)
        self.assertEqual(qty, Decimal("1000"))
        self.assertEqual(fx_notional(1000, "1.1"), Decimal("1100.0"))

    def test_capabilities_forex_available(self) -> None:
        caps = build_market_capabilities(feature_enabled=True, binance_reachable=False, alpaca_paper=False)
        fx = next(m for m in caps["markets"] if m["family"] == "forex")
        self.assertEqual(fx["HISTORICAL_SIM_AVAILABLE"], "AVAILABLE")
        self.assertEqual(fx["LIVE_TRADING_AVAILABLE"], "BLOCKED")


class FuturesPerpsW10Tests(unittest.TestCase):
    def test_multiplier_notional(self) -> None:
        self.assertEqual(ES_CME.notional(2, 5000), Decimal("500000"))
        self.assertEqual(BTCUSDT_PERP.funding_status(), "UNMEASURED")
        self.assertTrue(BTCUSDT_PERP.is_perpetual)
        self.assertFalse(ES_CME.is_perpetual)

    def test_futures_supported(self) -> None:
        self.assertEqual(family_capability(InstrumentFamily.FUTURES), CapabilityState.AVAILABLE)
        ok, reason, _ = validate_intent_rules(
            spec=FUTURES_ES_STUB, side="buy", qty=1, price=5000
        )
        self.assertTrue(ok, reason)
        self.assertEqual(compute_notional(1, 5000, multiplier=FUTURES_ES_STUB), Decimal("250000"))
        perp = spec_for_symbol("BTCUSDT", metadata={"family": "futures", "is_perpetual": True})
        self.assertEqual(perp.family, InstrumentFamily.FUTURES)
        self.assertTrue(perp.metadata.get("is_perpetual"))


class OptionsW11Tests(unittest.TestCase):
    def test_option_spec_greeks_unmeasured(self) -> None:
        opt = OptionContractSpec(
            symbol="AAPL240119C00150000",
            underlying="AAPL",
            right=parse_option_right("call"),
            strike="150",
            expiry="2024-01-19",
            venue="OPRA",
        )
        self.assertEqual(opt.greeks_status(), "UNMEASURED")
        self.assertTrue(opt.public_dict()["truth"]["options_require_contract_rules"])

    def test_options_still_not_tradeable(self) -> None:
        self.assertEqual(family_capability(InstrumentFamily.OPTIONS), CapabilityState.NOT_IMPLEMENTED)
        with self.assertRaises(MarketSimError):
            assert_family_implemented(InstrumentFamily.OPTIONS)
        spec = spec_for_symbol("AAPL_OPT", metadata={"family": "options"})
        ok, reason, qty = validate_intent_rules(spec=spec, side="buy", qty=1, price=5)
        self.assertFalse(ok)
        self.assertIn("INSTRUMENT_FAMILY_NOT_IMPLEMENTED", reason)
        self.assertEqual(qty, Decimal("0"))


class FixedIncomeW12Tests(unittest.TestCase):
    def test_fi_analytics_unmeasured(self) -> None:
        self.assertEqual(US10Y.analytics_status(), "UNMEASURED")
        dirty = US10Y.dirty_price("98.5")
        self.assertEqual(dirty["status"], "UNMEASURED")
        measured = FixedIncomeSpec(
            symbol="T",
            accrued_interest=0.25,
            coupon_rate=0.04,
            yield_to_maturity=0.041,
            duration=7.2,
        )
        self.assertEqual(measured.analytics_status(), "MEASURED")
        self.assertEqual(measured.dirty_price("100")["dirtyPrice"], "100.25")

    def test_fi_not_tradeable_not_equity(self) -> None:
        self.assertEqual(family_capability(InstrumentFamily.FIXED_INCOME), CapabilityState.NOT_IMPLEMENTED)
        matrix = {r["family"]: r for r in support_matrix()["families"]}
        self.assertEqual(matrix["fixed_income"]["capability"], "NOT_IMPLEMENTED")
        self.assertTrue(support_matrix()["truth"]["fixed_income_is_not_equity"])
        spec = spec_for_symbol("US10Y")
        self.assertEqual(spec.family, InstrumentFamily.FIXED_INCOME)
        ok, reason, _ = validate_intent_rules(spec=spec, side="buy", qty=1, price=100)
        self.assertFalse(ok)
        self.assertIn("INSTRUMENT_FAMILY_NOT_IMPLEMENTED", reason)


if __name__ == "__main__":
    unittest.main()
