from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_agent import explore_repository


class CodingAgentWorkspaceSymlinkBoundaryTests(unittest.TestCase):
    def test_explore_repository_does_not_read_file_symlink_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside.py"
            outside.write_text("ASTRA_OUTSIDE_SECRET_MARKER = 1\n", encoding="utf-8")
            link = root / "linked.py"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this host")

            hits = explore_repository(root, "ASTRA_OUTSIDE_SECRET_MARKER", limit=20)

            self.assertFalse(any(hit.path == "linked.py" for hit in hits))
            self.assertFalse(any("ASTRA_OUTSIDE_SECRET_MARKER" in hit.preview for hit in hits))


if __name__ == "__main__":
    unittest.main()
