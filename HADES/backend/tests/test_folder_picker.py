import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from folder_picker import FolderPickerUnavailable, pick_directory


class FolderPickerTests(unittest.TestCase):
    def test_powershell_script_reads_title_from_environment(self) -> None:
        from folder_picker import _POWERSHELL_FOLDER_PICKER
        self.assertIn("$env:HADES_FOLDER_PICKER_TITLE", _POWERSHELL_FOLDER_PICKER)
        self.assertNotIn("Selecteer pluginmap", _POWERSHELL_FOLDER_PICKER)

    def test_pick_directory_returns_cancelled_and_unavailable(self) -> None:
        with patch("folder_picker._pick_tkinter", return_value=None), patch("folder_picker._pick_windows_powershell", return_value=None):
            with patch("folder_picker.os.name", "posix"):
                self.assertIsNone(pick_directory("Selecteer pluginmap"))
        with patch("folder_picker._pick_tkinter", side_effect=FolderPickerUnavailable("geen display")):
            with patch("folder_picker.os.name", "posix"):
                with self.assertRaises(FolderPickerUnavailable):
                    pick_directory("Selecteer pluginmap")

    def test_windows_powershell_passes_title_via_env(self) -> None:
        captured: dict[str, str] = {}

        class Result:
            returncode = 0
            stdout = b"D:\\Plugins\\demo"
            stderr = b""

        def fake_run(command, **kwargs):
            captured["env_title"] = kwargs["env"]["HADES_FOLDER_PICKER_TITLE"]
            captured["command"] = command
            return Result()

        with patch("folder_picker.os.name", "nt"), patch("folder_picker._powershell_executable", return_value=Path("powershell.exe")), patch("folder_picker.subprocess.run", side_effect=fake_run):
            from folder_picker import _pick_windows_powershell
            selected = _pick_windows_powershell("Kies map")
        self.assertEqual(selected, r"D:\Plugins\demo")
        self.assertEqual(captured["env_title"], "Kies map")
        self.assertNotIn("Kies map", " ".join(str(part) for part in captured["command"]))


if __name__ == "__main__":
    unittest.main()
