"""WAVE 07 — institutional instrument model foundation."""

from __future__ import annotations

import unittest
from decimal import Decimal

from Data.modules.market_sim.capabilities import build_market_capabilities
from Data.modules.market_sim.instruments import (
    CRYPTO_BTCUSDT,
    EQUITY_AAPL,
    FIXED_INCOME_US10Y_STUB,
    FUTURES_ES_STUB,
    CapabilityState,
    InstrumentFamily,
    assert_family_implemented,
    compute_notional,
    family_capability,
    infer_family,
    make_instrument_id,
    parse_instrument_id,
    registry_lookup,
    spec_for_symbol,
    support_matrix,
    validate_intent_rules,
)
from Data.modules.market_sim.types import MarketSimError


class InstrumentModelW07Tests(unittest.TestCase):
    def test_family_inventory_includes_fixed_income(self) -> None:
        names = {f.value for f in InstrumentFamily}
        self.assertIn("fixed_income", names)
        self.assertIn("other", names)
        matrix = support_matrix()
        by_fam = {row["family"]: row for row in matrix["families"]}
        self.assertEqual(by_fam["equity"]["capability"], "AVAILABLE")
        self.assertEqual(by_fam["crypto_spot"]["capability"], "AVAILABLE")
        self.assertEqual(by_fam["forex"]["capability"], "AVAILABLE")
        self.assertEqual(by_fam["futures"]["capability"], "AVAILABLE")
        for unsupported in ("options", "fixed_income", "other"):
            self.assertEqual(by_fam[unsupported]["capability"], "NOT_IMPLEMENTED")
            self.assertFalse(by_fam[unsupported]["end_to_end"])
        self.assertTrue(matrix["truth"]["enum_exists_is_not_market_support"])

    def test_capabilities_matrix_covers_all_families(self) -> None:
        caps = build_market_capabilities(feature_enabled=True, binance_reachable=False, alpaca_paper=False)
        families = {m["family"] for m in caps["markets"]}
        for fam in InstrumentFamily:
            self.assertIn(fam.value, families, msg=fam.value)
        fi = next(m for m in caps["markets"] if m["family"] == "fixed_income")
        self.assertEqual(fi["HISTORICAL_SIM_AVAILABLE"], "NOT_IMPLEMENTED")
        self.assertEqual(fi["LIVE_TRADING_AVAILABLE"], "BLOCKED")
        fx = next(m for m in caps["markets"] if m["family"] == "forex")
        self.assertEqual(fx["HISTORICAL_SIM_AVAILABLE"], "AVAILABLE")

    def test_instrument_id_round_trip(self) -> None:
        iid = make_instrument_id(InstrumentFamily.EQUITY, "aapl", "nasdaq")
        self.assertEqual(iid, "equity:AAPL:NASDAQ")
        fam, sym, venue = parse_instrument_id(iid)
        self.assertEqual((fam, sym, venue), ("equity", "AAPL", "NASDAQ"))
        with self.assertRaises(ValueError):
            parse_instrument_id("bad")

    def test_multiplier_notional(self) -> None:
        self.assertEqual(compute_notional(2, 100, multiplier="1"), Decimal("200"))
        self.assertEqual(compute_notional(2, 100, multiplier=FUTURES_ES_STUB), Decimal("10000"))
        self.assertEqual(EQUITY_AAPL.multiplier, "1")
        self.assertEqual(CRYPTO_BTCUSDT.multiplier, "1")

    def test_identifiers_on_public_dict(self) -> None:
        pub = EQUITY_AAPL.public_dict()
        self.assertEqual(pub["identifiers"]["isin"], "US0378331005")
        self.assertEqual(pub["multiplier"], "1")
        self.assertTrue(pub["truth"]["multiplier_required_for_contract_notional"])

    def test_registry_lookup(self) -> None:
        self.assertIs(registry_lookup("AAPL"), EQUITY_AAPL)
        self.assertIs(registry_lookup("equity:AAPL:NASDAQ"), EQUITY_AAPL)
        self.assertIs(registry_lookup("BTCUSDT"), CRYPTO_BTCUSDT)
        self.assertIsNone(registry_lookup("UNKNOWNXYZ"))
        self.assertIs(registry_lookup("US10Y"), FIXED_INCOME_US10Y_STUB)

    def test_unsupported_never_available_or_equity_rules(self) -> None:
        for fam in (
            InstrumentFamily.OPTIONS,
            InstrumentFamily.FIXED_INCOME,
            InstrumentFamily.OTHER,
        ):
            self.assertEqual(family_capability(fam), CapabilityState.NOT_IMPLEMENTED)
            with self.assertRaises(MarketSimError) as ctx:
                assert_family_implemented(fam)
            self.assertEqual(ctx.exception.code, "INSTRUMENT_FAMILY_NOT_IMPLEMENTED")

        ok2, reason2, _ = validate_intent_rules(
            spec=FIXED_INCOME_US10Y_STUB, side="buy", qty=1, price=100
        )
        self.assertFalse(ok2)
        self.assertIn("INSTRUMENT_FAMILY_NOT_IMPLEMENTED", reason2)

    def test_infer_family_fixed_income_and_forex_not_equity(self) -> None:
        self.assertEqual(infer_family("US10Y"), InstrumentFamily.FIXED_INCOME)
        self.assertEqual(
            infer_family("BOND1", metadata={"instrument_type": "bond"}),
            InstrumentFamily.FIXED_INCOME,
        )
        self.assertEqual(infer_family("EURUSD"), InstrumentFamily.FOREX)
        spec = spec_for_symbol("EURUSD")
        self.assertEqual(spec.family, InstrumentFamily.FOREX)
        self.assertEqual(spec.capability_status(), CapabilityState.AVAILABLE)

    def test_equity_intent_still_ok(self) -> None:
        ok, reason, qty = validate_intent_rules(
            spec=EQUITY_AAPL, side="buy", qty=10, price=150
        )
        self.assertTrue(ok, reason)
        self.assertEqual(qty, Decimal("10"))


if __name__ == "__main__":
    unittest.main()
