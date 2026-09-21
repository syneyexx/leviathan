#!/usr/bin/env python3
"""HADES bridge for VoiceStudio — doctor + OpenAI-compatible API probe.

Uses only documented endpoints:
  GET  /v1/audio/voices
  POST /v1/audio/speech
  POST /v1/audio/transcriptions
"""
from __future__ import annotations

import argparse
import json
import shutil
import urllib.error
import urllib.request
from typing import Any

DEFAULT_UI = "http://127.0.0.1:3900"
DEFAULT_API = "http://127.0.0.1:3900/v1"
DEFAULT_IMAGE = "palashdeb/omnivoice-studio:stable"


def doctor() -> dict[str, Any]:
    docker = shutil.which("docker") or shutil.which("docker.exe")
    ready = bool(docker)
    payload: dict[str, Any] = {
        "ok": ready,
        "ready_to_start": ready,
        "docker": docker,
        "default_image": DEFAULT_IMAGE,
        "ui": DEFAULT_UI,
        "api": DEFAULT_API,
        "documented_endpoints": [
            "GET /v1/audio/voices",
            "POST /v1/audio/speech",
            "POST /v1/audio/transcriptions",
        ],
        "streaming_speech": False,
        "streaming_note": (
            "POST /v1/audio/speech returns a complete audio clip per request. "
            "HADES may chunk sentences for earlier first audio; that is not provider PCM streaming."
        ),
        "notes": [
            "Prefer official VoiceStudio desktop installers on Windows.",
            "HADES start uses the published Docker image when Docker is available.",
            "Configure HADES → Instellingen → Spraak to use this API as TTS/STT provider.",
            "Doctor fails closed when Docker is missing (HADES start path requires it).",
        ],
    }
    if not ready:
        payload["error"] = "missing_required:docker"
    return payload


def api_probe(base_url: str = DEFAULT_API) -> dict[str, Any]:
    base = (base_url or DEFAULT_API).rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    url = f"{base}/audio/voices"
    result: dict[str, Any] = {
        "ok": False,
        "url": url,
        "voices": [],
        "engines": [],
        "streaming_speech": False,
        "error": None,
    }
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        with urllib.request.urlopen(req, timeout=8) as response:  # noqa: S310 — local loopback probe
            payload = json.loads(response.read().decode("utf-8"))
        voices = list(payload.get("voices") or [])
        engines = list(payload.get("engines") or [])
        result["voices"] = voices
        result["engines"] = engines
        if not voices and not engines:
            result["error"] = "empty_voices_and_engines"
            return result
        result["ok"] = True
        return result
    except urllib.error.HTTPError as exc:
        result["error"] = f"HTTP {exc.code}: {exc.reason}"
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    probe = sub.add_parser("api_probe")
    probe.add_argument("--base-url", default=DEFAULT_API)
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok") else 2
    if args.cmd == "api_probe":
        payload = api_probe(args.base_url)
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok") else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
