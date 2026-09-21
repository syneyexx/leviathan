from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class FolderPickerSubprocessPolicyTests(unittest.TestCase):
    def test_pick_folder_respects_subprocess_block_before_opening_native_dialog(self) -> None:
        client = TestClient(main.app)
        with patch.object(main, "runtime_values", return_value={"subprocess_policy": "block"}), patch.object(
            main, "pick_directory", return_value=None
        ) as picker:
            response = client.post("/api/plugins/pick-folder")
        self.assertIn(response.status_code, {403, 409, 428})
        picker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
