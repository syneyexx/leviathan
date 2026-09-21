"""Research folder ingest must not always emit success when ready=0."""
from __future__ import annotations
import inspect, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

class ResearchFolderIngestEventTests(unittest.TestCase):
    def test_folder_event_uses_ready_failed_counts(self) -> None:
        import platform_services_core as core
        source = inspect.getsource(core.ResearchRunner)
        self.assertIn('event_kind = "warning"', source)
        self.assertIn("ready <= 0", source)
        self.assertIn("Map-indexatie zonder gereede bronnen", source)

if __name__ == "__main__":
    unittest.main()
