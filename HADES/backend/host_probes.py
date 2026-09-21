"""Host capability probe helpers used by verify_hades.py.

Separated so Linux unit tests can exercise honesty rules without live LM Studio,
Puppeteer, or physical audio hardware.
"""

from __future__ import annotations

import json
import os
import struct
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]


def host_row(
    capability: str,
    *,
    implemented: bool,
    available_on_host: bool,
    simulated: bool,
    operationally_tested: bool,
    quality_evaluated: bool,
    evidence: Any = None,
    failure_reason: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    if status is None:
        if not available_on_host:
            status = "UNVERIFIED_ON_HOST"
        elif operationally_tested and (quality_evaluated or evidence is not None):
            status = "PASS"
        elif operationally_tested:
            status = "PASS"
        elif simulated:
            status = "SIMULATED_ONLY"
        else:
            status = "UNVERIFIED_ON_HOST"
    return {
        "capability": capability,
        "implemented": implemented,
        "available_on_host": available_on_host,
        "simulated": simulated,
        "operationally_tested": operationally_tested,
        "quality_evaluated": quality_evaluated,
        "timestamp": time.time(),
        "evidence": evidence,
        "failure_reason": failure_reason,
        "status": status,
    }


def judge_lm_studio_chat_response(
    *,
    transport_ok: bool,
    http_status: int | None,
    body: dict[str, Any] | None,
    transport_error: str | None = None,
) -> dict[str, Any]:
    """Separate transport reachability from successful inference.

    HTTP 200 with empty completion / missing choices is NOT PASS.
    """
    if not transport_ok:
        return {
            "transport_reachable": False,
            "inference_ok": False,
            "status": "UNVERIFIED_ON_HOST",
            "failure_reason": transport_error or "transport_unreachable",
            "content": "",
        }
    if http_status is None or http_status >= 400:
        return {
            "transport_reachable": True,
            "inference_ok": False,
            "status": "DEGRADED",
            "failure_reason": f"chat_http_{http_status}",
            "content": "",
        }
    body = body or {}
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return {
            "transport_reachable": True,
            "inference_ok": False,
            "status": "DEGRADED",
            "failure_reason": "empty_or_missing_choices",
            "content": "",
        }
    message = (choices[0] or {}).get("message") if isinstance(choices[0], dict) else None
    content = ""
    if isinstance(message, dict):
        content = str(message.get("content") or "")
    # Some servers put text on choices[0].text
    if not content and isinstance(choices[0], dict):
        content = str(choices[0].get("text") or "")
    content = content.strip()
    if not content:
        return {
            "transport_reachable": True,
            "inference_ok": False,
            "status": "DEGRADED",
            "failure_reason": "empty_completion_content",
            "content": "",
        }
    return {
        "transport_reachable": True,
        "inference_ok": True,
        "status": "PASS",
        "failure_reason": None,
        "content": content,
    }


def probe_lm_studio(*, client_factory: Callable[[float], Any] | None = None) -> dict[str, Any]:
    try:
        import httpx
        from database import DEFAULT_SETTINGS
    except Exception as exc:
        return host_row(
            "lm_studio",
            implemented=True,
            available_on_host=False,
            simulated=False,
            operationally_tested=False,
            quality_evaluated=False,
            failure_reason=str(exc),
            status="UNVERIFIED_ON_HOST",
        )

    base = str(DEFAULT_SETTINGS.get("lm_studio_base_url") or "http://127.0.0.1:1234/v1").rstrip("/")
    factory = client_factory or (lambda timeout: httpx.Client(timeout=timeout))

    try:
        with factory(3.0) as client:
            models = client.get(f"{base}/models")
        if models.status_code >= 400:
            return host_row(
                "lm_studio",
                implemented=True,
                available_on_host=True,
                simulated=False,
                operationally_tested=False,
                quality_evaluated=False,
                failure_reason=f"models_http_{models.status_code}",
                evidence={"base_url": base, "transport_reachable": True, "inference_ok": False},
                status="DEGRADED",
            )
        data = models.json()
        ids = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")]
        if not ids:
            return host_row(
                "lm_studio",
                implemented=True,
                available_on_host=True,
                simulated=False,
                operationally_tested=False,
                quality_evaluated=False,
                failure_reason="no_models_discovered",
                evidence={"base_url": base, "transport_reachable": True, "inference_ok": False},
                status="DEGRADED",
            )
        model_id = ids[0]
        with factory(60.0) as client:
            chat = client.post(
                f"{base}/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "Reply with exactly: HADES_LIVE_OK"}],
                    "temperature": 0,
                    "max_tokens": 32,
                },
            )
        body: dict[str, Any] | None
        try:
            body = chat.json() if chat.status_code < 500 else {"error": chat.text[:500]}
        except Exception:
            body = {"error": (chat.text or "")[:500]}
        judged = judge_lm_studio_chat_response(
            transport_ok=True,
            http_status=chat.status_code,
            body=body if isinstance(body, dict) else None,
        )
        return host_row(
            "lm_studio",
            implemented=True,
            available_on_host=True,
            simulated=False,
            operationally_tested=bool(judged["inference_ok"]),
            quality_evaluated=False,
            evidence={
                "base_url": base,
                "model_id": model_id,
                "transport_reachable": judged["transport_reachable"],
                "inference_ok": judged["inference_ok"],
                "reply_preview": (judged.get("content") or "")[:200],
                "http_status": chat.status_code,
            },
            failure_reason=judged.get("failure_reason"),
            status=judged["status"],
        )
    except Exception as exc:
        return host_row(
            "lm_studio",
            implemented=True,
            available_on_host=False,
            simulated=False,
            operationally_tested=False,
            quality_evaluated=False,
            failure_reason=str(exc),
            evidence={"base_url": base, "transport_reachable": False, "inference_ok": False},
            status="UNVERIFIED_ON_HOST",
        )


