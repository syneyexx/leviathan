"""Local ASR via faster-whisper (CTranslate2). CPU always available; CUDA when configured."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from voice import VOICE_DATA_DIR
from voice.audio_utils import ensure_wav_mono16, is_silence, rms_level, read_wav_pcm16
from voice.errors import VoiceProviderError
from voice.providers.base import AsrProvider, TranscriptResult

logger = logging.getLogger("hades.voice.asr")

DEFAULT_MODEL = "base"
SUPPORTED_MODELS = ("tiny", "base", "small", "medium", "large-v3")


class FasterWhisperAsr(AsrProvider):
    id = "faster_whisper"
    label = "Faster-Whisper (lokaal)"

    def __init__(self, *, model_size: str = DEFAULT_MODEL, device: str = "auto", compute_type: str = "auto", download_root: Path | None = None):
        self.model_size = model_size if model_size in SUPPORTED_MODELS else DEFAULT_MODEL
        self.device_pref = device
        self.compute_type_pref = compute_type
        self.download_root = Path(download_root or (VOICE_DATA_DIR / "whisper"))
        self.download_root.mkdir(parents=True, exist_ok=True)
        self._model = None
        self._model_key: str | None = None
        self._lock = threading.RLock()
        self._cancel = threading.Event()

    def availability(self) -> dict[str, Any]:
        try:
            import faster_whisper  # noqa: F401
        except Exception as exc:
            return {
                "ready": False,
                "provider": self.id,
                "status": "dependency_missing",
                "message": "faster-whisper is niet geïnstalleerd.",
                "recovery": "Open Instellingen → Spraak → Installatie, of voer pip install -r backend/voice/requirements-voice.txt uit.",
                "error": str(exc),
            }
        model_dir = self.download_root / self.model_size
        loaded = self._model is not None and self._model_key == self._cache_key()
        cached = model_dir.exists() or loaded
        # Package import alone is not "ready" — model must be cached/loaded for operational ASR.
        return {
            "ready": bool(cached),
            "provider": self.id,
            "status": "ready" if loaded else ("model_cached" if cached else "model_not_cached"),
            "model": self.model_size,
            "model_cached": cached,
            "device": self._resolve_device(),
            "compute_type": self._resolve_compute_type(),
            "supported_models": list(SUPPORTED_MODELS),
            "languages": self.supported_languages(),
            "message": (
                "Faster-Whisper beschikbaar."
                if loaded or cached
                else "faster-whisper geïnstalleerd, maar model is niet gecached — nog niet operationally ready (geen cloud fallback)."
            ),
            "unverified_on_host": not cached,
        }

    def supported_languages(self) -> list[str]:
        return ["nl", "en", "auto"]

    def model_status(self) -> dict[str, Any]:
        avail = self.availability()
        return {
            "loaded": self._model is not None and self._model_key == self._cache_key(),
            "model": self.model_size,
            "device": self._resolve_device(),
            "compute_type": self._resolve_compute_type(),
            "download_root": str(self.download_root),
            **{k: avail.get(k) for k in ("ready", "status", "model_cached", "message")},
        }

    def transcribe(
        self,
        audio: bytes,
        *,
        language: str | None = None,
        mime_type: str = "audio/wav",
        cancel_check: Any | None = None,
    ) -> TranscriptResult:
        self._cancel.clear()
        wav_bytes, rate = ensure_wav_mono16(audio, mime_type)
        frames, rate, _channels = read_wav_pcm16(wav_bytes)
        level = rms_level(frames)
        if is_silence(frames, threshold=0.012, sample_rate=rate):
            return TranscriptResult(
                text="",
                language=language if language and language != "auto" else None,
                is_partial=False,
                confidence=None,
                duration_seconds=len(frames) / 2 / rate,
                provider=self.id,
                model=self.model_size,
                metadata={"silence": True, "rms": level},
            )

        model = self._ensure_model()
        lang = None if not language or language == "auto" else language
        if cancel_check and callable(cancel_check) and cancel_check():
            raise VoiceProviderError("cancelled", "Transcriptie geannuleerd.")

        segments_text: list[str] = []
        info = None
        try:
            segments, info = model.transcribe(
                self._wav_path(wav_bytes),
                language=lang,
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            for segment in segments:
                if self._cancel.is_set() or (cancel_check and callable(cancel_check) and cancel_check()):
                    raise VoiceProviderError("cancelled", "Transcriptie geannuleerd.")
                piece = (segment.text or "").strip()
                if piece:
                    segments_text.append(piece)
        except VoiceProviderError:
            raise
        except Exception as exc:
            logger.exception("faster-whisper transcribe failed")
            raise VoiceProviderError(
                "asr_failed",
                f"Spraakherkenning mislukt: {exc}",
                recovery="Controleer het model of probeer een kortere opname.",
                details={"error": str(exc)},
            ) from exc

        text = " ".join(segments_text).strip()
        detected = getattr(info, "language", None) if info is not None else lang
        # faster-whisper does not always expose a reliable per-utterance confidence; do not invent one.
        return TranscriptResult(
            text=text,
            language=detected,
            is_partial=False,
            confidence=None,
            duration_seconds=len(frames) / 2 / rate,
            provider=self.id,
            model=self.model_size,
            metadata={"rms": level, "vad_filter": True},
        )

    def cancel(self) -> None:
        self._cancel.set()

    def unload(self) -> None:
        with self._lock:
            self._model = None
            self._model_key = None

    def _ensure_model(self):
        key = self._cache_key()
        with self._lock:
            if self._model is not None and self._model_key == key:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except Exception as exc:
                raise VoiceProviderError(
                    "dependency_missing",
                    "faster-whisper is niet geïnstalleerd.",
                    recovery="Instellingen → Spraak → Installatie uitvoeren.",
                ) from exc
            device = self._resolve_device()
            compute_type = self._resolve_compute_type(device)
            try:
                self._model = WhisperModel(
                    self.model_size,
                    device=device,
                    compute_type=compute_type,
                    download_root=str(self.download_root),
                )
            except Exception as exc:
                if device != "cpu":
                    logger.warning("CUDA whisper load failed (%s); falling back to CPU", exc)
                    self._model = WhisperModel(
                        self.model_size,
                        device="cpu",
                        compute_type="int8",
                        download_root=str(self.download_root),
                    )
                else:
                    raise VoiceProviderError("model_load_failed", f"Whisper-model laden mislukt: {exc}", recovery="Controleer schijfruimte en herstart de installatie.") from exc
            self._model_key = key
            return self._model

    def _cache_key(self) -> str:
        return f"{self.model_size}:{self._resolve_device()}:{self._resolve_compute_type()}"

    def _resolve_device(self) -> str:
        pref = (self.device_pref or "auto").lower()
        if pref == "cpu":
            return "cpu"
        if pref == "cuda":
            return "cuda"
        # auto
        try:
            import ctranslate2

            if "cuda" in (ctranslate2.get_supported_compute_types("cuda") or []):
                return "cuda"
        except Exception:
            pass
        return "cpu"

    def _resolve_compute_type(self, device: str | None = None) -> str:
        pref = (self.compute_type_pref or "auto").lower()
        if pref != "auto":
            return pref
        device = device or self._resolve_device()
        return "float16" if device == "cuda" else "int8"

    def _wav_path(self, wav_bytes: bytes) -> str:
        import tempfile

        handle = tempfile.NamedTemporaryFile(prefix="hades-asr-", suffix=".wav", delete=False)
        handle.write(wav_bytes)
        handle.close()
        # Caller relies on OS temp cleanup; keep path for whisper file API.
        path = handle.name
        # Register for best-effort cleanup after a delay via finalize on next call
        if not hasattr(self, "_temp_files"):
            self._temp_files: list[str] = []
        for old in list(self._temp_files):
            try:
                Path(old).unlink(missing_ok=True)
            except Exception:
                pass
            self._temp_files.remove(old)
        self._temp_files.append(path)
        return path
