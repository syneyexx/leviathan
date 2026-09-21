"""Piper voice install must fail closed on empty artifacts."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class PiperEmptyArtifactHonestyTests(unittest.TestCase):
    def test_existing_empty_artifacts_are_not_ok(self) -> None:
        from voice import install as install_mod

        with tempfile.TemporaryDirectory() as td:
            voices = Path(td) / "piper" / "voices"
            voices.mkdir(parents=True)
            voice_id = "nl_NL-pim-medium"
            onnx = voices / f"{voice_id}.onnx"
            meta = voices / f"{voice_id}.onnx.json"
            onnx.write_bytes(b"")
            meta.write_bytes(b"")
            with mock.patch.object(install_mod, "VOICE_DATA_DIR", Path(td)):
                with mock.patch.object(
                    install_mod,
                    "PIPER_VOICE_URLS",
                    {voice_id: {"onnx": "http://example.test/a.onnx", "json": "http://example.test/a.json"}},
                ):
                    with mock.patch.object(
                        install_mod,
                        "_download",
                        side_effect=RuntimeError("empty_download:http://example.test/a.onnx"),
                    ):
                        result = install_mod.download_piper_voice(voice_id)
            self.assertFalse(result.get("ok"))
            self.assertTrue(result.get("error"))

    def test_download_rejects_empty_body(self) -> None:
        from voice import install as install_mod

        source = Path(install_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("empty_download", source)
        self.assertIn("empty_voice_artifact", source)


if __name__ == "__main__":
    unittest.main()