def _write_fixture_html(path: Path) -> None:
    path.write_text(
        "<!DOCTYPE html><html><head><title>HADES_BROWSER_PROBE</title></head>"
        "<body><h1>HADES_BROWSER_PROBE_OK</h1><p>local fixture</p></body></html>",
        encoding="utf-8",
    )


def probe_browser(*, repo_root: Path | None = None) -> dict[str, Any]:
    """Attempt a real PluginManager invoke against a local fixture page when possible.

    Manifest presence alone never yields PASS.
    """
    root = repo_root or ROOT
    plugin_dir = root / "plugins" / "puppeteer"
    manifest = plugin_dir / "hades-plugin.json"
    if not manifest.exists():
        return host_row(
            "puppeteer_browser",
            implemented=True,
            available_on_host=False,
            simulated=False,
            operationally_tested=False,
            quality_evaluated=False,
            failure_reason="plugin_manifest_missing",
            status="UNAVAILABLE",
        )

    try:
        from platform_db import PlatformDatabase
        from platform_services import PluginManager
    except Exception as exc:
        return host_row(
            "puppeteer_browser",
            implemented=True,
            available_on_host=False,
            simulated=False,
            operationally_tested=False,
            quality_evaluated=False,
            failure_reason=f"plugin_manager_import_failed:{exc}",
            evidence={"manifest_present": True},
            status="UNVERIFIED_ON_HOST",
        )

    tmp = tempfile.TemporaryDirectory(prefix="hades_browser_probe_")
    try:
        data_root = Path(tmp.name)
        fixture = data_root / "fixture.html"
        _write_fixture_html(fixture)
        fixture_url = fixture.resolve().as_uri()
        db = PlatformDatabase(str(data_root / "probe.db"))
        db.initialize()
        manager = PluginManager(db, data_root / "data")
        try:
            imported = manager.import_local_folder(plugin_dir, install_dependencies=False)
        except Exception as exc:
            return host_row(
                "puppeteer_browser",
                implemented=True,
                available_on_host=False,
                simulated=False,
                operationally_tested=False,
                quality_evaluated=False,
                failure_reason=f"import_local_folder_failed:{exc}",
                evidence={"manifest_present": True, "fixture_url": fixture_url},
                status="UNVERIFIED_ON_HOST",
            )
        plugin = imported.get("plugin") or {}
        plugin_id = plugin.get("id") or "puppeteer"
        status = plugin.get("status")
        if status != "ready":
            return host_row(
                "puppeteer_browser",
                implemented=True,
                available_on_host=False,
                simulated=False,
                operationally_tested=False,
                quality_evaluated=False,
                failure_reason=f"plugin_not_ready:status={status}:failure_state={plugin.get('failure_state')}",
                evidence={
                    "manifest_present": True,
                    "plugin_status": status,
                    "note": "Manifest≠Ready; PluginManager Ready required for live invoke",
                },
                status="UNAVAILABLE",
            )
        try:
            result = manager.invoke(
                plugin_id,
                "fetch",
                {"url": fixture_url, "max_chars": 5000},
                timeout=90,
                invocation_type="manual",
                approved_by_user=True,
            )
        except Exception as exc:
            return host_row(
                "puppeteer_browser",
                implemented=True,
                available_on_host=True,
                simulated=False,
                operationally_tested=False,
                quality_evaluated=False,
                failure_reason=f"invoke_failed:{exc}",
                evidence={"manifest_present": True, "plugin_status": status, "fixture_url": fixture_url},
                status="UNVERIFIED_ON_HOST",
            )
        stdout = str(result.get("stdout") or "")
        ok = (
            result.get("status") == "completed"
            and "HADES_BROWSER_PROBE_OK" in stdout
        )
        if ok:
            return host_row(
                "puppeteer_browser",
                implemented=True,
                available_on_host=True,
                simulated=False,
                operationally_tested=True,
                quality_evaluated=False,
                evidence={
                    "manifest_present": True,
                    "plugin_status": status,
                    "fixture_url": fixture_url,
                    "invoke_status": result.get("status"),
                    "stdout_preview": stdout[:400],
                },
                status="PASS",
            )
        return host_row(
            "puppeteer_browser",
            implemented=True,
            available_on_host=True,
            simulated=False,
            operationally_tested=False,
            quality_evaluated=False,
            failure_reason="invoke_completed_without_fixture_marker",
            evidence={
                "manifest_present": True,
                "plugin_status": status,
                "fixture_url": fixture_url,
                "invoke_status": result.get("status"),
                "stderr_preview": str(result.get("stderr") or "")[:400],
                "stdout_preview": stdout[:400],
            },
            status="UNVERIFIED_ON_HOST",
        )
    finally:
        tmp.cleanup()


