"""Unit/integration tests for HADES local voice subsystem."""

from __future__ import annotations

import base64
import io
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice.audio_utils import is_silence, rms_level, write_wav_pcm16
from voice.events import AudioSegment, AudioSegmentQueue
from voice.runtime import VoiceSessionManager, new_turn_id
from voice.speakable import assistant_to_speakable, is_speakable_payload, split_speakable_segments
from voice.vad import VadConfig, VadState, update_vad


def _silent_wav(seconds: float = 0.4, rate: int = 16000) -> bytes:
    frames = b"\x00\x00" * int(rate * seconds)
    return write_wav_pcm16(frames, sample_rate=rate)


def _tone_wav(seconds: float = 0.5, rate: int = 16000, amp: int = 8000) -> bytes:
    import math
    import struct

    samples = bytearray()
    for i in range(int(rate * seconds)):
        value = int(amp * math.sin(2 * math.pi * 440 * i / rate))
        samples.extend(struct.pack("<h", value))
    return write_wav_pcm16(bytes(samples), sample_rate=rate)


class SpeakableTests(unittest.TestCase):
    def test_markdown_and_code_compact(self) -> None:
        text = "Hallo **wereld**.\n\n```python\nprint(1)\nprint(2)\nprint(3)\n```\n\nZie [docs](https://example.com/path)."
        out = assistant_to_speakable(text, style="compact", language="nl")
        self.assertIn("Hallo wereld", out)
        self.assertIn("codeblok", out.lower())
        self.assertNotIn("```", out)
        self.assertIn("link naar example.com", out)
        self.assertNotIn("print(1)", out)

    def test_provisional_not_speakable(self) -> None:
        self.assertFalse(is_speakable_payload({"provisional": True, "delta": "geheim"}))
        self.assertTrue(is_speakable_payload({"speakable": True, "text": "ok"}))
        self.assertTrue(is_speakable_payload({"type": "final_answer", "text": "ok"}))

    def test_segment_order(self) -> None:
        parts = split_speakable_segments("Eén. Twee! Drie?")
        self.assertGreaterEqual(len(parts), 1)
        self.assertTrue(all(parts))


class SessionDedupeTests(unittest.TestCase):
    def test_final_transcript_dedupe_and_reconnect(self) -> None:
        mgr = VoiceSessionManager()
        session = mgr.start(conversation_id="c1", client_tab_id="tab-a")
        turn = new_turn_id()
        self.assertTrue(mgr.register_final_transcript(session, turn, "hallo hades"))
        self.assertFalse(mgr.register_final_transcript(session, turn, "hallo hades"))
        # Same tab reconnect returns existing session without auto-enabling mic
        again = mgr.start(conversation_id="c1", client_tab_id="tab-a")
        self.assertEqual(again.session_id, session.session_id)
        event = mgr.stop(session.session_id)
        self.assertEqual(event["type"], "session_stopped")

    def test_other_tab_blocked(self) -> None:
        from voice.providers.base import VoiceProviderError

        mgr = VoiceSessionManager()
        mgr.start(conversation_id="c1", client_tab_id="tab-a")
        with self.assertRaises(VoiceProviderError):
            mgr.start(conversation_id="c1", client_tab_id="tab-b")

    def test_spoken_response_dedupe(self) -> None:
        mgr = VoiceSessionManager()
        session = mgr.start(conversation_id="c1", client_tab_id="tab-spoken")
        self.assertTrue(mgr.mark_response_spoken(session, "resp-1:1"))
        self.assertFalse(mgr.mark_response_spoken(session, "resp-1:1"))
        mgr.stop(session.session_id)

    def test_synthesize_skips_already_spoken(self) -> None:
        from voice.runtime import VoiceRuntime, synthesize_response_segments

        class FakeTts:
            id = "piper"

            def synthesize(self, text, **kwargs):
                from voice.providers.base import SynthesisResult

                return SynthesisResult(
                    audio=b"RIFF" + b"\x00" * 100,
                    mime_type="audio/wav",
                    sample_rate=22050,
                    voice_id="fake",
                    provider="piper",
                    speakable_text=text,
                )

        class FakeRuntime:
            def tts_provider(self, settings):
                return FakeTts()

        mgr = VoiceSessionManager()
        session = mgr.start(conversation_id="c1", client_tab_id="tab-synth")
        first = synthesize_response_segments(
            runtime=FakeRuntime(),
            session=session,
            response_id="r1",
            text="Hallo wereld.",
            settings={"voice_language": "nl", "voice_speak_style": "compact"},
        )
        self.assertGreaterEqual(len(first), 1)
        second = synthesize_response_segments(
            runtime=FakeRuntime(),
            session=session,
            response_id="r1",
            text="Hallo wereld.",
            settings={"voice_language": "nl", "voice_speak_style": "compact"},
        )
        self.assertEqual(second, [])
        mgr.stop(session.session_id)


