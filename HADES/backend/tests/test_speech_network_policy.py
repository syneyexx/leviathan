from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from speech.runtime import SpeechRuntime


class SpeechNetworkPolicyTests(unittest.TestCase):
    def test_remote_voicestudio_is_blocked_when_network_policy_is_block(self) -> None:
        runtime = SpeechRuntime()
        client = MagicMock()
        client.probe = AsyncMock(return_value={"ok": True, "voices": [], "engines": []})
        values = {
            "network_policy": "block",
            "tts_provider": "voicestudio",
            "tts_base_url": "https://voice.example.invalid/v1",
            "stt_provider": "none",
        }

        with patch.object(runtime, "_tts_client", return_value=client) as make_client:
            result = asyncio.run(runtime.status(values))

        self.assertFalse(result["tts"]["available"])
        self.assertIn("network", str(result["tts"].get("error") or "").lower())
        make_client.assert_not_called()

    def test_loopback_voicestudio_remains_allowed_when_network_policy_is_block(self) -> None:
        runtime = SpeechRuntime()
        client = MagicMock()
        client.probe = AsyncMock(return_value={"ok": True, "voices": [], "engines": []})
        values = {
            "network_policy": "block",
            "tts_provider": "voicestudio",
            "tts_base_url": "http://127.0.0.1:3900/v1",
            "stt_provider": "none",
        }

        with patch.object(runtime, "_tts_client", return_value=client) as make_client:
            result = asyncio.run(runtime.status(values))

        self.assertTrue(result["tts"]["available"])
        make_client.assert_called_once()

    def test_remote_stt_is_blocked_before_client_construction(self) -> None:
        runtime = SpeechRuntime()
        values = {
            "network_policy": "block",
            "tts_provider": "none",
            "stt_provider": "voicestudio",
            "stt_base_url": "https://speech.example.invalid/v1",
        }

        with patch.object(runtime, "_stt_client") as make_client:
            with self.assertRaises(RuntimeError) as raised:
                asyncio.run(runtime.transcribe(values, audio=b"not-empty", filename="audio.wav"))

        self.assertIn("network", str(raised.exception).lower())
        make_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
