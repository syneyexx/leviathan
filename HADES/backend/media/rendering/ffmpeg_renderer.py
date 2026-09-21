
"""Deterministic FFmpeg compositor driven by EditPlan — no shell interpolation."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def which_ffmpeg() -> str | None:
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def which_ffprobe() -> str | None:
    return shutil.which("ffprobe") or shutil.which("ffprobe.exe")


def probe_media(path: Path) -> dict[str, Any]:
    ffprobe = which_ffprobe()
    if not ffprobe:
        return {"ok": False, "status": "SETUP_REQUIRED", "error": "ffprobe_missing"}
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "status": "FAILED", "error": str(exc)}
    if completed.returncode != 0:
        return {"ok": False, "status": "FAILED", "error": (completed.stderr or "probe_failed")[:500]}
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "status": "FAILED", "error": "probe_json_invalid"}
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float((payload.get("format") or {}).get("duration") or 0)
    return {
        "ok": True,
        "status": "READY",
        "duration": duration,
        "has_video": bool(video),
        "has_audio": bool(audio),
        "width": (video or {}).get("width"),
        "height": (video or {}).get("height"),
        "video_codec": (video or {}).get("codec_name"),
        "audio_codec": (audio or {}).get("codec_name"),
        "avg_frame_rate": (video or {}).get("avg_frame_rate"),
        "raw": payload,
    }


class FFmpegRenderer:
    def __init__(self, *, timeout_sec: int = 180) -> None:
        self.timeout_sec = timeout_sec

    def health(self) -> dict[str, Any]:
        binary = which_ffmpeg()
        if not binary:
            return {"ok": False, "status": "SETUP_REQUIRED", "error": "ffmpeg_missing"}
        return {"ok": True, "status": "READY", "binary": binary}

    def build_edit_plan(
        self,
        *,
        scenes: list[dict[str, Any]],
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        voice_path: str | None = None,
        music_path: str | None = None,
        caption_style: str = "plain",
    ) -> dict[str, Any]:
        return {
            "width": width,
            "height": height,
            "fps": fps,
            "scenes": scenes,
            "voice_path": voice_path,
            "music_path": music_path,
            "caption_style": caption_style,
            "operations": [
                "sequence_scenes",
                "scale_crop",
                "burn_captions",
                "mix_audio",
                "loudnorm",
            ],
        }

    def render(self, plan: dict[str, Any], output_path: Path, *, work_dir: Path | None = None) -> dict[str, Any]:
        health = self.health()
        if not health.get("ok"):
            return health
        ffmpeg = health["binary"]
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        width = int(plan.get("width") or 1080)
        height = int(plan.get("height") or 1920)
        fps = int(plan.get("fps") or 30)
        scenes = list(plan.get("scenes") or [])
        duration = 0.0
        for scene in scenes:
            duration = max(duration, float(scene.get("end") or 0))
        if duration <= 0:
            duration = 5.0

        if work_dir is not None:
            Path(work_dir).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(work_dir) if work_dir else None) as tmp:
            tmp_path = Path(tmp)
            partial = tmp_path / "partial.mp4"
            # Prefer drawtext when a system font exists; otherwise render master without burned captions.
            font_candidates = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "C:/Windows/Fonts/arial.ttf",
            ]
            font_path = next((p for p in font_candidates if Path(p).exists()), None)
            safe_captions: list[str] = []
            if font_path:
                for scene in scenes:
                    text = str(scene.get("caption_text") or scene.get("narration") or "")
                    text = (
                        text.replace("\\", "\\\\")
                        .replace(":", "\\:")
                        .replace("'", "")
                        .replace("%", "")
                        .replace("\n", " ")
                    )[:80]
                    if not text:
                        continue
                    start = float(scene.get("start") or 0)
                    end = float(scene.get("end") or start + 1)
                    safe_captions.append(
                        "drawtext="
                        f"fontfile={font_path}:"
                        f"text='{text}':fontsize=36:fontcolor=white:borderw=2:bordercolor=black:"
                        f"x=(w-text_w)/2:y=h*0.78:enable='between(t\\,{start}\\,{end})'"
                    )

            voice = plan.get("voice_path")
            has_voice = bool(voice and Path(str(voice)).exists())
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x101820:s={width}x{height}:d={duration}:r={fps}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate=44100:duration={duration}",
            ]
            if has_voice:
                cmd.extend(["-i", str(voice)])

            video_filter = ",".join(safe_captions) if safe_captions else "format=yuv420p"
            if has_voice:
                filter_complex = f"[0:v]{video_filter}[vout];[2:a]loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
            else:
                filter_complex = f"[0:v]{video_filter}[vout];[1:a]volume=0.05,aformat=sample_fmts=fltp:channel_layouts=stereo[aout]"

            cmd.extend(
                [
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    "[vout]",
                    "-map",
                    "[aout]",
                    "-t",
                    str(duration),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(partial),
                ]
            )
            try:
                completed = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_sec, check=False)
            except subprocess.TimeoutExpired:
                return {"ok": False, "status": "FAILED", "error": "ffmpeg_timeout"}
            except OSError as exc:
                return {"ok": False, "status": "FAILED", "error": str(exc)}
            if completed.returncode != 0 or not partial.exists():
                err = (completed.stderr or completed.stdout or "render_failed").strip()
                # Prefer the last non-banner lines for truthfulness.
                lines = [ln for ln in err.splitlines() if ln.strip()]
                detail = "\n".join(lines[-12:]) if lines else "render_failed"
                return {
                    "ok": False,
                    "status": "FAILED",
                    "error": detail[:1200],
                }
            # Atomic replace into destination.
            final_tmp = output_path.with_suffix(output_path.suffix + ".tmp")
            final_tmp.write_bytes(partial.read_bytes())
            final_tmp.replace(output_path)

        probed = probe_media(output_path)
        if not probed.get("ok"):
            return {"ok": False, "status": "FAILED", "error": "render_probe_failed", "probe": probed}
        return {
            "ok": True,
            "status": "READY",
            "path": str(output_path),
            "probe": probed,
            "plan": {k: v for k, v in plan.items() if k != "scenes"} | {"scene_count": len(scenes)},
        }
