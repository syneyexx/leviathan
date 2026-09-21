from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_confidence import inventory_gates


class ReleaseConfidenceInventoryHonestyTests(unittest.TestCase):
    def test_unreadable_verify_batch_is_an_error_not_a_green_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs").mkdir()
            (root / "backend" / "tests").mkdir(parents=True)
            (root / "tests").mkdir()
            (root / "docs" / "TESTING_RELEASE_GATES.md").write_text("gates", encoding="utf-8")
            verify = root / "VERIFY_HADES.bat"
            verify.write_text("echo [1] test", encoding="utf-8")
            (root / "tests" / "source-contracts.test.mjs").write_text("", encoding="utf-8")

            original_read_text = Path.read_text

            def guarded_read_text(path: Path, *args, **kwargs):
                if path == verify:
                    raise OSError("access denied")
                return original_read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", guarded_read_text):
                result = inventory_gates(root)

            gate = next(item for item in result["gates"] if item["id"] == "verify_bat")
            self.assertEqual(gate["status"], "error")
            self.assertEqual(result["overall"], "error")
            self.assertEqual(gate["stages"], [])
            self.assertIn("access denied", gate["detail"])
            self.assertTrue(any("VERIFY_HADES.bat" in item["label"] for item in result["what_broke"]))


if __name__ == "__main__":
    unittest.main()