def _minimal_wav_bytes(*, seconds: float = 0.2, rate: int = 16000) -> bytes:
    import io

    nframes = int(rate * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        # Quiet tone-ish PCM (not silence-only, still tiny amplitude).
        frames = bytearray()
        for i in range(nframes):
            sample = int(500 * (1 if (i // 40) % 2 == 0 else -1))
            frames.extend(struct.pack("<h", sample))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def _wav_header_ok(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def probe_voice(*, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Voice probe with separated axes: deps/modelcache, ASR fixture, TTS file, mic, playback."""
    try:
        from database import DEFAULT_SETTINGS
        from voice.install import doctor
    except Exception as exc:
        return host_row(
            "voice_physical",
            implemented=True,
            available_on_host=False,
            simulated=False,
            operationally_tested=False,
            quality_evaluated=False,
            failure_reason=str(exc),
            status="UNVERIFIED_ON_HOST",
        )

    cfg = dict(DEFAULT_SETTINGS)
    if settings:
        cfg.update(settings)

    axes: dict[str, Any] = {
        "config": {
            "voice_asr_provider": cfg.get("voice_asr_provider"),
            "voice_asr_model": cfg.get("voice_asr_model"),
            "voice_tts_provider": cfg.get("voice_tts_provider"),
            "voice_tts_voice": cfg.get("voice_tts_voice"),
        },
        "deps_modelcache": {"ok": False, "detail": None},
        "asr_wav_fixture": {"ok": False, "detail": None},
        "tts_playable_file": {"ok": False, "detail": None},
        "physical_mic": {"ok": False, "detail": "not_probed_no_capture_device_api"},
        "physical_playback": {"ok": False, "detail": "not_probed_no_output_device_api"},
    }

    report = doctor(cfg)
    deps_ok = bool(report.get("ready"))
    axes["deps_modelcache"] = {
        "ok": deps_ok,
        "detail": "doctor_ready" if deps_ok else "asr_tts_or_ffmpeg_not_ready",
        "checks": report.get("checks"),
    }

    # ASR WAV fixture — only attempt when deps look ready; never PASS from doctor alone.
    asr_attempted = False
    if deps_ok:
        asr_attempted = True
        try:
            from voice.runtime import VoiceRuntime

            runtime = VoiceRuntime()
            asr = runtime.asr_provider(cfg)
            wav = _minimal_wav_bytes()
            result = asr.transcribe(wav, language=str(cfg.get("voice_language") or "en"), mime_type="audio/wav")
            text = str((result or {}).get("text") or (result or {}).get("transcript") or "")
            axes["asr_wav_fixture"] = {
                "ok": True,
                "detail": "transcribe_returned",
                "text_preview": text[:120],
            }
        except Exception as exc:
            axes["asr_wav_fixture"] = {"ok": False, "detail": f"asr_fixture_failed:{exc}"}

    # TTS playable file
    tts_attempted = False
    if deps_ok:
        tts_attempted = True
        try:
            from voice.runtime import VoiceRuntime

            runtime = VoiceRuntime()
            tts = runtime.tts_provider(cfg)
            synth = tts.synthesize("HADES probe", voice_id=cfg.get("voice_tts_voice"), language=str(cfg.get("voice_language") or "en"))
            audio = b""
            if isinstance(synth, dict):
                audio = synth.get("audio") or synth.get("audio_bytes") or b""
                if isinstance(audio, str):
                    # Some providers return path
                    p = Path(audio)
                    audio = p.read_bytes() if p.exists() else b""
            elif hasattr(synth, "audio"):
                audio = getattr(synth, "audio") or b""
            playable = isinstance(audio, (bytes, bytearray)) and (_wav_header_ok(bytes(audio)) or len(audio) > 44)
            axes["tts_playable_file"] = {
                "ok": bool(playable),
                "detail": "wav_or_audio_bytes" if playable else "tts_returned_empty_or_non_audio",
                "bytes": len(audio) if isinstance(audio, (bytes, bytearray)) else 0,
            }
        except Exception as exc:
            axes["tts_playable_file"] = {"ok": False, "detail": f"tts_fixture_failed:{exc}"}

    # Physical mic / playback stay honest unless a real device probe exists.
    try:
        import shutil

        arecord = shutil.which("arecord") or shutil.which("sox")
        axes["physical_mic"] = {
            "ok": False,
            "detail": "capture_binary_present_but_device_unverified" if arecord else "no_capture_binary",
            "binary": arecord,
        }
        aplay = shutil.which("aplay") or shutil.which("ffplay")
        axes["physical_playback"] = {
            "ok": False,
            "detail": "playback_binary_present_but_device_unverified" if aplay else "no_playback_binary",
            "binary": aplay,
        }
    except Exception as exc:
        axes["physical_mic"] = {"ok": False, "detail": str(exc)}
        axes["physical_playback"] = {"ok": False, "detail": str(exc)}

    operational = bool(axes["asr_wav_fixture"]["ok"] and axes["tts_playable_file"]["ok"])
    physical_ok = bool(axes["physical_mic"]["ok"] and axes["physical_playback"]["ok"])

    if operational and physical_ok:
        status = "PASS"
        failure = None
    elif operational:
        status = "UNVERIFIED_ON_HOST"
        failure = "asr_tts_fixture_ok_but_physical_mic_playback_unverified"
    elif deps_ok and (asr_attempted or tts_attempted):
        status = "DEGRADED"
        failure = "deps_present_but_asr_or_tts_fixture_failed"
    elif not deps_ok:
        status = "UNVERIFIED_ON_HOST"
        failure = "deps_or_modelcache_not_ready"
    else:
        status = "UNVERIFIED_ON_HOST"
        failure = "voice_probe_incomplete"

    return host_row(
        "voice_physical",
        implemented=True,
        available_on_host=bool(deps_ok or operational),
        simulated=False,
        operationally_tested=operational and physical_ok,
        quality_evaluated=False,
        evidence=axes,
        failure_reason=failure,
        status=status,
    )


STATUS_VOCABULARY = (
    "PASS",
    "FAIL",
    "SKIPPED",
    "UNAVAILABLE",
    "UNVERIFIED_ON_HOST",
    "DEGRADED",
    "SIMULATED_ONLY",
)
