"""Install / doctor helpers for local voice dependencies and models."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable

from voice import VOICE_DATA_DIR

REQUIREMENTS = Path(__file__).resolve().parent / "requirements-voice.txt"

# Hugging Face Piper voice assets (onnx + json). User-triggered download only.
# Paths verified against rhasspy/piper-voices (rdh/nathalie are not published).
PIPER_VOICE_URLS = {
    "nl_NL-pim-medium": {
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/nl/nl_NL/pim/medium/nl_NL-pim-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/nl/nl_NL/pim/medium/nl_NL-pim-medium.onnx.json",
    },
    "nl_NL-mls-medium": {
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/nl/nl_NL/mls/medium/nl_NL-mls-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/nl/nl_NL/mls/medium/nl_NL-mls-medium.onnx.json",
    },
    "nl_NL-alex-medium": {
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/nl/nl_NL/alex/medium/nl_NL-alex-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/nl/nl_NL/alex/medium/nl_NL-alex-medium.onnx.json",
    },
    "nl_NL-ronnie-medium": {
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/nl/nl_NL/ronnie/medium/nl_NL-ronnie-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/nl/nl_NL/ronnie/medium/nl_NL-ronnie-medium.onnx.json",
    },
    "en_US-lessac-medium": {
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    },
}


ProgressCb = Callable[[dict[str, Any]], None]
VALID_INSTALL_STEPS = frozenset({"deps", "whisper", "piper_voice"})


def doctor(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    from voice.providers import list_provider_summaries
    from voice.audio_utils import audio_format_docs, _which_ffmpeg

    summaries = list_provider_summaries(settings)
    asr = summaries["asr"][0]
    tts = summaries["tts"][0]
    ffmpeg = bool(_which_ffmpeg())
    checks = [
        {"id": "ffmpeg", "ok": ffmpeg, "detail": "ffmpeg gevonden" if ffmpeg else "ffmpeg ontbreekt (nodig voor webm→wav)"},
        {"id": "asr", "ok": bool(asr.get("ready")), "detail": asr.get("message"), "recovery": asr.get("recovery")},
        {"id": "tts", "ok": bool(tts.get("ready")), "detail": tts.get("message"), "recovery": tts.get("recovery")},
        {"id": "voice_data_dir", "ok": VOICE_DATA_DIR.exists(), "detail": str(VOICE_DATA_DIR)},
    ]
    ready = all(item["ok"] for item in checks if item["id"] in {"asr", "tts", "ffmpeg"})
    return {
        "ready": ready,
        "checks": checks,
        "providers": summaries,
        "audio_formats": audio_format_docs(),
        "data_dir": str(VOICE_DATA_DIR),
        "requirements_file": str(REQUIREMENTS),
        "installable_voices": list(PIPER_VOICE_URLS.keys()),
        "notes": [
            "ffmpeg is required for browser MediaRecorder (webm/ogg) → WAV before ASR.",
            "ASR/TTS Python packages are optional core deps; install via Instellingen → Spraak.",
        ],
    }


def install_python_deps(*, progress: ProgressCb | None = None) -> dict[str, Any]:
    if progress:
        progress({"stage": "pip", "message": "Python-pakketten installeren…", "percent": 5})
    if not REQUIREMENTS.exists():
        return {"ok": False, "error": f"Ontbrekende requirements: {REQUIREMENTS}"}
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pip install time-out (20 min)."}
    if progress:
        progress({"stage": "pip", "message": "pip klaar" if proc.returncode == 0 else "pip mislukt", "percent": 40})
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


def ensure_whisper_model(model_size: str = "base", *, progress: ProgressCb | None = None) -> dict[str, Any]:
    if progress:
        progress({"stage": "whisper", "message": f"Whisper-model '{model_size}' laden…", "percent": 50})
    from voice.providers.faster_whisper_asr import FasterWhisperAsr

    asr = FasterWhisperAsr(model_size=model_size)
    try:
        asr._ensure_model()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "recovery": "Controleer netwerk voor eerste download of plaats modelbestanden handmatig."}
    if progress:
        progress({"stage": "whisper", "message": "Whisper-model gereed", "percent": 70})
    return {"ok": True, "model": model_size, "status": asr.model_status()}


def download_piper_voice(voice_id: str = "nl_NL-pim-medium", *, progress: ProgressCb | None = None) -> dict[str, Any]:
    # Map legacy / unpublished ids to a published Dutch medium voice.
    legacy = {
        "nl_NL-rdh-medium": "nl_NL-pim-medium",
        "nl_NL-nathalie-medium": "nl_NL-pim-medium",
    }
    voice_id = legacy.get(voice_id, voice_id)
    urls = PIPER_VOICE_URLS.get(voice_id)
    if not urls:
        return {"ok": False, "error": f"Onbekende stem: {voice_id}", "known": list(PIPER_VOICE_URLS)}
    voices_dir = VOICE_DATA_DIR / "piper" / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = voices_dir / f"{voice_id}.onnx"
    json_path = voices_dir / f"{voice_id}.onnx.json"
    try:
        if progress:
            progress({"stage": "piper_voice", "message": f"Download {voice_id}.onnx…", "percent": 75})
        if not onnx_path.exists() or onnx_path.stat().st_size <= 0:
            if onnx_path.exists():
                onnx_path.unlink(missing_ok=True)
            _download(urls["onnx"], onnx_path)
        if progress:
            progress({"stage": "piper_voice", "message": f"Download {voice_id}.onnx.json…", "percent": 90})
        if not json_path.exists() or json_path.stat().st_size <= 0:
            if json_path.exists():
                json_path.unlink(missing_ok=True)
            _download(urls["json"], json_path)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "recovery": "Zorg voor netwerk tijdens installatie, of kopieer .onnx + .onnx.json handmatig naar backend/data/voice/piper/voices/.",
        }
    if onnx_path.stat().st_size <= 0 or json_path.stat().st_size <= 0:
        for path in (onnx_path, json_path):
            try:
                if path.exists() and path.stat().st_size <= 0:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        return {
            "ok": False,
            "error": "empty_voice_artifact",
            "voice_id": voice_id,
            "recovery": "Verwijder lege stembestanden en installeer opnieuw, of kopieer geldige .onnx + .onnx.json.",
        }
    if progress:
        progress({"stage": "piper_voice", "message": "Stem geïnstalleerd", "percent": 100})
    return {"ok": True, "voice_id": voice_id, "onnx": str(onnx_path), "json": str(json_path)}


def run_install(steps: list[str] | None = None, *, settings: dict[str, Any] | None = None, progress: ProgressCb | None = None) -> dict[str, Any]:
    if steps is None:
        wanted = ["deps", "whisper", "piper_voice"]
    else:
        wanted = [str(step).strip() for step in steps if str(step).strip()]
        if not wanted:
            return {"ok": False, "error": "no_install_steps", "known_steps": sorted(VALID_INSTALL_STEPS)}
    unknown = sorted({step for step in wanted if step not in VALID_INSTALL_STEPS})
    if unknown:
        return {
            "ok": False,
            "error": "unknown_install_steps",
            "unknown_steps": unknown,
            "known_steps": sorted(VALID_INSTALL_STEPS),
        }

    results: dict[str, Any] = {}
    values = settings or {}
    if "deps" in wanted:
        results["deps"] = install_python_deps(progress=progress)
        if not results["deps"].get("ok"):
            return {"ok": False, "results": results}
    if "whisper" in wanted:
        results["whisper"] = ensure_whisper_model(str(values.get("voice_asr_model") or "base"), progress=progress)
        if not results["whisper"].get("ok"):
            return {"ok": False, "results": results}
    if "piper_voice" in wanted:
        voice_id = str(values.get("voice_tts_voice") or "nl_NL-pim-medium")
        results["piper_voice"] = download_piper_voice(voice_id, progress=progress)
        if not results["piper_voice"].get("ok"):
            return {"ok": False, "results": results}
    health = doctor(settings)
    ready = bool(health.get("ready"))
    return {
        "ok": ready,
        "results": results,
        "doctor": health,
        **({} if ready else {"error": "voice_doctor_not_ready"}),
    }


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    req = urllib.request.Request(url, headers={"User-Agent": "HADES-Voice/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
    if not tmp.exists() or tmp.stat().st_size <= 0:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(f"empty_download:{url}")
    os.replace(tmp, dest)
