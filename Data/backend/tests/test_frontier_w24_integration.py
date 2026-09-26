"""W24 — final integration smoke: no architectural islands; live blocked."""

from __future__ import annotations

import unittest

from Data.modules.execution.computer_use import propose_actions_from_model_text, run_computer_use_loop
from Data.modules.execution.data_analysis import safe_calculate
from Data.modules.market_sim.agent_lab import LabOutcome, finalize_lab, new_agent_lab
from Data.modules.market_sim.paper_deployment import assess_feed_health
from Data.modules.market_sim.trading_live_guard import LiveTradingGuard
from Data.modules.voice.transport import probe_voice_capabilities


class FrontierW24IntegrationTests(unittest.TestCase):
    def test_live_blocked_and_lab_negative_result_valid(self) -> None:
        live = LiveTradingGuard().public_status()
        self.assertIn(str(live.get("LIVE_TRADING_AVAILABLE") or live.get("live_trading") or "BLOCKED").upper(),
                        {"BLOCKED", "FALSE", "UNAVAILABLE", "UNSUPPORTED"})
        lab = new_agent_lab(lab_id="w24")
        finalize_lab(lab)
        self.assertEqual(lab.outcome, LabOutcome.NO_STRATEGY_QUALIFIED.value)

    def test_cross_domain_helpers_compose(self) -> None:
        self.assertTrue(safe_calculate("1+1")["ok"])
        voice = probe_voice_capabilities().public_dict()
        self.assertTrue(voice["truth"]["voice_is_transport"])
        health = assess_feed_health(feed_id="x", last_tick_ts=None)
        self.assertEqual(health.status, "UNMEASURED")
        actions = propose_actions_from_model_text("ACTION kind=click target=#a")
        loop = run_computer_use_loop(
            proposals=actions,
            authorize=lambda a: {"allowed": False, "reason": "deny"},
            execute=lambda a: {},
            observe=lambda a, e: {},
            verify=lambda a, e, o: {},
        )
        self.assertTrue(loop.public_dict()["truth"]["model_text_cannot_directly_control_os"])

    def test_parallel_runtimes_none_declared(self) -> None:
        # Architectural vow — no *V2 owners introduced by frontier waves.
        import Data.modules.market_sim as ms
        import Data.modules.execution as ex
        self.assertFalse(hasattr(ms, "PortfolioV2"))
        self.assertFalse(hasattr(ex, "AutomationRuntime2"))


if __name__ == "__main__":
    unittest.main()
