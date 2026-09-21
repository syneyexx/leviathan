"""Removed unused helpers must stay gone (usage-proof regression)."""
from __future__ import annotations
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

class DeadCodeRemovedTests(unittest.TestCase):
    def test_unused_helpers_absent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        forbidden = {'agent_runtimes.py': 'def looks_like_url_host', 'artifacts.py': 'def extension_for_mime', 'code_intel.py': 'def analyze_workspace', 'control/detect.py': 'def findings_not_in_registry', 'control/validation.py': 'def unbounded_or', 'gen2/committee.py': 'def role_stance_live_sync_blocked', 'result_contracts.py': 'def attach_plan', 'execution_truth.py': 'def can_complete_task', 'gen2/mission_control.py': 'def _artifact_present', 'gen2/skill_runtime.py': 'def workflow_definition_digest'}
        for rel, needle in forbidden.items():
            text = (root / rel).read_text(encoding="utf-8")
            self.assertNotIn(needle, text, rel)
        committee = (root / "gen2/committee.py").read_text(encoding="utf-8")
        for name in ['def role_stance_live_sync', 'def role_stance_live_async']:
            self.assertIn(name, committee)
        mission = (root / "gen2/mission_control.py").read_text(encoding="utf-8")
        for name in ['def _artifact_verified']:
            self.assertIn(name, mission)

if __name__ == "__main__":
    unittest.main()
