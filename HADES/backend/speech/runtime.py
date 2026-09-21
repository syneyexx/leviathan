"""Speech runtime: generation tokens, barge-in, echo guard, provider dispatch."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import threading
import time
import urllib.parse
from typing import Any
from uuid import uuid4

from speech.memory_gate import evaluate_tts_memory_budget
from speech.speakable import join_preview_sample, prepare_speakable_text, split_speakable_chunks
from speech.voicestudio_client import VoiceStudioClient, engine_supported_settings, normalize_base_url

_RUNTIME: "SpeechRuntime | None" = None
_RUNTIME_LOCK = threading.Lock()


def _is_explicit_loopback_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
    except ValueError:
        return False
    if (parsed.scheme or "").lower() not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().strip("[]").rstrip(".")
    if not host:
        return False
    literal = host.split("%", 1)[0]
    try:
        return bool(ipaddress.ip_address(literal).is_loopback)
    except ValueError:
        return host == "localhost" or host.endswith(".localhost")


def _network_block_reason(cfg: dict[str, Any], url: str) -> str | None:
    if str(cfg.get("network_policy") or "").strip().lower() != "block":
        return None
    if _is_explicit_loopback_url(url):
        return None
    return (
        "network_policy=block blokkeert een externe VoiceStudio-endpoint. "
        "Gebruik een lokale localhost/loopback-endpoint of wijzig het netwerkbeleid bewust."
    )


def get_speech_runtime() -> "SpeechRuntime":
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            _RUNTIME = SpeechRuntime()
        return _RUNTIME


class SpeechRuntime:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._generation_id: str | None = None
        self._cancel_event = asyncio.Event()
        self._playback_active = False
        self._playback_until_ms = 0.0
        self._last_error: str | None = None
        self._inflight = 0

    def settings_from(self, values: dict[str, Any]) -> dict[str, Any]:
        provider = str(values.get("tts_provider") or "none").strip().lower()
        if provider not in {"none", "voicestudio"}:
            provider = "none"
        stt_provider = str(values.get("stt_provider") or "none").strip().lower()
        if stt_provider not in {"none", "voicestudio", "paste"}:
            stt_provider = "none"
        return {
            "network_policy": str(values.get("network_policy") or "").strip().lower(),
            "spoken_answers_enabled": bool(values.get("spoken_answers_enabled", False)),
            "tts_provider": provider,
            "tts_base_url": normalize_base_url(str(values.get("tts_base_url") or "http://127.0.0.1:3900/v1")),
            "tts_api_key": str(values.get("tts_api_key") or ""),
            "tts_voice_id": str(values.get("tts_voice_id") or "default"),
            "tts_model": str(values.get("tts_model") or "tts-1"),
            "tts_speed": float(values.get("tts_speed") or 1.0),
            "tts_language": str(values.get("tts_language") or values.get("language") or "nl"),
            "tts_response_format": str(values.get("tts_response_format") or "wav"),
            "tts_sentence_chunking": bool(values.get("tts_sentence_chunking", True)),
            "tts_min_free_ram_mb": int(values.get("tts_min_free_ram_mb") or 1500),
            "tts_min_free_vram_mb": int(values.get("tts_min_free_vram_mb") or 0),
            "tts_instruct": str(values.get("tts_instruct") or ""),
            "tts_description": str(values.get("tts_description") or ""),
            "stt_provider": stt_provider,
            "stt_base_url": normalize_base_url(
                str(values.get("stt_base_url") or values.get("tts_base_url") or "http://127.0.0.1:3900/v1")
            ),
            "stt_api_key": str(values.get("stt_api_key") or values.get("tts_api_key") or ""),
            "stt_model": str(values.get("stt_model") or "whisper-1"),
            "stt_language": str(values.get("stt_language") or values.get("language") or "nl"),
            "stt_echo_guard_ms": int(values.get("stt_echo_guard_ms") or 750),
        }

    def _tts_client(self, cfg: dict[str, Any]) -> VoiceStudioClient:
        return VoiceStudioClient(
            base_url=cfg["tts_base_url"],
            api_key=cfg["tts_api_key"],
            timeout_seconds=240.0,
        )

    def _stt_client(self, cfg: dict[str, Any]) -> VoiceStudioClient:
        return VoiceStudioClient(
            base_url=cfg["stt_base_url"],
            api_key=cfg["stt_api_key"],
            timeout_seconds=240.0,
        )

    async def status(self, values: dict[str, Any]) -> dict[str, Any]:
        cfg = self.settings_from(values)
        echo = self.echo_guard_state(cfg)
        base: dict[str, Any] = {
            "spoken_answers_enabled": cfg["spoken_answers_enabled"],
            "tts": {
                "provider": cfg["tts_provider"],
                "configured": cfg["tts_provider"] == "voicestudio",
                "available": False,
                "base_url": cfg["tts_base_url"],
                "voice_id": cfg["tts_voice_id"],
                "model": cfg["tts_model"],
                "streaming_speech": False,
                "sentence_chunking": cfg["tts_sentence_chunking"],
                "supported_settings": {"speed": True, "language": True, "voice": True, "model": True, "response_format": True},
                "engines": [],
                "voices": [],
                "version": None,
                "error": None,
                "recovery": [],
            },
            "stt": {
                "provider": cfg["stt_provider"],
                "configured": cfg["stt_provider"] in {"voicestudio", "paste"},
                "available": cfg["stt_provider"] == "paste",
                "base_url": cfg["stt_base_url"],
                "model": cfg["stt_model"],
                "error": None,
                "recovery": [],
                "note": (
                    "Spraakherkenning is apart configureerbaar van TTS. "
                    "Provider 'paste' blijft het bestaande transcript-plakpad."
                ),
            },
            "echo_guard": echo,
            "active_generation_id": self._generation_id,
            "inflight": self._inflight,
            "last_error": self._last_error,
            "lm_studio_independence": True,
            "note": "Stemprofiel en LM Studio-model zijn onafhankelijke instellingen.",
        }

        tts_network_error = (
            _network_block_reason(cfg, cfg["tts_base_url"])
            if cfg["tts_provider"] == "voicestudio"
            else None
        )
        stt_network_error = (
            _network_block_reason(cfg, cfg["stt_base_url"])
            if cfg["stt_provider"] == "voicestudio"
            else None
        )
        if tts_network_error:
            base["tts"]["error"] = tts_network_error
            base["tts"]["recovery"] = [
                {"id": "use_local_endpoint", "label": "Gebruik een lokale VoiceStudio localhost/loopback-endpoint"}
            ]
        if stt_network_error:
            base["stt"]["error"] = stt_network_error
            base["stt"]["recovery"] = [
                {"id": "use_local_endpoint", "label": "Gebruik een lokale VoiceStudio localhost/loopback-endpoint"}
            ]

        if cfg["tts_provider"] != "voicestudio":
            if cfg["spoken_answers_enabled"]:
                base["tts"]["error"] = "Gesproken antwoorden staat aan, maar er is geen TTS-provider geselecteerd."
                base["tts"]["recovery"] = [
                    {
                        "id": "select_provider",
                        "label": "Kies VoiceStudio onder Instellingen → Spraak",
                    }
                ]
            return base
        if tts_network_error:
            return base

        client = self._tts_client(cfg)
        probe = await client.probe()
        base["tts"]["available"] = bool(probe.get("ok"))
        base["tts"]["voices"] = probe.get("voices") or []
        base["tts"]["engines"] = probe.get("engines") or []
        base["tts"]["version"] = probe.get("version")
        base["tts"]["streaming_speech"] = False
        base["tts"]["streaming_note"] = probe.get("streaming_note")
        base["tts"]["error"] = probe.get("error")
        base["tts"]["recovery"] = probe.get("recovery") or []
        engine = _pick_engine(probe.get("engines") or [], cfg["tts_model"])
        base["tts"]["supported_settings"] = engine_supported_settings(engine, cfg["tts_model"])
        base["tts"]["selected_engine"] = engine

        if cfg["stt_provider"] == "voicestudio" and not stt_network_error:
            stt_client = self._stt_client(cfg)
            stt_probe = await stt_client.probe()
            base["stt"]["available"] = bool(stt_probe.get("ok"))
            base["stt"]["error"] = stt_probe.get("error")
            base["stt"]["recovery"] = stt_probe.get("recovery") or []

        return base

    async def begin(self, values: dict[str, Any], *, reason: str = "speak") -> dict[str, Any]:
        cfg = self.settings_from(values)
        if cfg["tts_provider"] != "voicestudio":
            raise RuntimeError("Geen TTS-provider geconfigureerd. Kies VoiceStudio onder Instellingen → Spraak.")
        network_error = _network_block_reason(cfg, cfg["tts_base_url"])
        if network_error:
            raise RuntimeError(network_error)
        async with self._lock:
            self._cancel_event.set()
            self._generation_id = f"speech_{uuid4().hex[:16]}"
            self._cancel_event = asyncio.Event()
            generation_id = self._generation_id
        return {
            "generation_id": generation_id,
            "reason": reason,
            "provider": "voicestudio",
            "streaming_speech": False,
            "sentence_chunking": cfg["tts_sentence_chunking"],
        }

    async def stop(self, *, generation_id: str | None = None) -> dict[str, Any]:
        async with self._lock:
            if generation_id and self._generation_id and generation_id != self._generation_id:
                return {
                    "stopped": False,
                    "reason": "stale_generation",
                    "active_generation_id": self._generation_id,
                }
            self._cancel_event.set()
            stopped_id = self._generation_id
            self._generation_id = None
            self._playback_active = False
            self._playback_until_ms = time.time() * 1000
        return {"stopped": True, "generation_id": stopped_id}

    def set_playback(self, *, active: bool, echo_guard_ms: int = 750) -> dict[str, Any]:
        self._playback_active = bool(active)
        if active:
            self._playback_until_ms = 0.0
        else:
            self._playback_until_ms = time.time() * 1000 + max(0, int(echo_guard_ms))
        return self.echo_guard_state({"stt_echo_guard_ms": echo_guard_ms})

    def echo_guard_state(self, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
        guard_ms = int((cfg or {}).get("stt_echo_guard_ms") or 750)
        now = time.time() * 1000
        blocked = self._playback_active or now < self._playback_until_ms
        remaining = 0
        if self._playback_active:
            remaining = guard_ms
        elif now < self._playback_until_ms:
            remaining = int(self._playback_until_ms - now)
        return {
            "blocked": blocked,
            "playback_active": self._playback_active,
            "remaining_ms": max(0, remaining),
            "reason": "tts_playback" if blocked else None,
            "note": "Blokkeert microfoon/STT zodat HADES-luidsprekeruitvoer niet als gebruikersinvoer wordt verwerkt.",
        }

    async def preview(self, values: dict[str, Any]) -> dict[str, Any]:
        cfg = self.settings_from(values)
        sample = join_preview_sample(cfg["tts_language"])
        began = await self.begin(values, reason="preview")
        try:
            return await self.synthesize_chunk(
                values,
                text=sample,
                generation_id=began["generation_id"],
                chunk_index=0,
                allow_empty=False,
            )
        except Exception:
            await self.stop(generation_id=began["generation_id"])
            raise

    async def speak_plan(self, values: dict[str, Any], *, text: str) -> dict[str, Any]:
        cfg = self.settings_from(values)
        speakable = prepare_speakable_text(text)
        if not speakable:
            raise ValueError("Geen voorleesbare tekst over na filteren van code/redenering/tooluitvoer.")
        began = await self.begin(values, reason="speak")
        if cfg["tts_sentence_chunking"]:
            chunks = split_speakable_chunks(speakable)
        else:
            chunks = [speakable]
        return {
            "generation_id": began["generation_id"],
            "provider": "voicestudio",
            "streaming_speech": False,
            "sentence_chunking": cfg["tts_sentence_chunking"],
            "chunk_count": len(chunks),
            "chunks": [{"index": index, "text": chunk} for index, chunk in enumerate(chunks)],
            "speakable_chars": len(speakable),
        }

    async def synthesize_chunk(
        self,
        values: dict[str, Any],
        *,
        text: str,
        generation_id: str,
        chunk_index: int = 0,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        cfg = self.settings_from(values)
        if cfg["tts_provider"] != "voicestudio":
            raise RuntimeError("VoiceStudio is niet geselecteerd als TTS-provider.")
        if not self._generation_id or generation_id != self._generation_id:
            raise InterruptedError("Deze spraakgeneratie is geannuleerd of verouderd.")
        if self._cancel_event.is_set():
            raise InterruptedError("Spraak geannuleerd.")

        speakable = prepare_speakable_text(text)
        if not speakable:
            if allow_empty:
                return {"skipped": True, "generation_id": generation_id, "chunk_index": chunk_index}
            raise ValueError("Lege voorleesbare tekst.")

        status = await self.status(values)
        if not status["tts"].get("available"):
            error = status["tts"].get("error") or "VoiceStudio niet beschikbaar."
            self._last_error = error
            raise RuntimeError(error)

        engine = status["tts"].get("selected_engine") or {}
        memory = evaluate_tts_memory_budget(
            min_free_ram_mb=cfg["tts_min_free_ram_mb"],
            min_free_vram_mb=cfg["tts_min_free_vram_mb"],
            engine_min_vram_gb=(engine.get("min_vram_gb") if isinstance(engine, dict) else None),
        )
        if not memory.get("ok"):
            self._last_error = "; ".join(memory.get("reasons") or ["Geheugenbudget geweigerd."])
            raise RuntimeError(self._last_error)

        supported = status["tts"].get("supported_settings") or {}
        extras: dict[str, Any] = {}
        if supported.get("instruct") and cfg["tts_instruct"]:
            extras["instruct"] = cfg["tts_instruct"]
        if supported.get("description") and cfg["tts_description"]:
            extras["description"] = cfg["tts_description"]

        client = self._tts_client(cfg)
        self._inflight += 1
        try:
            result = await client.synthesize(
                text=speakable,
                voice=cfg["tts_voice_id"],
                model=cfg["tts_model"],
                response_format=cfg["tts_response_format"],
                speed=cfg["tts_speed"],
                language=cfg["tts_language"],
                extras=extras,
                cancel_event=self._cancel_event,
            )
        except InterruptedError:
            self._last_error = "Spraak geannuleerd."
            raise
        except Exception as exc:
            self._last_error = str(exc)
            raise
        finally:
            self._inflight = max(0, self._inflight - 1)

        if not self._generation_id or generation_id != self._generation_id or self._cancel_event.is_set():
            raise InterruptedError("Spraakresultaat verworpen — nieuwere beurt of stop.")

        audio = result.get("audio") or b""
        if not audio:
            self._last_error = "VoiceStudio leverde lege audio."
            raise RuntimeError(self._last_error)

        audio_b64 = base64.b64encode(audio).decode("ascii")
        return {
            "generation_id": generation_id,
            "chunk_index": chunk_index,
            "text": speakable,
            "mime_type": result["mime_type"],
            "response_format": result["response_format"],
            "bytes": result["bytes"],
            "audio_base64": audio_b64,
            "voice": result["voice"],
            "model": result["model"],
            "provider": "voicestudio",
            "memory": memory,
            "streaming_speech": False,
        }

    async def transcribe(self, values: dict[str, Any], *, audio: bytes, filename: str = "audio.wav") -> dict[str, Any]:
        cfg = self.settings_from(values)
        echo = self.echo_guard_state(cfg)
        if echo.get("blocked"):
            raise RuntimeError(
                "Microfoon/STT geblokkeerd tijdens of kort na TTS-afspelen (echo-guard). "
                "Wacht tot de luidsprekeruitvoer klaar is."
            )
        if cfg["stt_provider"] != "voicestudio":
            raise RuntimeError(
                "STT-provider is niet VoiceStudio. Gebruik plakken (paste) of zet stt_provider op voicestudio."
            )
        network_error = _network_block_reason(cfg, cfg["stt_base_url"])
        if network_error:
            raise RuntimeError(network_error)
        client = self._stt_client(cfg)
        return await client.transcribe(
            audio=audio,
            filename=filename,
            model=cfg["stt_model"],
            language=cfg["stt_language"],
        )


def _pick_engine(engines: list[Any], model_id: str) -> dict[str, Any] | None:
    wanted = (model_id or "").strip().lower()
    typed = [item for item in engines if isinstance(item, dict)]
    if wanted in {"tts-1", "tts-1-hd", ""}:
        for item in typed:
            if item.get("available"):
                return item
        return typed[0] if typed else None
    for item in typed:
        if str(item.get("id") or "").lower() == wanted:
            return item
    return typed[0] if typed else None
