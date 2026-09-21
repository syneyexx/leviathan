"""Local TTS via Piper (onnx voices). Dutch voice preferred when installed."""

from __future__ import annotations

import json
import logging
import shutil
import struct
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any

from voice import VOICE_DATA_DIR
from voice.errors import VoiceProviderError
from voice.providers.base import SynthesisResult, TtsProvider, VoiceInfo

logger = logging.getLogger("hades.voice.tts")

# Well-known Piper NL/EN voice ids (onnx + json pair under voices dir).
# Ids match published rhasspy/piper-voices paths used by install.PIPER_VOICE_URLS.
KNOWN_VOICES = [
    {"id": "nl_NL-pim-medium", "name": "Nederlands (pim medium)", "language": "nl", "gender": "male"},
    {"id": "nl_NL-mls-medium", "name": "Nederlands (mls medium)", "language": "nl", "gender": None},
    {"id": "nl_NL-alex-medium", "name": "Nederlands (alex medium)", "language": "nl", "gender": None},
    {"id": "nl_NL-ronnie-medium", "name": "Nederlands (ronnie medium)", "language": "nl", "gender": None},
    {"id": "en_US-lessac-medium", "name": "English (lessac medium)", "language": "en", "gender": "male"},
]


class PiperTts(TtsProvider):
    id = "piper"
    label = "Piper (lokaal)"

    def __init__(self, *, voices_dir: Path | None = None, piper_bin: str | None = None):
        self.voices_dir = Path(voices_dir or (VOICE_DATA_DIR / "piper" / "voices"))
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        self.piper_bin = piper_bin
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._python_voice = None
        self._python_voice_id: str | None = None

    def availability(self) -> dict[str, Any]:
        voices = self.list_voices()
        piper = self._resolve_piper_bin()
        has_python = self._has_piper_python()
        ready = bool(voices) and (bool(piper) or has_python)
        if not voices:
            status = "voices_missing"
            message = "Geen Piper-stemmen gevonden."
            recovery = "Download een Nederlandse stem via Instellingen → Spraak → Installatie."
        elif not piper and not has_python:
            status = "binary_missing"
            message = "Piper runtime ontbreekt (binary of piper-tts Python-pakket)."
            recovery = "Installeer piper of pip install piper-tts."
        else:
            status = "ready"
            message = "Piper TTS beschikbaar."
            recovery = None
        return {
            "ready": ready,
            "provider": self.id,
            "status": status,
            "message": message,
            "recovery": recovery,
            "piper_bin": piper,
            "python_api": has_python,
            "voices": [v.id for v in voices],
            "voice_count": len(voices),
            "offline": True,
        }

    def list_voices(self, language: str | None = None) -> list[VoiceInfo]:
        found: list[VoiceInfo] = []
        for onnx in sorted(self.voices_dir.glob("*.onnx")):
            voice_id = onnx.stem
            meta = self._read_voice_config(onnx)
            lang = str(meta.get("language", {}).get("code") or meta.get("language") or self._lang_from_id(voice_id))
            if isinstance(lang, dict):
                lang = str(lang.get("code") or "und")
            info = VoiceInfo(
                id=voice_id,
                name=str(meta.get("name") or voice_id),
                language=str(lang)[:8],
                gender=meta.get("gender"),
                sample_rate=int(meta.get("audio", {}).get("sample_rate") or 22050),
                offline=True,
                provider=self.id,
                path=str(onnx),
            )
            if language and language != "auto" and not str(info.language).startswith(language[:2]):
                continue
            found.append(info)
        # Also advertise known installable voices that are not yet present.
        present = {v.id for v in found}
        for known in KNOWN_VOICES:
            if known["id"] in present:
                continue
            if language and language != "auto" and not known["language"].startswith(language[:2]):
                continue
            # Skip advertising missing voices in list used for synthesis selection when not installed —
            # still useful for UI install prompts via availability.
        return found

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        language: str | None = None,
        speed: float = 1.0,
        cancel_check: Any | None = None,
    ) -> SynthesisResult:
        self._cancel.clear()
        cleaned = (text or "").strip()
        if not cleaned:
            raise VoiceProviderError("empty_text", "Geen tekst om uit te spreken.")

        voice = self._pick_voice(voice_id, language)
        if voice is None:
            raise VoiceProviderError(
                "voice_missing",
                "Geen Piper-stem beschikbaar.",
                recovery="Download een stem via Instellingen → Spraak → Installatie (bijv. nl_NL-pim-medium).",
            )
        if cancel_check and callable(cancel_check) and cancel_check():
            raise VoiceProviderError("cancelled", "Spraaksynthese geannuleerd.")

        length_scale = max(0.5, min(2.0, 1.0 / max(0.5, float(speed or 1.0))))
        try:
            audio = self._synthesize_with_binary(cleaned, voice, length_scale=length_scale)
        except VoiceProviderError as exc:
            if exc.code in {"binary_missing", "piper_failed"} and self._has_piper_python():
                audio = self._synthesize_with_python(cleaned, voice, length_scale=length_scale)
            else:
                raise

        if self._cancel.is_set() or (cancel_check and callable(cancel_check) and cancel_check()):
            raise VoiceProviderError("cancelled", "Spraaksynthese geannuleerd.")

        # Never return silence as a fake success.
        if not audio or len(audio) < 44 or audio[:4] != b"RIFF":
            raise VoiceProviderError("tts_empty", "TTS leverde geen afspeelbare audio.", recovery="Andere stem proberen of Piper herinstalleren.")

        return SynthesisResult(
            audio=audio,
            mime_type="audio/wav",
            sample_rate=voice.sample_rate,
            voice_id=voice.id,
            provider=self.id,
            speakable_text=cleaned,
            metadata={"length_scale": length_scale, "offline": True},
        )

    def cancel(self) -> None:
        self._cancel.set()

    def unload(self) -> None:
        with self._lock:
            self._python_voice = None
            self._python_voice_id = None

    def _pick_voice(self, voice_id: str | None, language: str | None) -> VoiceInfo | None:
        voices = self.list_voices()
        if not voices:
            return None
        if voice_id:
            for voice in voices:
                if voice.id == voice_id:
                    return voice
        lang = (language or "nl")[:2]
        for voice in voices:
            if str(voice.language).startswith(lang):
                return voice
        return voices[0]

    def _resolve_piper_bin(self) -> str | None:
        if self.piper_bin and Path(self.piper_bin).exists():
            return self.piper_bin
        bundled = VOICE_DATA_DIR / "piper" / ("piper.exe" if Path("C:/").exists() else "piper")
        # Prefer explicit env/path, then PATH, then optional bundle dir.
        found = shutil.which("piper") or shutil.which("piper.exe")
        if found:
            return found
        if bundled.exists():
            return str(bundled)
        return None

    def _has_piper_python(self) -> bool:
        try:
            import piper  # noqa: F401

            return True
        except Exception:
            return False

    def _synthesize_with_binary(self, text: str, voice: VoiceInfo, *, length_scale: float) -> bytes:
        piper = self._resolve_piper_bin()
        if not piper:
            raise VoiceProviderError("binary_missing", "Piper binary niet gevonden.", recovery="Installeer piper of gebruik piper-tts.")
        model_path = Path(voice.path or "")
        if not model_path.exists():
            raise VoiceProviderError("voice_missing", f"Stembestand ontbreekt: {voice.id}")
        with tempfile.TemporaryDirectory(prefix="hades-piper-") as tmp:
            out_path = Path(tmp) / "out.wav"
            cmd = [
                piper,
                "--model",
                str(model_path),
                "--output_file",
                str(out_path),
                "--length_scale",
                str(length_scale),
            ]
            try:
                subprocess.run(
                    cmd,
                    input=text.encode("utf-8"),
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:400]
                raise VoiceProviderError("piper_failed", f"Piper mislukt: {detail}", recovery="Controleer stem-bestanden (.onnx + .onnx.json).") from exc
            except subprocess.TimeoutExpired as exc:
                raise VoiceProviderError("piper_timeout", "Piper time-out.", recovery="Kortere tekst of andere stem.") from exc
            if not out_path.exists():
                raise VoiceProviderError("piper_failed", "Piper produceerde geen WAV.")
            return out_path.read_bytes()

    def _synthesize_with_python(self, text: str, voice: VoiceInfo, *, length_scale: float) -> bytes:
        try:
            from piper import PiperVoice
        except Exception as exc:
            raise VoiceProviderError("dependency_missing", "piper-tts Python-pakket ontbreekt.", recovery="pip install piper-tts") from exc
        model_path = Path(voice.path or "")
        with self._lock:
            if self._python_voice is None or self._python_voice_id != voice.id:
                self._python_voice = PiperVoice.load(str(model_path))
                self._python_voice_id = voice.id
            piper_voice = self._python_voice

        syn_config = None
        try:
            from piper.config import SynthesisConfig

            syn_config = SynthesisConfig(length_scale=length_scale)
        except Exception:
            syn_config = None

        # Prefer synthesize_wav when available (current piper-tts).
        if hasattr(piper_voice, "synthesize_wav"):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                with wave.open(str(tmp_path), "wb") as wav_file:
                    try:
                        if syn_config is not None:
                            piper_voice.synthesize_wav(text, wav_file, syn_config=syn_config)
                        else:
                            piper_voice.synthesize_wav(text, wav_file)
                    except TypeError:
                        # Older API variants.
                        try:
                            piper_voice.synthesize_wav(text, wav_file, length_scale=length_scale)
                        except TypeError:
                            piper_voice.synthesize_wav(text, wav_file)
                data = tmp_path.read_bytes()
                if data and data[:4] == b"RIFF":
                    return data
            finally:
                tmp_path.unlink(missing_ok=True)

        rows: list[bytes] = []
        sample_rate = voice.sample_rate
        chunks = None
        try:
            if syn_config is not None:
                chunks = piper_voice.synthesize(text, syn_config=syn_config)
            else:
                chunks = piper_voice.synthesize(text, length_scale=length_scale)
        except TypeError:
            chunks = piper_voice.synthesize(text)
        for chunk in chunks or []:
            audio_bytes = getattr(chunk, "audio_int16_bytes", None)
            if audio_bytes is None and hasattr(chunk, "audio_int16_array"):
                audio_bytes = chunk.audio_int16_array.tobytes()
            if audio_bytes:
                rows.append(audio_bytes)
            if getattr(chunk, "sample_rate", None):
                sample_rate = int(chunk.sample_rate)
        pcm = b"".join(rows)
        if not pcm:
            raise VoiceProviderError("tts_empty", "Piper Python-API leverde geen audio.")
        return _pcm16_to_wav(pcm, sample_rate)

    def _read_voice_config(self, onnx: Path) -> dict[str, Any]:
        cfg = Path(str(onnx) + ".json")
        if not cfg.exists():
            # Sometimes named stem.json
            alt = onnx.with_suffix(".onnx.json")
            cfg = alt if alt.exists() else onnx.with_suffix(".json")
        if not cfg.exists():
            return {"language": {"code": self._lang_from_id(onnx.stem)}}
        try:
            return json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            return {"language": {"code": self._lang_from_id(onnx.stem)}}

    @staticmethod
    def _lang_from_id(voice_id: str) -> str:
        if voice_id.startswith("nl"):
            return "nl"
        if voice_id.startswith("en"):
            return "en"
        return "und"


def _pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    import io

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()
