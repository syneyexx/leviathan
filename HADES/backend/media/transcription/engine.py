
"""Transcription engine with source-hash caching."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from media.paths import content_hash_file


def _which_ffmpeg() -> str | None:
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def provider_config_hash(config: dict[str, Any] | None) -> str:
    payload = repr(sorted((config or {}).items())).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


class TranscriptionEngine:
    def __init__(self, store: Any, *, asr_callable: Callable[..., dict[str, Any]] | None = None) -> None:
        self.store = store
        self.asr_callable = asr_callable

    def extract_audio(self, media_path: Path, out_wav: Path) -> dict[str, Any]:
        ffmpeg = _which_ffmpeg()
        if not ffmpeg:
            return {"ok": False, "status": "SETUP_REQUIRED", "error": "ffmpeg_missing"}
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(media_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            str(out_wav),
        ]
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "status": "FAILED", "error": str(exc)}
        if completed.returncode != 0 or not out_wav.exists():
            return {
                "ok": False,
                "status": "FAILED",
                "error": (completed.stderr or completed.stdout or "audio_extract_failed")[:800],
            }
        return {"ok": True, "status": "READY", "path": str(out_wav)}

    def transcribe_source(
        self,
        *,
        source_id: str,
        media_path: Path | None = None,
        official_transcript: str | None = None,
        language: str = "",
        provider: str = "faster_whisper",
        provider_config: dict[str, Any] | None = None,
        tmp_dir: Path | None = None,
    ) -> dict[str, Any]:
        cfg_hash = provider_config_hash(provider_config)
        if media_path and media_path.exists():
            content_hash = content_hash_file(media_path)
        elif official_transcript is not None:
            content_hash = hashlib.sha256(official_transcript.encode("utf-8")).hexdigest()
            provider = "official_captions"
        else:
            return {"ok": False, "status": "FAILED", "error": "no_media_or_transcript"}

        cached = self.store.get_transcript_by_hash(content_hash, provider, cfg_hash)
        if cached:
            return {"ok": True, "status": "READY", "cached": True, "transcript": cached}

        if official_transcript is not None:
            segments = [{"start": 0.0, "end": None, "text": official_transcript}]
            saved = self.store.save_transcript(
                {
                    "source_id": source_id,
                    "content_hash": content_hash,
                    "provider": provider,
                    "language": language,
                    "confidence": None,
                    "segments": segments,
                    "words": [],
                    "full_text": official_transcript,
                    "provider_config_hash": cfg_hash,
                }
            )
            return {"ok": True, "status": "READY", "cached": False, "transcript": saved}

        if self.asr_callable is None:
            # Attempt local faster-whisper if present.
            try:
                from voice.providers.faster_whisper_asr import FasterWhisperAsr

                asr = FasterWhisperAsr()
                health = asr.health() if hasattr(asr, "health") else {"ok": True}
                if not health.get("ok", True):
                    return {"ok": False, "status": "SETUP_REQUIRED", "error": "asr_not_ready", "health": health}
                wav = None
                if media_path and media_path.suffix.lower() not in {".wav"}:
                    tmp = (tmp_dir or media_path.parent) / f"{media_path.stem}.16k.wav"
                    extracted = self.extract_audio(media_path, tmp)
                    if not extracted.get("ok"):
                        return extracted
                    wav = Path(extracted["path"])
                else:
                    wav = media_path
                assert wav is not None
                result = asr.transcribe(str(wav), language=language or None)
                text = str(result.get("text") or result.get("full_text") or "")
                segments = result.get("segments") or [{"start": 0.0, "end": None, "text": text}]
                words = result.get("words") or []
                saved = self.store.save_transcript(
                    {
                        "source_id": source_id,
                        "content_hash": content_hash,
                        "provider": provider,
                        "language": language or str(result.get("language") or ""),
                        "confidence": result.get("confidence"),
                        "segments": segments,
                        "words": words,
                        "full_text": text,
                        "provider_config_hash": cfg_hash,
                    }
                )
                return {"ok": True, "status": "READY", "cached": False, "transcript": saved}
            except Exception as exc:
                return {"ok": False, "status": "UNAVAILABLE", "error": f"asr_unavailable:{exc.__class__.__name__}"}

        result = self.asr_callable(media_path=media_path, language=language, config=provider_config or {})
        if not result.get("ok"):
            return result
        saved = self.store.save_transcript(
            {
                "source_id": source_id,
                "content_hash": content_hash,
                "provider": provider,
                "language": language or str(result.get("language") or ""),
                "confidence": result.get("confidence"),
                "segments": result.get("segments") or [],
                "words": result.get("words") or [],
                "full_text": result.get("full_text") or "",
                "provider_config_hash": cfg_hash,
            }
        )
        return {"ok": True, "status": "READY", "cached": False, "transcript": saved}
