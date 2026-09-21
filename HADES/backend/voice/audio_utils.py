"""Audio helpers: WAV encoding, sample-rate docs, silence detection.

Transport contract
------------------
* Browser capture preferred format for upload: ``audio/webm;codecs=opus`` or PCM WAV.
* Server ASR accepts WAV PCM 16-bit mono (any common rate; resampled as needed) and
  converts WebM/Ogg via ffmpeg when available.
* TTS output format: WAV PCM 16-bit mono at the voice sample rate (typically 22050 Hz for Piper).
* Browser MediaRecorder chunks are NOT treated as standalone valid files until the
  recorder is stopped and a complete Blob is assembled.
"""

from __future__ import annotations

import io
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

from voice.errors import VoiceProviderError

# Documented sample rates used by the voice pipeline.
CAPTURE_TARGET_RATE = 16000  # ASR-friendly mono PCM
TTS_DEFAULT_RATE = 22050  # Piper default family
PLAYBACK_MIME = "audio/wav"


def write_wav_pcm16(samples: bytes, *, sample_rate: int, channels: int = 1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples)
    return buffer.getvalue()


def read_wav_pcm16(data: bytes) -> tuple[bytes, int, int]:
    with wave.open(io.BytesIO(data), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if width != 2:
        raise VoiceProviderError("unsupported_wav", f"Alleen 16-bit PCM WAV wordt ondersteund (got {width * 8}-bit).")
    return frames, sample_rate, channels


def rms_level(pcm16: bytes) -> float:
    if len(pcm16) < 2:
        return 0.0
    count = len(pcm16) // 2
    total = 0.0
    for index in range(0, count * 2, 2):
        sample = struct.unpack_from("<h", pcm16, index)[0]
        total += float(sample * sample)
    return (total / max(1, count)) ** 0.5 / 32768.0


def is_silence(pcm16: bytes, *, threshold: float = 0.012, min_seconds: float = 0.0, sample_rate: int = 16000) -> bool:
    if min_seconds > 0:
        duration = (len(pcm16) / 2) / max(1, sample_rate)
        if duration < min_seconds:
            return True
    return rms_level(pcm16) < threshold


def ensure_wav_mono16(audio: bytes, mime_type: str = "audio/wav", *, target_rate: int = CAPTURE_TARGET_RATE) -> tuple[bytes, int]:
    """Normalize arbitrary browser audio bytes to mono 16-bit WAV at target_rate."""
    mime = (mime_type or "audio/wav").split(";")[0].strip().lower()
    if mime in {"audio/wav", "audio/x-wav", "audio/wave"} and audio[:4] == b"RIFF":
        frames, rate, channels = read_wav_pcm16(audio)
        if channels > 1:
            # Downmix by taking left channel.
            out = bytearray()
            frame_size = 2 * channels
            for offset in range(0, len(frames) - frame_size + 1, frame_size):
                out.extend(frames[offset : offset + 2])
            frames = bytes(out)
        if rate != target_rate:
            frames = _resample_pcm16(frames, rate, target_rate)
            rate = target_rate
        return write_wav_pcm16(frames, sample_rate=rate), rate

    # Convert via ffmpeg for webm/ogg/mp3/etc.
    ffmpeg = _which_ffmpeg()
    if not ffmpeg:
        raise VoiceProviderError(
            "ffmpeg_missing",
            "Kan browseraudio niet converteren: ffmpeg ontbreekt.",
            recovery="Installeer ffmpeg of stuur WAV PCM 16-bit mono.",
        )
    suffix = {
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".mp4",
        "audio/x-m4a": ".m4a",
    }.get(mime, ".bin")
    with tempfile.TemporaryDirectory(prefix="hades-voice-") as tmp:
        src = Path(tmp) / f"in{suffix}"
        dst = Path(tmp) / "out.wav"
        src.write_bytes(audio)
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            str(target_rate),
            "-sample_fmt",
            "s16",
            str(dst),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:400]
            raise VoiceProviderError("audio_convert_failed", f"Audio conversie mislukt: {detail}", recovery="Probeer opnieuw of gebruik een ander microfoonformaat.") from exc
        except subprocess.TimeoutExpired as exc:
            raise VoiceProviderError("audio_convert_timeout", "Audio conversie time-out.", recovery="Kortere opname proberen.") from exc
        data = dst.read_bytes()
    return data, target_rate


def _resample_pcm16(frames: bytes, src_rate: int, dst_rate: int) -> bytes:
    if src_rate == dst_rate or not frames:
        return frames
    import array

    samples = array.array("h")
    samples.frombytes(frames)
    if not samples:
        return frames
    ratio = dst_rate / src_rate
    out_len = max(1, int(len(samples) * ratio))
    out = array.array("h", [0] * out_len)
    for i in range(out_len):
        src_pos = i / ratio
        left = int(src_pos)
        right = min(left + 1, len(samples) - 1)
        frac = src_pos - left
        out[i] = int(samples[left] * (1 - frac) + samples[right] * frac)
    return out.tobytes()


def _which_ffmpeg() -> str | None:
    from shutil import which

    return which("ffmpeg")


def audio_format_docs() -> dict[str, Any]:
    return {
        "capture_target_rate": CAPTURE_TARGET_RATE,
        "tts_default_rate": TTS_DEFAULT_RATE,
        "playback_mime": PLAYBACK_MIME,
        "notes": [
            "Browser MediaRecorder chunks are incomplete until stop(); do not POST partial chunks as files.",
            "ASR input is normalized to mono PCM16 WAV @ 16 kHz.",
            "TTS output is mono PCM16 WAV at the voice sample rate.",
        ],
    }
