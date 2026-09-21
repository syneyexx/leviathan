"""Automated tests for VoiceStudio TTS integration (no live audio required)."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main
from database import Database
from speech.memory_gate import evaluate_tts_memory_budget
from speech.runtime import SpeechRuntime
from speech.speakable import prepare_speakable_text, split_speakable_chunks
from speech.voicestudio_client import VoiceStudioClient, engine_supported_settings, normalize_base_url


class SpeakableTextTests(unittest.TestCase):
    def test_strips_code_reasoning_and_tools(self) -> None:
        raw = """
Antwoord: Hallo wereld.
```python
print("secret")
```
<think>interne redenering</think>
Tool result: {"ok": true}
Redenering: dit mag niet klinken.
"""
        text = prepare_speakable_text(raw)
        self.assertIn("Hallo wereld", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("interne redenering", text)
        self.assertNotIn("Tool result", text)
        self.assertNotIn("Redenering", text)

    def test_sentence_chunks_for_ttfa(self) -> None:
        text = "Eerste zin. Tweede zin! Derde zin?"
        chunks = split_speakable_chunks(text, max_chars=20)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(chunks))


class VoiceStudioClientTests(unittest.TestCase):
    def test_normalize_base_url(self) -> None:
        self.assertEqual(normalize_base_url("http://127.0.0.1:3900"), "http://127.0.0.1:3900/v1")
        self.assertEqual(normalize_base_url("http://127.0.0.1:3900/v1/"), "http://127.0.0.1:3900/v1")

    def test_engine_ui_hints_hide_unsupported(self) -> None:
        hints = engine_supported_settings({"id": "kittentts", "supports_voice_design": False}, "kittentts")
        self.assertTrue(hints.get("speed"))
        self.assertFalse(hints.get("description", False))

        vox = engine_supported_settings({"id": "voxcpm2", "supports_voice_design": True}, "voxcpm2")
        self.assertTrue(vox.get("description"))

    def test_probe_uses_voices_endpoint(self) -> None:
        async def _run() -> None:
            client = VoiceStudioClient(base_url="http://127.0.0.1:3900/v1")

            class FakeResponse:
                status_code = 200

                def json(self):
                    return {
                        "voices": [{"voice_id": "default", "name": "Default", "type": "openai_alias"}],
                        "engines": [{"id": "omnivoice", "available": True, "min_vram_gb": 6.0}],
                    }

            class FakeAsyncClient:
                def __init__(self, *args, **kwargs):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return False

                async def get(self, url, headers=None):
                    self.url = url
                    return FakeResponse()

            with patch("speech.voicestudio_client.httpx.AsyncClient", FakeAsyncClient):
                result = await client.probe()
            self.assertTrue(result["ok"])
            self.assertFalse(result["streaming_speech"])
            self.assertEqual(len(result["voices"]), 1)

        asyncio.run(_run())


class SpeechRuntimeTests(unittest.TestCase):
    def test_settings_independent_of_lm_studio_model(self) -> None:
        runtime = SpeechRuntime()
        values = {
            "tts_provider": "voicestudio",
            "tts_voice_id": "my-clone",
            "tts_model": "tts-1",
            "spoken_answers_enabled": True,
            "stt_provider": "paste",
        }
        cfg = runtime.settings_from(values)
        values_after_model_switch = {**values, "lm_studio_base_url": "http://127.0.0.1:1234/v1"}
        cfg2 = runtime.settings_from(values_after_model_switch)
        self.assertEqual(cfg["tts_voice_id"], "my-clone")
        self.assertEqual(cfg2["tts_voice_id"], "my-clone")
        self.assertEqual(cfg2["tts_provider"], "voicestudio")

    def test_barge_in_rejects_stale_generation(self) -> None:
        async def _run() -> None:
            runtime = SpeechRuntime()
            values = {
                "tts_provider": "voicestudio",
                "tts_voice_id": "default",
                "tts_model": "tts-1",
                "spoken_answers_enabled": True,
                "tts_sentence_chunking": False,
                "tts_min_free_ram_mb": 0,
                "tts_min_free_vram_mb": 0,
            }
            began = await runtime.begin(values)
            stale = began["generation_id"]
            await runtime.stop(generation_id=stale)
            with self.assertRaises(InterruptedError):
                await runtime.synthesize_chunk(values, text="Hallo", generation_id=stale, chunk_index=0)

        asyncio.run(_run())

    def test_echo_guard_blocks_during_playback(self) -> None:
        runtime = SpeechRuntime()
        runtime.set_playback(active=True, echo_guard_ms=500)
        state = runtime.echo_guard_state({"stt_echo_guard_ms": 500})
        self.assertTrue(state["blocked"])
        runtime.set_playback(active=False, echo_guard_ms=500)
        state2 = runtime.echo_guard_state({"stt_echo_guard_ms": 500})
        self.assertIn("remaining_ms", state2)

    def test_synthesize_chunk_with_mocked_voicestudio(self) -> None:
        async def _run() -> None:
            runtime = SpeechRuntime()
            values = {
                "tts_provider": "voicestudio",
                "tts_voice_id": "alloy",
                "tts_model": "tts-1",
                "tts_language": "nl",
                "tts_response_format": "wav",
                "tts_sentence_chunking": True,
                "tts_min_free_ram_mb": 0,
                "tts_min_free_vram_mb": 0,
                "spoken_answers_enabled": True,
            }
            began = await runtime.begin(values)

            async def fake_status(_values):
                return {
                    "tts": {
                        "available": True,
                        "supported_settings": {"speed": True, "language": True},
                        "selected_engine": {"id": "omnivoice", "min_vram_gb": 0},
                    }
                }

            async def fake_synthesize(**kwargs):
                return {
                    "audio": b"RIFF....WAVEfmt ",
                    "mime_type": "audio/wav",
                    "response_format": "wav",
                    "bytes": 16,
                    "model": "tts-1",
                    "voice": "alloy",
                }

            with patch.object(runtime, "status", AsyncMock(side_effect=fake_status)):
                with patch("speech.runtime.VoiceStudioClient.synthesize", AsyncMock(side_effect=fake_synthesize)):
                    with patch(
                        "speech.runtime.evaluate_tts_memory_budget",
                        return_value={"ok": True, "probe": {}, "reasons": [], "forced_model_unload": False},
                    ):
                        result = await runtime.synthesize_chunk(
                            values,
                            text="Hallo, dit is een Nederlandse test.",
                            generation_id=began["generation_id"],
                            chunk_index=0,
                        )
            self.assertEqual(result["voice"], "alloy")
            self.assertTrue(result["audio_base64"])
            self.assertFalse(result["streaming_speech"])
            base64.b64decode(result["audio_base64"])

        asyncio.run(_run())


class MemoryGateTests(unittest.TestCase):
    def test_refuses_low_ram_without_unloading_model(self) -> None:
        with patch(
            "speech.memory_gate.probe_host_memory",
            return_value={"ram_available_mb": 200, "vram_free_mb": None, "notes": []},
        ):
            decision = evaluate_tts_memory_budget(min_free_ram_mb=1500)
        self.assertFalse(decision["ok"])
        self.assertFalse(decision["forced_model_unload"])


class SpeechApiRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        main.database = Database(str(Path(self.tmp.name) / "speech.db"))
        main.database.initialize()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_speech_status_when_provider_none(self) -> None:
        response = self.client.get("/api/speech/status")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIn("tts", payload)
        self.assertIn("stt", payload)
        self.assertTrue(payload.get("lm_studio_independence"))
        self.assertFalse(payload["tts"].get("streaming_speech", True))

    def test_speech_unavailable_returns_recovery(self) -> None:
        current = main.database.get_settings()
        saved = main.database.update_settings(
            {
                **current,
                "tts_provider": "voicestudio",
                "tts_base_url": "http://127.0.0.1:39999/v1",
                "spoken_answers_enabled": True,
            }
        )
        self.assertEqual(saved.get("tts_provider"), "voicestudio")
        response = self.client.get("/api/speech/status")
        self.assertEqual(response.status_code, 200, response.text)
        tts = response.json()["tts"]
        self.assertFalse(tts.get("available"))
        self.assertTrue(tts.get("recovery"))

    def test_default_settings_include_speech_keys(self) -> None:
        values = main.database.get_settings()
        for key in (
            "spoken_answers_enabled",
            "tts_provider",
            "tts_voice_id",
            "stt_provider",
            "stt_echo_guard_ms",
        ):
            self.assertIn(key, values)

    def test_stop_endpoint(self) -> None:
        response = self.client.post("/api/speech/stop", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("stopped", response.json())


class VoiceStudioPluginBridgeTests(unittest.TestCase):
    def test_doctor_documents_real_endpoints(self) -> None:
        path = Path(__file__).resolve().parents[2] / "plugins" / "voicestudio" / "hades_bridge.py"
        spec = importlib.util.spec_from_file_location("voicestudio_bridge", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        doc = mod.doctor()
        self.assertIn("GET /v1/audio/voices", doc["documented_endpoints"])
        self.assertFalse(doc["streaming_speech"])


if __name__ == "__main__":
    unittest.main()