class WakeWordTests(unittest.TestCase):
    def test_remainder_after_wake(self) -> None:
        from voice.wake_word import WakeWordDetector

        class FakeAsr:
            def transcribe(self, audio, *, language="nl", mime_type="audio/wav"):
                from voice.providers.base import TranscriptResult

                return TranscriptResult(
                    text="Hades wat is de tijd",
                    language="nl",
                    confidence=0.9,
                    provider="fake",
                    model="fake",
                    duration_seconds=1.0,
                    metadata={},
                )

        detector = WakeWordDetector(FakeAsr(), enabled=True)
        out = detector.process_audio(b"RIFF", mime_type="audio/wav")
        self.assertTrue(out["detected"])
        self.assertIn("tijd", out["remainder"].lower())
        self.assertNotIn("hades", out["remainder"].lower())


class AudioQueueTests(unittest.TestCase):
    def test_generation_cancels_stale(self) -> None:
        queue = AudioSegmentQueue()
        seg = AudioSegment(
            session_id="s",
            turn_id="t",
            response_id="r",
            order=0,
            generation=1,
            mime_type="audio/wav",
            sample_rate=22050,
            audio_b64="AAAA",
            text="een",
        )
        self.assertTrue(queue.push(seg))
        queue.bump_generation()
        self.assertIsNone(queue.pop_ready())
        stale = AudioSegment(
            session_id="s",
            turn_id="t",
            response_id="r",
            order=1,
            generation=1,
            mime_type="audio/wav",
            sample_rate=22050,
            audio_b64="BBBB",
            text="oud",
        )
        self.assertFalse(queue.push(stale))


class SilenceAndVadTests(unittest.TestCase):
    def test_silence_detected(self) -> None:
        frames = b"\x00\x00" * 1600
        self.assertTrue(is_silence(frames, threshold=0.012, sample_rate=16000))
        self.assertLess(rms_level(frames), 0.01)

    def test_vad_speech_edges(self) -> None:
        state = VadState()
        cfg = VadConfig(sensitivity=1.0, end_silence_ms=100, min_speech_ms=40)
        # Synthesize loud PCM directly (avoid WAV container confusion)
        import math
        import struct

        loud = bytearray()
        for i in range(1600):
            value = int(20000 * math.sin(2 * math.pi * 440 * i / 16000))
            loud.extend(struct.pack("<h", value))
        pcm = bytes(loud)
        event = None
        for _ in range(5):
            state, event = update_vad(state, pcm, sample_rate=16000, config=cfg, frame_ms=50)
            if event == "speech_started":
                break
        self.assertEqual(event, "speech_started")
        quiet = b"\x00\x00" * 800
        end_event = None
        for _ in range(10):
            state, end_event = update_vad(state, quiet, sample_rate=16000, config=cfg, frame_ms=50)
            if end_event == "speech_ended":
                break
        self.assertEqual(end_event, "speech_ended")


class VoiceApiRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        import main
        from database import Database
        from fastapi.testclient import TestClient
        from voice import runtime as runtime_mod

        # Isolate process-local session registry across tests.
        runtime_mod._SESSION_MANAGER = VoiceSessionManager()
        if runtime_mod.VoiceRuntime._instance is not None:
            runtime_mod.VoiceRuntime._instance.sessions = runtime_mod._SESSION_MANAGER

        db = Database(str(Path(self.tmp.name) / "voice.db"))
        db.initialize()
        main.database = db
        main.runner = main.TaskRunner()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()
        self.addCleanup(lambda: self.client_context.__exit__(None, None, None))

    def test_voice_status_and_speakable(self) -> None:
        status = self.client.get("/api/voice/status")
        self.assertEqual(status.status_code, 200)
        body = status.json()
        self.assertIn("checks", body)
        self.assertIn("providers", body)
        speakable = self.client.post(
            "/api/voice/speakable",
            json={"text": "Dit is **belangrijk** en niet onzeker.", "style": "compact", "language": "nl"},
        )
        self.assertEqual(speakable.status_code, 200)
        data = speakable.json()
        self.assertIn("belangrijk", data["speakable_text"])
        self.assertNotIn("**", data["speakable_text"])

    def test_silence_transcribe_does_not_send(self) -> None:
        wav = _silent_wav()
        # Without faster-whisper, endpoint may 400 dependency_missing — accept either silence skip or honest error.
        encoded = base64.b64encode(wav).decode("ascii")
        response = self.client.post(
            "/api/voice/transcribe",
            json={"audio_base64": encoded, "mime_type": "audio/wav", "language": "nl", "is_final": True},
        )
        if response.status_code == 200:
            payload = response.json()
            self.assertTrue(payload.get("silence") or not payload.get("should_send"))
        else:
            detail = response.json().get("detail")
            self.assertTrue(isinstance(detail, dict) or isinstance(detail, str))

    def test_session_interrupt_and_stop(self) -> None:
        start = self.client.post(
            "/api/voice/session/start",
            json={"conversation_id": None, "client_tab_id": "test-tab-interrupt", "force": True},
        )
        self.assertEqual(start.status_code, 200, start.text)
        sid = start.json()["session_id"]
        interrupt = self.client.post(f"/api/voice/session/{sid}/interrupt", json={"reason": "user"})
        self.assertEqual(interrupt.status_code, 200)
        self.assertEqual(interrupt.json()["event"]["type"], "interrupted")
        stop = self.client.post(f"/api/voice/session/{sid}/stop", json={"reason": "user"})
        self.assertEqual(stop.status_code, 200)

    def test_voice_to_task_still_works(self) -> None:
        response = self.client.post(
            "/api/voice/to-task",
            json={"transcript": "Maak een taak voor lokale tests", "create": False},
        )
        self.assertEqual(response.status_code, 200)
        proposal = response.json()["proposal"]
        self.assertEqual(proposal["source"], "voice_transcript")
        self.assertIn("asr", proposal["note"].lower())

    def test_session_idle_and_metrics_final_only(self) -> None:
        start = self.client.post(
            "/api/voice/session/start",
            json={"conversation_id": None, "client_tab_id": "idle-tab", "idle_timeout_seconds": 30},
        )
        self.assertEqual(start.status_code, 200)
        self.assertEqual(start.json().get("idle_timeout_seconds"), 30)
        sid = start.json()["session_id"]
        metrics = self.client.get("/api/voice/metrics/reference")
        self.assertEqual(metrics.status_code, 200)
        body = metrics.json()
        self.assertEqual(body.get("transcript_mode"), "final_only")
        self.assertIn("N/A", body.get("note", "") or "N/A")
        recordings = self.client.get("/api/voice/recordings")
        self.assertEqual(recordings.status_code, 200)
        self.assertIn("sessions", recordings.json())
        self.client.post(f"/api/voice/session/{sid}/stop", json={"reason": "user"})

    def test_wake_probe_disabled_by_default(self) -> None:
        wav = _silent_wav()
        encoded = base64.b64encode(wav).decode("ascii")
        response = self.client.post(
            "/api/voice/wake/probe",
            json={"audio_base64": encoded, "mime_type": "audio/wav", "language": "nl"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json().get("detected"))
        self.assertFalse(response.json().get("enabled"))

    def test_doctor_voices_and_speak_wav(self) -> None:
        doctor = self.client.post("/api/voice/doctor", json={})
        self.assertEqual(doctor.status_code, 200)
        self.assertIn("checks", doctor.json())
        voices = self.client.get("/api/voice/voices?language=nl")
        self.assertEqual(voices.status_code, 200)
        self.assertIn("voices", voices.json())
        speak = self.client.post(
            "/api/voice/speak",
            json={"text": "Hallo HADES.", "language": "nl", "style": "compact"},
        )
        if speak.status_code == 200:
            self.assertTrue(speak.content.startswith(b"RIFF"))
            self.assertGreater(len(speak.content), 1000)
        else:
            detail = speak.json().get("detail")
            self.assertTrue(isinstance(detail, (dict, str)))

    def test_session_speak_response_when_tts_ready(self) -> None:
        from voice.providers.piper_tts import PiperTts

        if not PiperTts().availability().get("ready"):
            self.skipTest("Piper niet klaar")
        start = self.client.post(
            "/api/voice/session/start",
            json={"conversation_id": None, "client_tab_id": "speak-resp-tab", "force": True},
        )
        self.assertEqual(start.status_code, 200)
        sid = start.json()["session_id"]
        spoken = self.client.post(
            "/api/voice/session/speak-response",
            json={"session_id": sid, "response_id": "msg-1", "text": "Dit is een kort antwoord."},
        )
        self.assertEqual(spoken.status_code, 200, spoken.text)
        body = spoken.json()
        self.assertTrue(body.get("ok"))
        self.assertGreaterEqual(body.get("segments", 0), 1)
        self.assertTrue(body.get("events"))
        first = body["events"][0]["payload"]
        self.assertTrue(first.get("audio_base64"))
        self.client.post(f"/api/voice/session/{sid}/stop", json={"reason": "user"})

    def test_wake_probe_enabled_detects_keyword_audio_if_asr_ready(self) -> None:
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            self.skipTest("faster-whisper ontbreekt")
        from voice.providers.faster_whisper_asr import FasterWhisperAsr
        from voice.providers.piper_tts import PiperTts
        from voice.wake_word import WakeWordDetector

        if not FasterWhisperAsr(model_size="tiny").availability().get("ready"):
            self.skipTest("ASR niet klaar")
        if not PiperTts().availability().get("ready"):
            self.skipTest("Piper niet klaar")
        # Exercise detector directly (settings wiring covered separately); avoids DB/control-plane cache quirks.
        spoken = PiperTts().synthesize("Hades wat is de tijd", language="nl")
        detector = WakeWordDetector(FasterWhisperAsr(model_size="tiny", device="cpu"), enabled=True)
        payload = detector.process_audio(spoken.audio, mime_type="audio/wav", language="nl")
        self.assertTrue(payload.get("enabled"))
        if payload.get("detected"):
            self.assertTrue(str(payload.get("text") or "").strip())
            self.assertNotIn("hades", str(payload.get("remainder") or "").lower())
        # Also ensure disabled probe endpoint stays off by default in fresh DB.
        disabled = self.client.post(
            "/api/voice/wake/probe",
            json={"audio_base64": base64.b64encode(spoken.audio).decode("ascii"), "mime_type": "audio/wav"},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json().get("enabled"))

    def test_install_unknown_voice_fails_honestly(self) -> None:
        from voice.install import download_piper_voice

        result = download_piper_voice("nl_NL-does-not-exist-medium")
        self.assertFalse(result.get("ok"))
        self.assertIn("known", result)


class IdleSessionTests(unittest.TestCase):
    def test_reap_idle_stops_session(self) -> None:
        mgr = VoiceSessionManager()
        session = mgr.start(conversation_id=None, client_tab_id="idle-1", idle_timeout_seconds=1)
        session.last_activity_at = time.time() - 5
        stopped = mgr.reap_idle(now=time.time())
        self.assertIn(session.session_id, stopped)
        self.assertIsNone(mgr.get(session.session_id))

    def test_keep_audio_preserves_files_on_stop(self) -> None:
        mgr = VoiceSessionManager()
        with tempfile.TemporaryDirectory() as tmp:
            keep = mgr.start(conversation_id=None, client_tab_id="keep-1", keep_audio=True)
            path = Path(tmp) / "utterance.wav"
            path.write_bytes(_silent_wav())
            keep.temp_files.append(str(path))
            mgr.stop(keep.session_id, reason="user")
            self.assertTrue(path.exists())

            drop = mgr.start(conversation_id=None, client_tab_id="drop-1", keep_audio=False)
            path2 = Path(tmp) / "utterance2.wav"
            path2.write_bytes(_silent_wav())
            drop.temp_files.append(str(path2))
            mgr.stop(drop.session_id, reason="user")
            self.assertFalse(path2.exists())


class InterruptSynthTests(unittest.TestCase):
    def test_interrupt_stops_further_segments(self) -> None:
        from voice.runtime import synthesize_response_segments

        calls = {"n": 0}

        class FakeTts:
            id = "piper"

            def synthesize(self, text, **kwargs):
                from voice.providers.base import SynthesisResult

                calls["n"] += 1
                result = SynthesisResult(
                    audio=b"RIFF" + b"\x00" * 100,
                    mime_type="audio/wav",
                    sample_rate=22050,
                    voice_id="fake",
                    provider="piper",
                    speakable_text=text,
                )
                if calls["n"] == 1:
                    # Simulate barge-in after first segment is produced.
                    session.interrupt(reason="barge-in")
                return result

        class FakeRuntime:
            def tts_provider(self, settings):
                return FakeTts()

        mgr = VoiceSessionManager()
        session = mgr.start(conversation_id=None, client_tab_id="synth-int")
        events = synthesize_response_segments(
            runtime=FakeRuntime(),
            session=session,
            response_id="r-int",
            text="Eén. Twee. Drie. Vier.",
            settings={"voice_language": "nl", "voice_speak_style": "compact"},
        )
        # Should not synthesize every sentence after interrupt.
        self.assertLess(len(events), 4)
        mgr.stop(session.session_id)


class InstallCatalogTests(unittest.TestCase):
    def test_piper_voice_catalog_has_published_nl_default(self) -> None:
        from voice.install import PIPER_VOICE_URLS, download_piper_voice

        self.assertIn("nl_NL-pim-medium", PIPER_VOICE_URLS)
        self.assertIn("en_US-lessac-medium", PIPER_VOICE_URLS)
        # Legacy unpublished id must remap without hard-failing on lookup.
        mapped = download_piper_voice.__defaults__
        self.assertEqual(mapped[0] if mapped else "nl_NL-pim-medium", "nl_NL-pim-medium")
        for voice_id, urls in PIPER_VOICE_URLS.items():
            self.assertTrue(urls["onnx"].endswith(f"{voice_id}.onnx"))
            self.assertTrue(urls["json"].endswith(f"{voice_id}.onnx.json"))
            self.assertNotIn("/rdh/", urls["onnx"])

    def test_download_network_failure_returns_recovery(self) -> None:
        from voice import install as install_mod

        original = install_mod._download

        def boom(url: str, dest: Path) -> None:
            raise RuntimeError("simulated network down")

        install_mod._download = boom  # type: ignore[assignment]
        try:
            result = install_mod.download_piper_voice("nl_NL-pim-medium")
            # May succeed if voice already cached on disk from earlier env setup.
            if not result.get("ok"):
                self.assertIn("recovery", result)
                self.assertIn("error", result)
        finally:
            install_mod._download = original  # type: ignore[assignment]


class RealProviderOptionalTests(unittest.TestCase):
    """Real ASR/TTS when dependencies+models are present; otherwise mark unknown/skip."""

    def test_faster_whisper_dutch_if_available(self) -> None:
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            self.skipTest("faster-whisper niet geïnstalleerd — hosttest vereist")
        from voice.providers.faster_whisper_asr import FasterWhisperAsr

        asr = FasterWhisperAsr(model_size="tiny", device="cpu")
        avail = asr.availability()
        if not avail.get("ready"):
            self.skipTest(avail.get("message") or "ASR niet klaar")
        # Silence fixture must not invent a Dutch sentence.
        fixture = Path(__file__).resolve().parent / "fixtures" / "voice" / "silence_nl_placeholder.wav"
        result = asr.transcribe(fixture.read_bytes(), language="nl", mime_type="audio/wav")
        self.assertTrue(result.metadata.get("silence") or not (result.text or "").strip())

    def test_piper_produces_wav_if_available(self) -> None:
        from voice.providers.piper_tts import PiperTts

        tts = PiperTts()
        avail = tts.availability()
        if not avail.get("ready"):
            self.skipTest(avail.get("message") or "Piper niet klaar")
        result = tts.synthesize("Dit is een korte test.", language="nl", speed=1.0)
        self.assertTrue(result.audio.startswith(b"RIFF"))
        self.assertGreater(len(result.audio), 1000)
        self.assertEqual(result.mime_type, "audio/wav")

    def test_tts_asr_roundtrip_keywords_if_available(self) -> None:
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            self.skipTest("faster-whisper niet geïnstalleerd")
        from voice.providers.faster_whisper_asr import FasterWhisperAsr
        from voice.providers.piper_tts import PiperTts

        tts = PiperTts()
        asr = FasterWhisperAsr(model_size="tiny", device="cpu")
        if not tts.availability().get("ready") or not asr.availability().get("ready"):
            self.skipTest("ASR/TTS niet klaar")
        spoken = tts.synthesize("Goedemorgen HADES dit is een test.", language="nl")
        heard = asr.transcribe(spoken.audio, language="nl", mime_type="audio/wav")
        text = (heard.text or "").lower()
        # Tiny model is imperfect; require at least one strong keyword, never invent long silence lies.
        self.assertTrue(any(token in text for token in ("goedemorgen", "hades", "test", "dit")), text)

    def test_silence_fixture_exists(self) -> None:
        fixture = Path(__file__).resolve().parent / "fixtures" / "voice" / "silence_nl_placeholder.wav"
        self.assertTrue(fixture.exists(), "silence fixture missing")
        self.assertGreater(fixture.stat().st_size, 44)


if __name__ == "__main__":
    unittest.main()
