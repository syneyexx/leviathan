from __future__ import annotations

import unittest
from unittest.mock import patch

from voice.install import run_install


class VoiceInstallStepValidationTests(unittest.TestCase):
    def test_explicit_empty_steps_do_not_trigger_default_install(self) -> None:
        with patch("voice.install.install_python_deps") as deps, patch(
            "voice.install.ensure_whisper_model"
        ) as whisper, patch("voice.install.download_piper_voice") as piper, patch(
            "voice.install.doctor", return_value={"ready": True}
        ):
            result = run_install([])
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "no_install_steps")
        deps.assert_not_called()
        whisper.assert_not_called()
        piper.assert_not_called()

    def test_unknown_steps_fail_instead_of_being_silently_ignored(self) -> None:
        with patch("voice.install.install_python_deps") as deps, patch(
            "voice.install.ensure_whisper_model"
        ) as whisper, patch("voice.install.download_piper_voice") as piper, patch(
            "voice.install.doctor", return_value={"ready": True}
        ):
            result = run_install(["bogus"])
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "unknown_install_steps")
        self.assertEqual(result.get("unknown_steps"), ["bogus"])
        deps.assert_not_called()
        whisper.assert_not_called()
        piper.assert_not_called()


if __name__ == "__main__":
    unittest.main()