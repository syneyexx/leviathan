from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class BridgeTemplateDriftTests(unittest.TestCase):
    def assert_template_matches_live(self, plugin_id: str, template_name: str) -> None:
        live = (ROOT / "plugins" / plugin_id / "hades_bridge.py").read_text(encoding="utf-8")
        template = (ROOT / "plugins" / "_shared" / "bridge_templates" / template_name).read_text(encoding="utf-8")
        self.assertEqual(
            template,
            live,
            f"{plugin_id} live bridge drifted from generator template; regeneration would reintroduce stale behavior",
        )

    def test_agent_reach_template_matches_hardened_live_bridge(self) -> None:
        self.assert_template_matches_live("agent-reach", "agent-reach.py")

    def test_rtk_template_matches_hardened_live_bridge(self) -> None:
        self.assert_template_matches_live("rtk", "rtk.py")


if __name__ == "__main__":
    unittest.main()
