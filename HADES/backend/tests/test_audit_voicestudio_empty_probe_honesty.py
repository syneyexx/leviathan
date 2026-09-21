"""VoiceStudio client probe must fail closed on empty voices/engines."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from speech.voicestudio_client import VoiceStudioClient


class VoiceStudioClientEmptyProbeHonestyTests(unittest.TestCase):
    def test_empty_voices_engines_not_ok(self) -> None:
        client = VoiceStudioClient(base_url="http://127.0.0.1:3900/v1")

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"voices": [], "engines": []}
        response.text = "{}"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get = AsyncMock(return_value=response)

        async def _run():
            with patch("speech.voicestudio_client.httpx.AsyncClient", return_value=mock_client):
                return await client.probe()

        result = asyncio.run(_run())
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "empty_voices_and_engines")


if __name__ == "__main__":
    unittest.main()
