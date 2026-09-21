"""Regression coverage for VoiceStudio's synchronous provider boundary."""

from __future__ import annotations

import asyncio
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice.errors import VoiceProviderError
from voice.providers.voicestudio_tts import VoiceStudioTts


class _FakeVoiceStudioClient:
    async def probe(self):
        await asyncio.sleep(0)
        return {"ok": True, "error": None}

    async def list_voices(self):
        await asyncio.sleep(0)
        return {
            "voices": [
                {
                    "id": "local-test",
                    "name": "Local Test",
                    "language": "nl",
                }
            ]
        }

    async def synthesize(self, **kwargs):
        await asyncio.sleep(0)
        self.cancel_event = kwargs.get("cancel_event")
        return {
            "audio": b"RIFF-test",
            "mime_type": "audio/wav",
            "sample_rate": 22050,
            "voice": kwargs.get("voice") or "default",
        }


class VoiceStudioAsyncBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_provider_methods_are_safe_inside_running_event_loop(self) -> None:
        provider = VoiceStudioTts()
        fake = _FakeVoiceStudioClient()

        with (
            patch.object(provider, "_client", return_value=fake),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", RuntimeWarning)

            availability = provider.availability()
            voices = provider.list_voices(language="nl")
            synthesis = provider.synthesize(
                "Hallo",
                voice_id="local-test",
                language="nl",
            )

        self.assertTrue(availability["ready"])
        self.assertEqual([voice.id for voice in voices], ["local-test"])
        self.assertEqual(synthesis.audio, b"RIFF-test")
        self.assertEqual(synthesis.voice_id, "local-test")
        self.assertIsInstance(fake.cancel_event, asyncio.Event)

    async def test_cancelled_synthesis_does_not_create_async_operation(self) -> None:
        provider = VoiceStudioTts()
        fake = _FakeVoiceStudioClient()

        with patch.object(provider, "_client", return_value=fake):
            with self.assertRaises(VoiceProviderError) as ctx:
                provider.synthesize("stop", cancel_check=lambda: True)

        self.assertIn("cancel", str(ctx.exception).lower())
        self.assertFalse(hasattr(fake, "cancel_event"))


if __name__ == "__main__":
    unittest.main()
