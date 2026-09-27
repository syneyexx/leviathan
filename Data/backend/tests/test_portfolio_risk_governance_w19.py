"""Wave 19 — portfolio risk-setting governance (approval-gated loosening)."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from Data.modules.execution.builtins import build_default_catalog
from Data.modules.market_sim.data_store import MarketDataStore
from Data.modules.market_sim.portefeuille.risk_governance import (
    PORTFOLIO_RISK_LOOSEN_CAPABILITY,
    RiskMutationClass,
    classify_risk_mutation,
)
from Data.modules.market_sim.service import MarketSimControlPlane
from Data.modules.market_sim.store import MarketSimStore
from Data.modules.market_sim.types import MarketSimError


class _Approvals:
    def __init__(self, ok: set[str], *, capability: str = PORTFOLIO_RISK_LOOSEN_CAPABILITY):
        self.ok = ok
        self.capability = capability
        self.calls: list[tuple[str, str]] = []

    def is_approved(self, approval_id, *, capability_id, side_effects):
        self.calls.append((approval_id, capability_id))
        return approval_id in self.ok and capability_id == self.capability


def _plane(tmp: Path, approvals: _Approvals | None = None) -> MarketSimControlPlane:
    markets = tmp / "markets"
    markets.mkdir(exist_ok=True)
    store = MarketSimStore(tmp / "lev.db")
    store.initialize()
    data = MarketDataStore(store, markets)
    plane = MarketSimControlPlane(store=store, data=data, enabled=True)
    provider = MagicMock()
    provider.status.return_value = MagicMock(reachable=True, latency_ms=1)
    provider.fetch_quote.return_value = {"price": 100.0, "symbol": "BTCUSDT"}
    plane.providers = MagicMock()
    plane.providers.get.return_value = provider
    if approvals is not None:
        plane.portfolios.approval_service = approvals
    return plane


class ClassifyRiskMutationTests(unittest.TestCase):
    def test_directionality(self) -> None:
        before = {
            "max_leverage": 1.0,
            "max_drawdown_pct": 20.0,
            "cash_reserve_pct": 10.0,
            "shorting_enabled": False,
            "max_position_pct": 25.0,
        }
        after = {
            "max_leverage": 2.0,  # loosen
            "max_drawdown_pct": 30.0,  # loosen
            "cash_reserve_pct": 15.0,  # tighten
            "shorting_enabled": True,  # loosen
            "max_position_pct": 25.0,
        }
        a = classify_risk_mutation(before, after)
        self.assertEqual(a.classification, RiskMutationClass.LOOSENING)
        self.assertIn("max_leverage", a.loosening_axes)
        self.assertIn("cash_reserve_pct", a.tightening_axes)

        tight = classify_risk_mutation(
            {"max_leverage": 2.0, "cash_reserve_pct": 5.0},
            {"max_leverage": 1.0, "cash_reserve_pct": 20.0},
        )
        self.assertEqual(tight.classification, RiskMutationClass.TIGHTENING)

        neu = classify_risk_mutation({"fee_bps": 5}, {"fee_bps": 50})
        self.assertEqual(neu.classification, RiskMutationClass.NEUTRAL)


class PortfolioRiskGovernanceW19Tests(unittest.TestCase):
    def test_capability_registered(self) -> None:
        cat = build_default_catalog()
        cap = cat.get(PORTFOLIO_RISK_LOOSEN_CAPABILITY)
        self.assertIsNotNone(cap)
        self.assertTrue(cap.metadata.get("approval_identity"))

    def test_tightening_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td))
            pf = plane.create_portfolio(
                name="T",
                initial_equity=50_000,
                settings={"allow_manual_only": True, "max_leverage": 2.0, "max_drawdown_pct": 30},
            )
            out = plane.patch_portfolio(
                pf["portfolio_id"],
                {"settings": {"max_leverage": 1.0, "max_drawdown_pct": 10}},
            )
            self.assertEqual(float(out["settings"]["max_leverage"]), 1.0)
            hist = out["metadata"]["settings_history"]
            self.assertEqual(hist[-1]["classification"], "TIGHTENING")

    def test_neutral_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td))
            pf = plane.create_portfolio(
                name="N",
                initial_equity=50_000,
                settings={"allow_manual_only": True, "fee_bps": 5},
            )
            out = plane.patch_portfolio(pf["portfolio_id"], {"settings": {"fee_bps": 50}})
            self.assertEqual(float(out["settings"]["fee_bps"]), 50)

    def test_loosening_fails_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td), _Approvals(ok=set()))
            pf = plane.create_portfolio(
                name="L",
                initial_equity=50_000,
                settings={"allow_manual_only": True, "max_leverage": 1.0},
            )
            with self.assertRaises(MarketSimError) as ctx:
                plane.patch_portfolio(
                    pf["portfolio_id"],
                    {"settings": {"max_leverage": 3.0}},
                )
            self.assertEqual(ctx.exception.code, "APPROVAL_REQUIRED")
            # Must not have applied
            self.assertEqual(
                float(plane.get_portfolio(pf["portfolio_id"])["settings"]["max_leverage"]),
                1.0,
            )
            self.assertEqual(
                plane.get_portfolio(pf["portfolio_id"])["metadata"].get("settings_history") or [],
                [],
            )

    def test_wrong_capability_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # Approvals only accept mandate.loosen — wrong for portfolio risk
            apr = _Approvals(ok={"apr-ok"}, capability="market_sim.mandate.loosen")
            plane = _plane(Path(td), apr)
            pf = plane.create_portfolio(
                name="W",
                initial_equity=50_000,
                settings={"allow_manual_only": True, "max_drawdown_pct": 10},
            )
            with self.assertRaises(MarketSimError) as ctx:
                plane.patch_portfolio(
                    pf["portfolio_id"],
                    {"settings": {"max_drawdown_pct": 40}, "approval_id": "apr-ok"},
                )
            self.assertEqual(ctx.exception.code, "APPROVAL_INVALID")

    def test_invalid_approval_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td), _Approvals(ok={"apr-ok"}))
            pf = plane.create_portfolio(
                name="I",
                initial_equity=50_000,
                settings={"allow_manual_only": True, "shorting_enabled": False},
            )
            with self.assertRaises(MarketSimError) as ctx:
                plane.patch_portfolio(
                    pf["portfolio_id"],
                    {"settings": {"shorting_enabled": True}, "approval_id": "apr-bad"},
                )
            self.assertEqual(ctx.exception.code, "APPROVAL_INVALID")

    def test_valid_commits_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            apr = _Approvals(ok={"apr-ok"})
            plane = _plane(Path(td), apr)
            pf = plane.create_portfolio(
                name="V",
                initial_equity=50_000,
                settings={"allow_manual_only": True, "max_leverage": 1.0},
            )
            out = plane.patch_portfolio(
                pf["portfolio_id"],
                {"settings": {"max_leverage": 2.5}, "approval_id": "apr-ok"},
            )
            self.assertEqual(float(out["settings"]["max_leverage"]), 2.5)
            self.assertEqual(len(apr.calls), 1)
            self.assertEqual(apr.calls[0][1], PORTFOLIO_RISK_LOOSEN_CAPABILITY)
            hist = out["metadata"]["settings_history"]
            self.assertEqual(len(hist), 1)
            self.assertEqual(hist[0]["approvalId"], "apr-ok")
            self.assertEqual(hist[0]["classification"], "LOOSENING")

    def test_mixed_all_or_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td), _Approvals(ok=set()))
            pf = plane.create_portfolio(
                name="M",
                initial_equity=50_000,
                settings={
                    "allow_manual_only": True,
                    "max_leverage": 1.0,
                    "cash_reserve_pct": 10.0,
                    "fee_bps": 5,
                },
            )
            with self.assertRaises(MarketSimError):
                plane.patch_portfolio(
                    pf["portfolio_id"],
                    {
                        "settings": {
                            "max_leverage": 5.0,  # loosen
                            "cash_reserve_pct": 20.0,  # tighten
                            "fee_bps": 99,
                        }
                    },
                )
            got = plane.get_portfolio(pf["portfolio_id"])
            self.assertEqual(float(got["settings"]["max_leverage"]), 1.0)
            self.assertEqual(float(got["settings"]["cash_reserve_pct"]), 10.0)
            self.assertEqual(float(got["settings"]["fee_bps"]), 5)

    def test_concurrent_duplicate_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            apr = _Approvals(ok={"apr-dup"})
            plane = _plane(Path(td), apr)
            pf = plane.create_portfolio(
                name="C",
                initial_equity=50_000,
                settings={"allow_manual_only": True, "max_gross_exposure_pct": 100},
            )
            pid = pf["portfolio_id"]
            patch = {
                "settings": {"max_gross_exposure_pct": 250},
                "approval_id": "apr-dup",
            }
            errors: list[BaseException] = []
            results: list[dict] = []

            def _do() -> None:
                try:
                    results.append(plane.patch_portfolio(pid, patch))
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            t1 = threading.Thread(target=_do)
            t2 = threading.Thread(target=_do)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 2)
            final = plane.get_portfolio(pid)
            self.assertEqual(float(final["settings"]["max_gross_exposure_pct"]), 250)
            # History only after successful commits — at most one loosening entry
            hist = final["metadata"].get("settings_history") or []
            loosening = [h for h in hist if h.get("classification") == "LOOSENING"]
            self.assertEqual(len(loosening), 1)

    def test_history_only_after_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane = _plane(Path(td), _Approvals(ok=set()))
            pf = plane.create_portfolio(
                name="H",
                initial_equity=50_000,
                settings={"allow_manual_only": True, "daily_loss_limit_pct": 5},
            )
            with self.assertRaises(MarketSimError):
                plane.patch_portfolio(
                    pf["portfolio_id"],
                    {"settings": {"daily_loss_limit_pct": 25}},
                )
            self.assertEqual(
                plane.get_portfolio(pf["portfolio_id"])["metadata"].get("settings_history") or [],
                [],
            )


if __name__ == "__main__":
    unittest.main()
