#!/usr/bin/env python3
"""Local ffmpeg clip tools for HADES (AutoClip / OpenMontage-compatible operations)."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _bin(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name + ".exe")


def doctor() -> dict:
    ffmpeg = _bin("ffmpeg")
    ffprobe = _bin("ffprobe")
    ok = bool(ffmpeg and ffprobe)
    payload = {
        "ok": ok,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "python": sys.executable,
        "notes": [
            "Cutting local files requires ffmpeg/ffprobe on PATH.",
            "This plugin does not call cloud video APIs.",
        ],
    }
    if not ok:
        payload["error"] = "ffmpeg_missing"
        payload["hint"] = "Install ffmpeg for Windows and reopen HADES."
    return payload


def _run(command: list[str], timeout: int = 180) -> dict:
    process = subprocess.run(command, capture_output=True, text=True, timeout=timeout, shell=False)
    return {
        "ok": process.returncode == 0,
        "command": command,
        "exit_code": process.returncode,
        "stdout": (process.stdout or "")[-20_000:],
        "stderr": (process.stderr or "")[-20_000:],
    }


def probe(path: str) -> dict:
    ffprobe = _bin("ffprobe")
    source = Path(path).expanduser()
    if not source.is_file():
        return {"ok": False, "error": "file_not_found", "path": str(source)}
    if not ffprobe:
        return {"ok": False, "error": "ffmpeg_missing"}
    payload = _run(
        [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)],
        timeout=60,
    )
    if not payload.get("ok"):
        payload["error"] = "probe_failed"
        return payload
    try:
        info = json.loads(payload["stdout"] or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid_ffprobe_json"}
    fmt = info.get("format") if isinstance(info.get("format"), dict) else {}
    return {
        "ok": True,
        "path": str(source.resolve()),
        "duration": fmt.get("duration"),
        "size": fmt.get("size"),
        "format": fmt.get("format_name"),
        "streams": len(info.get("streams") or []),
    }


def cut(path: str, start: str, duration: str, output: str) -> dict:
    ffmpeg = _bin("ffmpeg")
    source = Path(path).expanduser()
    dest = Path(output).expanduser()
    if not source.is_file():
        return {"ok": False, "error": "file_not_found", "path": str(source)}
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg_missing"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = _run(
        [
            ffmpeg,
            "-y",
            "-ss",
            start,
            "-i",
            str(source),
            "-t",
            duration,
            "-c",
            "copy",
            str(dest),
        ],
        timeout=300,
    )
    payload["input"] = str(source)
    payload["output"] = str(dest)
    if payload.get("ok") and dest.is_file():
        payload["bytes"] = dest.stat().st_size
    else:
        payload["ok"] = False
        payload["error"] = payload.get("error") or "cut_failed"
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES ffmpeg clip bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("probe")
    p.add_argument("--path", required=True)
    c = sub.add_parser("cut")
    c.add_argument("--path", required=True)
    c.add_argument("--start", default="0")
    c.add_argument("--duration", default="10")
    c.add_argument("--output", default="clip.mp4")
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
    elif args.cmd == "probe":
        payload = probe(args.path)
    else:
        payload = cut(args.path, args.start, args.duration, args.output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
