"""VoiceStudio empty speech/transcript must fail closed."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class VoiceStudioEmptySpeechHonestyTests(unittest.TestCase):
    def test_synthesize_rejects_empty_audio_body(self) -> None:
        from speech.voicestudio_client import VoiceStudioClient

        source = inspect.getsource(VoiceStudioClient.synthesize)
        self.assertIn("empty audio body", source.lower())

    def test_runtime_synthesize_chunk_rejects_empty_audio(self) -> None:
        from speech.runtime import SpeechRuntime

        source = inspect.getsource(SpeechRuntime.synthesize_chunk)
        self.assertIn("lege audio", source.lower())

    def test_transcribe_route_returns_ok_false_on_empty_text(self) -> None:
        import speech.routes as routes_mod

        source = inspect.getsource(routes_mod)
        self.assertIn("empty_transcript", source)
        self.assertIn('"ok": False', source)


if __name__ == "__main__":
    unittest.main()
