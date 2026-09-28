"""Production FFmpeg / FFprobe media backend.

Security / ops invariants:
- typed argv lists only (never shell=True)
- ``-nostdin`` on every ffmpeg invoke (ffprobe closes stdin via DEVNULL; ``-nostdin``
  breaks some ffprobe builds that treat it as a valued option)
- network / remote protocols blocked — local file paths only
- codecs/containers validated against allowlists
- progress via ``-progress pipe:1`` when possible; never invent percent
- cancellation via process-tree kill
- bounded stderr capture; path-based I/O (no whole-file Path.read_bytes on media)
- outputs written to staging; caller registers ArtifactStore
- readiness = executable exists + version probe (never auto-install)
"""

from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from Data.modules.media.backends import (
    MediaBackendKind,
    ThumbnailResult,
    TranscodeResult,
    TransformSpec,
)
from Data.modules.media.errors import (
    MEDIA_CANCELLED,
    MEDIA_DISK_FULL,
    MEDIA_FFMPEG_UNAVAILABLE,
    MEDIA_FFPROBE_UNAVAILABLE,
    MEDIA_INPUT_INVALID,
    MEDIA_NETWORK_INPUT_BLOCKED,
    MEDIA_OUTPUT_INVALID,
    MEDIA_TIMEOUT,
    MEDIA_TRANSCODE_FAILED,
    MEDIA_UNSUPPORTED_CODEC,
    MEDIA_UNSUPPORTED_FORMAT,
    MediaDomainError,
)

# --------------------------------------------------------------------------- allowlists

ALLOWED_VIDEO_CODECS = frozenset(
    {
        "copy",
        "libx264",
        "libx265",
        "h264",
        "hevc",
        "mpeg4",
        "libvpx",
        "libvpx-vp9",
        "vp8",
        "vp9",
        "libaom-av1",
        "libsvtav1",
        "av1",
        "gif",
        "png",
        "mjpeg",
    }
)

ALLOWED_AUDIO_CODECS = frozenset(
    {
        "copy",
        "aac",
        "libmp3lame",
        "mp3",
        "libopus",
        "opus",
        "flac",
        "pcm_s16le",
        "pcm_s24le",
        "ac3",
        "libvorbis",
        "vorbis",
    }
)

ALLOWED_CONTAINERS = frozenset(
    {
        "mp4",
        "mkv",
        "webm",
        "mov",
        "avi",
        "wav",
        "mp3",
        "ogg",
        "flac",
        "m4a",
        "aac",
        "gif",
        "png",
        "jpg",
        "jpeg",
        "webp",
        "image2",
    }
)

ALLOWED_QUALITY_PRESETS = frozenset(
    {
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
        "placebo",
    }
)

# Protocols / schemes that must never reach FFmpeg as inputs.
_BLOCKED_NETWORK_SCHEMES = frozenset(
    {
        "http",
        "https",
        "rtsp",
        "rtsps",
        "rtmp",
        "rtmps",
        "rtp",
        "udp",
        "tcp",
        "concat",
        "ftp",
        "ftps",
        "sftp",
        "smb",
        "mmsh",
        "mmst",
        "gopher",
        "ipfs",
        "tls",
        "crypto",  # not a network scheme but blocks protocol injection; files still ok
        "hls",
        "dash",
        "icecast",
        "pipe",
        "fd",
        "data",
        "lavfi",
        "subfile",
    }
)

# FFmpeg protocol_whitelist — local files only (+ crypto for TLS-free local demux).
_PROTOCOL_WHITELIST = "file,crypto"

_DEFAULT_THREADS = 2
_MAX_STDERR_BYTES = 64 * 1024
_MAX_PROGRESS_BUFFER = 32 * 1024
_VERSION_RE = re.compile(r"^(?:ffmpeg|ffprobe)\s+version\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_OUT_TIME_RE = re.compile(r"^out_time(?:_ms)?=(.+)$", re.MULTILINE)
_PROGRESS_KV_RE = re.compile(r"^([a-zA-Z0-9_]+)=([^\r\n]*)$", re.MULTILINE)


def _is_windows() -> bool:
    return os.name == "nt"


def _truncate_bytes(data: bytes, limit: int) -> bytes:
    if len(data) <= limit:
        return data
    half = max(1, limit // 2 - 20)
    return data[:half] + b"\n...[truncated]...\n" + data[-half:]


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = max(1, limit // 2 - 20)
    return text[:half] + "\n...[truncated]...\n" + text[-half:]


def _parse_version_line(text: str) -> str | None:
    match = _VERSION_RE.search(text or "")
    if match:
        return match.group(1)
    # Fallback: first non-empty line fragment.
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return None


def resolve_binary(
    configured: str | Path | None,
    *,
    names: tuple[str, ...],
) -> Path | None:
    """Resolve an executable from an explicit config path or PATH. Never installs."""
    if configured:
        candidate = Path(str(configured)).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
        # Configured but missing/non-executable — do not silently fall through to PATH
        # when the operator explicitly set a path; still try PATH as last resort below
        # only when the configured path was a bare name.
        if candidate.name == str(configured) and not candidate.is_absolute():
            found = shutil.which(str(configured))
            if found:
                return Path(found).resolve()
        return None
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    return None


def assert_local_media_path(path: str | Path, *, must_exist: bool = True) -> Path:
    """Reject network/protocol inputs; return a resolved local filesystem path."""
    raw = str(path or "").strip()
    if not raw:
        raise MediaDomainError(MEDIA_INPUT_INVALID, "media path is required")
    if "\x00" in raw or "\n" in raw or "\r" in raw:
        raise MediaDomainError(MEDIA_INPUT_INVALID, "media path contains illegal characters")
    if raw in {"-", "/dev/stdin", "stdin:"}:
        raise MediaDomainError(MEDIA_NETWORK_INPUT_BLOCKED, "stdin / pipe media inputs are blocked")

    # URL-like or protocol-prefixed strings.
    lowered = raw.lower()
    if "://" in raw:
        parsed = urlparse(raw)
        scheme = (parsed.scheme or "").lower()
        if scheme in _BLOCKED_NETWORK_SCHEMES or scheme not in {"", "file"}:
            raise MediaDomainError(
                MEDIA_NETWORK_INPUT_BLOCKED,
                f"network/protocol media input blocked: {scheme or 'unknown'}",
                details={"scheme": scheme, "path": raw[:200]},
            )
        if scheme == "file":
            # file:///abs/path — keep local path only
            raw = parsed.path or ""
            if os.name == "nt" and raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
                raw = raw[1:]  # /C:/... → C:/...
            if not raw:
                raise MediaDomainError(MEDIA_INPUT_INVALID, "empty file:// path")
    else:
        # Bare scheme prefixes: rtsp:host, concat:list, udp:// already caught.
        for scheme in _BLOCKED_NETWORK_SCHEMES:
            if lowered.startswith(f"{scheme}:") or lowered.startswith(f"{scheme},"):
                raise MediaDomainError(
                    MEDIA_NETWORK_INPUT_BLOCKED,
                    f"network/protocol media input blocked: {scheme}",
                    details={"scheme": scheme, "path": raw[:200]},
                )

    candidate = Path(raw).expanduser()
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise MediaDomainError(
            MEDIA_INPUT_INVALID,
            f"cannot resolve media path: {exc}",
            details={"path": raw[:200]},
        ) from exc

    if must_exist:
        if not resolved.exists():
            raise MediaDomainError(
                MEDIA_INPUT_INVALID,
                f"media path does not exist: {resolved}",
                details={"path": str(resolved)},
            )
        if not resolved.is_file():
            raise MediaDomainError(
                MEDIA_INPUT_INVALID,
                f"media path is not a regular file: {resolved}",
                details={"path": str(resolved)},
            )
    return resolved


def validate_transform_codecs(spec: TransformSpec) -> None:
    if spec.container:
        container = str(spec.container).lstrip(".").lower()
        if container not in ALLOWED_CONTAINERS:
            raise MediaDomainError(
                MEDIA_UNSUPPORTED_FORMAT,
                f"container not allowlisted: {container}",
                details={"container": container},
            )
    if spec.video_codec:
        vc = str(spec.video_codec).lower()
        if vc not in ALLOWED_VIDEO_CODECS:
            raise MediaDomainError(
                MEDIA_UNSUPPORTED_CODEC,
                f"video codec not allowlisted: {vc}",
                details={"video_codec": vc},
            )
    if spec.audio_codec:
        ac = str(spec.audio_codec).lower()
        if ac not in ALLOWED_AUDIO_CODECS:
            raise MediaDomainError(
                MEDIA_UNSUPPORTED_CODEC,
                f"audio codec not allowlisted: {ac}",
                details={"audio_codec": ac},
            )
    if spec.quality_preset:
        preset = str(spec.quality_preset).lower()
        if preset not in ALLOWED_QUALITY_PRESETS:
            raise MediaDomainError(
                MEDIA_UNSUPPORTED_CODEC,
                f"quality preset not allowlisted: {preset}",
                details={"quality_preset": preset},
            )


def _disk_free_bytes(path: Path) -> int | None:
    try:
        target = path if path.exists() else path.parent
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
        return int(shutil.disk_usage(target).free)
    except OSError:
        return None


def disk_preflight_for_media(
    *,
    staging_dir: Path,
    input_size: int | None,
    duration_seconds: float | None = None,
    bitrate: str | int | None = None,
) -> dict[str, Any]:
    """Rough free-space estimate. Skips hard fail when size cannot be estimated."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    free = _disk_free_bytes(staging_dir)
    estimate: int | None = None
    if bitrate is not None and duration_seconds and duration_seconds > 0:
        try:
            br = str(bitrate).lower().strip()
            if br.endswith("k"):
                bps = float(br[:-1]) * 1000.0
            elif br.endswith("m"):
                bps = float(br[:-1]) * 1_000_000.0
            else:
                bps = float(br)
            estimate = int(bps * float(duration_seconds) / 8.0 * 1.25)
        except (TypeError, ValueError):
            estimate = None
    if estimate is None and input_size is not None and input_size > 0:
        # Conservative: assume re-encode may temporarily need ~1.5× input + headroom.
        estimate = int(input_size * 1.5)
    if estimate is None:
        return {"ok": True, "skipped": True, "diskFreeBytes": free, "estimatedBytes": None}
    reserve = 256 * 1024 * 1024
    required = estimate + reserve
    ok = free is None or free >= required
    result = {
        "ok": ok,
        "skipped": False,
        "requiredBytes": required,
        "estimatedBytes": estimate,
        "availableBytes": free,
        "missingBytes": None if free is None else max(0, required - free),
        "targetPath": str(staging_dir),
    }
    if not ok:
        raise MediaDomainError(
            MEDIA_DISK_FULL,
            f"insufficient disk for media output: required≈{required} available={free}",
            details=result,
        )
    return result


def _terminate_ffmpeg_process(proc: subprocess.Popen[Any]) -> dict[str, Any]:
    """Cancel an owned FFmpeg process tree."""
    try:
        from Data.modules.coding.process import kill_process_tree

        kill_process_tree(proc, grace_seconds=0.5)
        return {"method": "kill_process_tree", "returncode": proc.poll()}
    except Exception:  # noqa: BLE001
        pass
    try:
        from Data.modules.model_runtime.process_control import terminate_owned_process

        return {"method": "terminate_owned_process", **terminate_owned_process(proc)}
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except OSError:
            pass
        return {"method": "kill", "returncode": proc.poll()}


def _spawn_popen(argv: list[str], *, stdout=subprocess.PIPE, stderr=subprocess.PIPE) -> subprocess.Popen[Any]:
    creationflags = 0
    start_new_session = False
    if _is_windows():
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        start_new_session = True
    return subprocess.Popen(  # noqa: S603 — argv list, shell=False
        argv,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        shell=False,
        start_new_session=start_new_session,
        creationflags=creationflags,
    )


def _drain_bounded_stderr(proc: subprocess.Popen[Any], *, limit: int = _MAX_STDERR_BYTES) -> bytes:
    """Read stderr with a hard byte cap (ring-style keep head+tail via truncate)."""
    if proc.stderr is None:
        return b""
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            block = proc.stderr.read(4096)
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total >= limit * 2:
                # Collapse early to bound memory.
                joined = _truncate_bytes(b"".join(chunks), limit)
                chunks = [joined]
                total = len(joined)
    except (OSError, ValueError):
        pass
    return _truncate_bytes(b"".join(chunks), limit)


def parse_progress_blob(text: str, *, duration_seconds: float | None) -> dict[str, Any]:
    """Parse ffmpeg ``-progress`` key=value output. Never invent percent."""
    fields: dict[str, str] = {}
    for match in _PROGRESS_KV_RE.finditer(text or ""):
        fields[match.group(1)] = match.group(2).strip()
    out: dict[str, Any] = {"fields": fields}
    out_time_ms: float | None = None
    if "out_time_us" in fields:
        try:
            out_time_ms = float(fields["out_time_us"]) / 1000.0
        except ValueError:
            out_time_ms = None
    elif "out_time_ms" in fields:
        try:
            # FFmpeg: out_time_ms is historically microseconds despite the name.
            out_time_ms = float(fields["out_time_ms"]) / 1000.0
        except ValueError:
            out_time_ms = None
    elif "out_time" in fields:
        # HH:MM:SS.microseconds
        try:
            parts = fields["out_time"].split(":")
            if len(parts) == 3:
                h, m, s = parts
                out_time_ms = (int(h) * 3600 + int(m) * 60 + float(s)) * 1000.0
        except (TypeError, ValueError):
            out_time_ms = None
    if out_time_ms is not None:
        out["out_time_ms"] = out_time_ms
        out["out_time_seconds"] = out_time_ms / 1000.0
    if (
        duration_seconds is not None
        and duration_seconds > 0
        and out_time_ms is not None
    ):
        pct = max(0.0, min(100.0, (out_time_ms / 1000.0) / float(duration_seconds) * 100.0))
        out["percent"] = round(pct, 2)
    else:
        out["percent"] = None  # unknown duration — never fake
    if "progress" in fields:
        out["progress"] = fields["progress"]
    return out


class FfmpegMediaBackend:
    """Real FFmpeg/FFprobe backend for production media workers."""

    kind = MediaBackendKind.FFMPEG

    def __init__(
        self,
        *,
        ffmpeg_path: str | Path | None = None,
        ffprobe_path: str | Path | None = None,
        staging_dir: str | Path | None = None,
        threads: int = _DEFAULT_THREADS,
        protocol_whitelist: str = _PROTOCOL_WHITELIST,
        max_stderr_bytes: int = _MAX_STDERR_BYTES,
    ) -> None:
        self._configured_ffmpeg = ffmpeg_path
        self._configured_ffprobe = ffprobe_path
        self._ffmpeg: Path | None = resolve_binary(
            ffmpeg_path, names=("ffmpeg", "ffmpeg.exe")
        )
        self._ffprobe: Path | None = resolve_binary(
            ffprobe_path, names=("ffprobe", "ffprobe.exe")
        )
        self._staging_dir = Path(staging_dir) if staging_dir else None
        self._threads = max(1, int(threads or _DEFAULT_THREADS))
        self._protocol_whitelist = protocol_whitelist
        self._max_stderr_bytes = max(4096, int(max_stderr_bytes))
        self._ffmpeg_version: str | None = None
        self._ffprobe_version: str | None = None
        self._readiness_cache: dict[str, Any] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ paths / versions

    @property
    def ffmpeg_path(self) -> Path | None:
        return self._ffmpeg

    @property
    def ffprobe_path(self) -> Path | None:
        return self._ffprobe

    def _require_ffmpeg(self) -> Path:
        if self._ffmpeg is None or not self._ffmpeg.is_file():
            # Re-resolve in case PATH changed after construction.
            self._ffmpeg = resolve_binary(
                self._configured_ffmpeg, names=("ffmpeg", "ffmpeg.exe")
            )
        if self._ffmpeg is None or not self._ffmpeg.is_file():
            raise MediaDomainError(
                MEDIA_FFMPEG_UNAVAILABLE,
                "ffmpeg executable not found (not auto-installed)",
                details={"configured": str(self._configured_ffmpeg) if self._configured_ffmpeg else None},
            )
        return self._ffmpeg

    def _require_ffprobe(self) -> Path:
        if self._ffprobe is None or not self._ffprobe.is_file():
            self._ffprobe = resolve_binary(
                self._configured_ffprobe, names=("ffprobe", "ffprobe.exe")
            )
        if self._ffprobe is None or not self._ffprobe.is_file():
            raise MediaDomainError(
                MEDIA_FFPROBE_UNAVAILABLE,
                "ffprobe executable not found (not auto-installed)",
                details={"configured": str(self._configured_ffprobe) if self._configured_ffprobe else None},
            )
        return self._ffprobe

    def _probe_version(self, binary: Path) -> str | None:
        try:
            completed = subprocess.run(  # noqa: S603
                [str(binary), "-version"],
                capture_output=True,
                text=True,
                timeout=15,
                shell=False,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        blob = (completed.stdout or "") + "\n" + (completed.stderr or "")
        return _parse_version_line(blob)

    def _ensure_versions(self) -> dict[str, str | None]:
        if self._ffmpeg and self._ffmpeg_version is None:
            self._ffmpeg_version = self._probe_version(self._ffmpeg)
        if self._ffprobe and self._ffprobe_version is None:
            self._ffprobe_version = self._probe_version(self._ffprobe)
        return {
            "ffmpeg_version": self._ffmpeg_version,
            "ffprobe_version": self._ffprobe_version,
        }

    def _receipt_base(self, **extra: Any) -> dict[str, Any]:
        versions = self._ensure_versions()
        return {
            "backend": self.kind.value,
            "ffmpeg_path": str(self._ffmpeg) if self._ffmpeg else None,
            "ffprobe_path": str(self._ffprobe) if self._ffprobe else None,
            **versions,
            **extra,
        }

    def _ffmpeg_base_argv(self, ffmpeg: Path) -> list[str]:
        """Common ffmpeg prefix: no shell, no stdin interaction, local protocols only."""
        return [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-protocol_whitelist",
            self._protocol_whitelist,
        ]

    def _ffprobe_base_argv(self, ffprobe: Path) -> list[str]:
        """Common ffprobe prefix.

        stdin is always DEVNULL at spawn. Do not pass ``-nostdin`` — on several
        packaged ffprobe builds it is a valued option and consumes the next argv
        token (breaking ``-v`` / ``-protocol_whitelist``).
        """
        return [
            str(ffprobe),
            "-protocol_whitelist",
            self._protocol_whitelist,
        ]

    # ------------------------------------------------------------------ readiness

    def readiness(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._readiness_cache is not None and not force:
                return dict(self._readiness_cache)

            # Re-resolve binaries on force / first probe.
            self._ffmpeg = resolve_binary(
                self._configured_ffmpeg, names=("ffmpeg", "ffmpeg.exe")
            )
            self._ffprobe = resolve_binary(
                self._configured_ffprobe, names=("ffprobe", "ffprobe.exe")
            )
            self._ffmpeg_version = None
            self._ffprobe_version = None

            ffmpeg_ok = bool(self._ffmpeg and self._ffmpeg.is_file())
            ffprobe_ok = bool(self._ffprobe and self._ffprobe.is_file())
            versions = self._ensure_versions() if (ffmpeg_ok or ffprobe_ok) else {
                "ffmpeg_version": None,
                "ffprobe_version": None,
            }
            # Version probe must succeed for READY — executable presence alone is insufficient
            # if the binary is broken.
            ffmpeg_ver_ok = bool(versions.get("ffmpeg_version")) if ffmpeg_ok else False
            ffprobe_ver_ok = bool(versions.get("ffprobe_version")) if ffprobe_ok else False
            ready = ffmpeg_ok and ffprobe_ok and ffmpeg_ver_ok and ffprobe_ver_ok

            if not ffmpeg_ok:
                detail = "ffmpeg executable missing (not auto-installed)"
                status = "UNAVAILABLE"
            elif not ffprobe_ok:
                detail = "ffprobe executable missing (not auto-installed)"
                status = "UNAVAILABLE"
            elif not ffmpeg_ver_ok:
                detail = "ffmpeg version probe failed"
                status = "DEGRADED"
            elif not ffprobe_ver_ok:
                detail = "ffprobe version probe failed"
                status = "DEGRADED"
            else:
                detail = (
                    f"ffmpeg {versions.get('ffmpeg_version')} / "
                    f"ffprobe {versions.get('ffprobe_version')}"
                )
                status = "READY"

            snap: dict[str, Any] = {
                "status": status,
                "ready": ready,
                "backend": self.kind.value,
                "production_capable": ready,
                "ffmpeg_available": ffmpeg_ok and ffmpeg_ver_ok,
                "ffprobe_available": ffprobe_ok and ffprobe_ver_ok,
                "ffmpeg_path": str(self._ffmpeg) if self._ffmpeg else None,
                "ffprobe_path": str(self._ffprobe) if self._ffprobe else None,
                "ffmpeg_version": versions.get("ffmpeg_version"),
                "ffprobe_version": versions.get("ffprobe_version"),
                "threads": self._threads,
                "detail": detail,
                "truth": {
                    "executable_alone_is_not_ready": True,
                    "no_auto_install": True,
                    "fixture_is_not_ffmpeg": False,
                    "production_capable": ready,
                    "shell": False,
                },
            }
            self._readiness_cache = snap
            return dict(snap)

    # ------------------------------------------------------------------ probe

    def probe(self, path: str | Path, *, timeout_seconds: float = 60.0) -> dict[str, Any]:
        local = assert_local_media_path(path, must_exist=True)
        ffprobe = self._require_ffprobe()
        # Also require ffmpeg for a coherent production backend readiness story,
        # but probe itself only needs ffprobe.
        try:
            self._require_ffmpeg()
        except MediaDomainError:
            pass
        argv = [
            *self._ffprobe_base_argv(ffprobe),
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(local),
        ]
        try:
            completed = subprocess.run(  # noqa: S603
                argv,
                capture_output=True,
                timeout=max(1.0, float(timeout_seconds)),
                shell=False,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaDomainError(
                MEDIA_TIMEOUT,
                f"ffprobe timed out after {timeout_seconds}s",
                details={"path": str(local)},
            ) from exc
        except OSError as exc:
            raise MediaDomainError(
                MEDIA_FFPROBE_UNAVAILABLE,
                f"ffprobe spawn failed: {exc}",
            ) from exc

        stderr = _truncate_text(
            (completed.stderr or b"").decode("utf-8", errors="replace")
            if isinstance(completed.stderr, (bytes, bytearray))
            else str(completed.stderr or ""),
            self._max_stderr_bytes,
        )
        if completed.returncode != 0:
            raise MediaDomainError(
                MEDIA_INPUT_INVALID,
                "ffprobe failed to inspect media",
                details={
                    "path": str(local),
                    "returncode": completed.returncode,
                    "stderr": stderr[:2000],
                },
            )
        raw_out = completed.stdout or b""
        if isinstance(raw_out, str):
            text = raw_out
        else:
            text = raw_out.decode("utf-8", errors="replace")
        try:
            payload = json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            raise MediaDomainError(
                MEDIA_INPUT_INVALID,
                "ffprobe returned non-JSON output",
                details={"path": str(local)},
            ) from exc
        if not isinstance(payload, dict):
            raise MediaDomainError(MEDIA_INPUT_INVALID, "ffprobe JSON root must be an object")

        fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
        streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
        duration = None
        try:
            if fmt.get("duration") is not None:
                duration = float(fmt["duration"])
        except (TypeError, ValueError):
            duration = None

        size_bytes = None
        try:
            size_bytes = int(local.stat().st_size)
        except OSError:
            size_bytes = None

        receipt = self._receipt_base(
            operation="probe",
            input=str(local),
            input_size_bytes=size_bytes,
        )
        return {
            "backend": self.kind.value,
            "path": str(local),
            "exists": True,
            "size_bytes": size_bytes,
            "duration_seconds": duration,
            "format": fmt,
            "streams": streams,
            "receipt": receipt,
            "truth": {
                "fixture_is_not_ffmpeg": False,
                "production_capable": True,
                "shell": False,
            },
        }

    # ------------------------------------------------------------------ thumbnail

    def thumbnail(
        self,
        path: str | Path,
        *,
        at_seconds: float = 0.0,
        width: int | None = 320,
        height: int | None = None,
        staging_dir: str | Path | None = None,
        fmt: str = "png",
        timeout_seconds: float = 60.0,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ThumbnailResult:
        local = assert_local_media_path(path, must_exist=True)
        ffmpeg = self._require_ffmpeg()
        self._ensure_versions()

        out_fmt = str(fmt or "png").lower().lstrip(".")
        if out_fmt not in {"png", "jpg", "jpeg", "webp"}:
            raise MediaDomainError(
                MEDIA_UNSUPPORTED_FORMAT,
                f"thumbnail format not allowlisted: {out_fmt}",
                details={"format": out_fmt},
            )
        if out_fmt == "jpeg":
            out_fmt = "jpg"

        staging = Path(staging_dir) if staging_dir else self._staging_dir
        if staging is None:
            staging = Path(tempfile.mkdtemp(prefix="lev-media-thumb-"))
        else:
            staging.mkdir(parents=True, exist_ok=True)

        try:
            input_size = int(local.stat().st_size)
        except OSError:
            input_size = None
        disk_preflight_for_media(
            staging_dir=staging,
            input_size=min(input_size or 0, 8 * 1024 * 1024) or (2 * 1024 * 1024),
        )

        out = staging / f"thumb-{uuid.uuid4().hex[:12]}.{out_fmt}"
        scale = self._scale_filter(width, height)
        seek = max(0.0, float(at_seconds or 0.0))

        argv: list[str] = [
            *self._ffmpeg_base_argv(ffmpeg),
            "-y",
            "-ss",
            f"{seek:.3f}",
            "-i",
            str(local),
            "-frames:v",
            "1",
        ]
        if scale:
            argv.extend(["-vf", scale])
        argv.extend(
            [
                "-threads",
                str(self._threads),
                str(out),
            ]
        )

        self._run_ffmpeg(
            argv,
            timeout_seconds=timeout_seconds,
            cancel_check=cancel_check,
            duration_seconds=None,
            progress_cb=None,
            use_progress_pipe=False,
            operation="thumbnail",
        )

        if not out.is_file() or out.stat().st_size <= 0:
            raise MediaDomainError(
                MEDIA_OUTPUT_INVALID,
                "thumbnail output missing or empty",
                details={"path": str(out)},
            )

        return ThumbnailResult(
            path=out,
            format=out_fmt,
            width=width,
            height=height,
            at_seconds=seek,
            size_bytes=int(out.stat().st_size),
            receipt=self._receipt_base(
                operation="thumbnail",
                input=str(local),
                output=str(out),
                at_seconds=seek,
            ),
        )

    # ------------------------------------------------------------------ transcode

    def transcode(
        self,
        spec: TransformSpec,
        *,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> TranscodeResult:
        validate_transform_codecs(spec)
        local = assert_local_media_path(spec.input_path, must_exist=True)
        ffmpeg = self._require_ffmpeg()
        self._require_ffprobe()
        self._ensure_versions()

        staging = spec.resolved_staging()
        staging.mkdir(parents=True, exist_ok=True)

        container = (spec.container or local.suffix.lstrip(".") or "mp4").lstrip(".").lower()
        if container not in ALLOWED_CONTAINERS:
            raise MediaDomainError(
                MEDIA_UNSUPPORTED_FORMAT,
                f"container not allowlisted: {container}",
                details={"container": container},
            )

        # Probe for duration (progress percent) + size (disk estimate).
        duration_seconds: float | None = None
        try:
            probed = self.probe(local, timeout_seconds=min(60.0, float(spec.timeout_seconds or 60.0)))
            duration_seconds = probed.get("duration_seconds")
            if isinstance(duration_seconds, (int, float)):
                duration_seconds = float(duration_seconds)
            else:
                duration_seconds = None
        except MediaDomainError:
            probed = None

        try:
            input_size = int(local.stat().st_size)
        except OSError:
            input_size = None

        # Apply trim window to duration estimate when present.
        effective_duration = duration_seconds
        if effective_duration is not None:
            start = float(spec.trim_start or 0.0)
            end = float(spec.trim_end) if spec.trim_end is not None else effective_duration
            if end > start:
                effective_duration = max(0.0, end - start)

        disk_meta = disk_preflight_for_media(
            staging_dir=staging,
            input_size=input_size,
            duration_seconds=effective_duration,
            bitrate=spec.bitrate,
        )

        base = spec.output_basename or f"transcode-{uuid.uuid4().hex[:12]}"
        if Path(base).suffix:
            out = staging / base
        else:
            ext = "jpg" if container == "jpeg" else container
            if ext == "image2":
                ext = "png"
            out = staging / f"{base}.{ext}"

        threads = int(spec.threads) if spec.threads is not None else self._threads
        threads = max(1, min(threads, 8))  # hard ceiling — never all CPUs by default

        argv: list[str] = [
            *self._ffmpeg_base_argv(ffmpeg),
            "-y",
        ]

        if spec.trim_start is not None:
            argv.extend(["-ss", f"{float(spec.trim_start):.3f}"])

        argv.extend(["-i", str(local)])

        if spec.trim_end is not None:
            # Prefer -to as absolute timestamp when trim_start was input-seeked.
            argv.extend(["-to", f"{float(spec.trim_end):.3f}"])

        vf = self._scale_filter(spec.width, spec.height)
        if spec.fps is not None:
            fps_filter = f"fps={float(spec.fps)}"
            vf = f"{vf},{fps_filter}" if vf else fps_filter
        if vf:
            argv.extend(["-vf", vf])

        if spec.video_codec:
            argv.extend(["-c:v", str(spec.video_codec)])
        if spec.audio_codec:
            argv.extend(["-c:a", str(spec.audio_codec)])
        if spec.bitrate is not None:
            argv.extend(["-b:v", str(spec.bitrate)])
        if spec.sample_rate is not None:
            argv.extend(["-ar", str(int(spec.sample_rate))])
        if spec.channels is not None:
            argv.extend(["-ac", str(int(spec.channels))])
        if spec.quality_preset:
            argv.extend(["-preset", str(spec.quality_preset).lower()])

        # Container-ish format when useful (gif/image2/etc.)
        if container in {"gif", "image2", "webp"}:
            argv.extend(["-f", container if container != "webp" else "webp"])
        elif container in {"mp3", "wav", "flac", "ogg", "adts"}:
            argv.extend(["-f", container])

        argv.extend(["-threads", str(threads), str(out)])

        progress = self._run_ffmpeg(
            argv,
            timeout_seconds=float(spec.timeout_seconds or 600.0),
            cancel_check=cancel_check,
            duration_seconds=effective_duration,
            progress_cb=progress_cb,
            use_progress_pipe=True,
            operation="transcode",
        )

        if not out.is_file() or out.stat().st_size <= 0:
            raise MediaDomainError(
                MEDIA_OUTPUT_INVALID,
                "transcode output missing or empty",
                details={"path": str(out), "progress": progress},
            )

        return TranscodeResult(
            path=out,
            container=container,
            size_bytes=int(out.stat().st_size),
            progress=progress,
            receipt=self._receipt_base(
                operation="transcode",
                input=str(local),
                output=str(out),
                container=container,
                video_codec=spec.video_codec,
                audio_codec=spec.audio_codec,
                threads=threads,
                disk_preflight=disk_meta,
                transform={
                    "width": spec.width,
                    "height": spec.height,
                    "fps": spec.fps,
                    "bitrate": spec.bitrate,
                    "sample_rate": spec.sample_rate,
                    "channels": spec.channels,
                    "trim_start": spec.trim_start,
                    "trim_end": spec.trim_end,
                    "quality_preset": spec.quality_preset,
                },
            ),
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _scale_filter(width: int | None, height: int | None) -> str | None:
        if width is None and height is None:
            return None
        w = int(width) if width is not None else -2
        h = int(height) if height is not None else -2
        if w == 0 or h == 0:
            raise MediaDomainError(MEDIA_INPUT_INVALID, "width/height must be non-zero")
        # Keep aspect when one dim omitted (-2 = even dimension for yuv420).
        return f"scale={w}:{h}"

    def _run_ffmpeg(
        self,
        argv: list[str],
        *,
        timeout_seconds: float,
        cancel_check: Callable[[], bool] | None,
        duration_seconds: float | None,
        progress_cb: Callable[[dict[str, Any]], None] | None,
        use_progress_pipe: bool,
        operation: str,
    ) -> dict[str, Any]:
        run_argv = list(argv)
        if use_progress_pipe:
            # Insert progress before output path (last argv element).
            if len(run_argv) < 2:
                raise MediaDomainError(MEDIA_TRANSCODE_FAILED, "invalid ffmpeg argv")
            out_path = run_argv[-1]
            run_argv = run_argv[:-1] + ["-progress", "pipe:1", "-nostats", out_path]

        started = time.monotonic()
        stdout_target = subprocess.PIPE if use_progress_pipe else subprocess.DEVNULL
        try:
            proc = _spawn_popen(run_argv, stdout=stdout_target, stderr=subprocess.PIPE)
        except FileNotFoundError as exc:
            raise MediaDomainError(
                MEDIA_FFMPEG_UNAVAILABLE,
                f"ffmpeg executable missing: {exc}",
            ) from exc
        except OSError as exc:
            raise MediaDomainError(
                MEDIA_FFMPEG_UNAVAILABLE,
                f"ffmpeg spawn failed: {exc}",
            ) from exc

        stderr_buf = bytearray()
        progress_text = ""
        last_progress: dict[str, Any] = {
            "percent": None,
            "out_time_seconds": None,
            "duration_seconds": duration_seconds,
        }
        timed_out = False
        cancelled = False
        deadline = started + max(1.0, float(timeout_seconds))

        try:
            assert proc.stderr is not None
            open_fds: set[int] = set()
            stdout_fd: int | None = None
            stderr_fd = proc.stderr.fileno()
            open_fds.add(stderr_fd)
            if use_progress_pipe and proc.stdout is not None:
                stdout_fd = proc.stdout.fileno()
                open_fds.add(stdout_fd)

            while open_fds or proc.poll() is None:
                if callable(cancel_check) and cancel_check():
                    cancelled = True
                    _terminate_ffmpeg_process(proc)
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    _terminate_ffmpeg_process(proc)
                    break

                if not open_fds:
                    try:
                        proc.wait(timeout=0.2)
                    except subprocess.TimeoutExpired:
                        continue
                    break

                remaining = max(0.05, min(0.5, deadline - time.monotonic()))
                try:
                    readable, _, _ = select.select(list(open_fds), [], [], remaining)
                except (ValueError, OSError, AttributeError):
                    # select unsupported on this platform for pipes — fall back to communicate.
                    try:
                        out_b, err_b = proc.communicate(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        continue
                    if err_b:
                        stderr_buf.extend(err_b if isinstance(err_b, (bytes, bytearray)) else err_b.encode())
                    if out_b and use_progress_pipe:
                        progress_text = _truncate_text(
                            progress_text
                            + (
                                out_b.decode("utf-8", errors="replace")
                                if isinstance(out_b, (bytes, bytearray))
                                else str(out_b)
                            ),
                            _MAX_PROGRESS_BUFFER,
                        )
                        last_progress = parse_progress_blob(
                            progress_text, duration_seconds=duration_seconds
                        )
                        if progress_cb:
                            try:
                                progress_cb(dict(last_progress))
                            except Exception:  # noqa: BLE001
                                pass
                    open_fds.clear()
                    break

                if not readable:
                    if proc.poll() is not None:
                        for fd in list(open_fds):
                            try:
                                chunk = os.read(fd, 4096)
                            except OSError:
                                open_fds.discard(fd)
                                continue
                            if not chunk:
                                open_fds.discard(fd)
                                continue
                            if fd == stderr_fd:
                                stderr_buf.extend(chunk)
                                if len(stderr_buf) > self._max_stderr_bytes * 2:
                                    stderr_buf[:] = _truncate_bytes(
                                        bytes(stderr_buf), self._max_stderr_bytes
                                    )
                            elif stdout_fd is not None and fd == stdout_fd:
                                progress_text = _truncate_text(
                                    progress_text + chunk.decode("utf-8", errors="replace"),
                                    _MAX_PROGRESS_BUFFER,
                                )
                                last_progress = parse_progress_blob(
                                    progress_text, duration_seconds=duration_seconds
                                )
                                if progress_cb:
                                    try:
                                        progress_cb(dict(last_progress))
                                    except Exception:  # noqa: BLE001
                                        pass
                    continue

                for fd in readable:
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:
                        open_fds.discard(fd)
                        continue
                    if not chunk:
                        open_fds.discard(fd)
                        continue
                    if fd == stderr_fd:
                        stderr_buf.extend(chunk)
                        if len(stderr_buf) > self._max_stderr_bytes * 2:
                            stderr_buf[:] = _truncate_bytes(
                                bytes(stderr_buf), self._max_stderr_bytes
                            )
                    elif stdout_fd is not None and fd == stdout_fd:
                        progress_text = _truncate_text(
                            progress_text + chunk.decode("utf-8", errors="replace"),
                            _MAX_PROGRESS_BUFFER,
                        )
                        last_progress = parse_progress_blob(
                            progress_text, duration_seconds=duration_seconds
                        )
                        if progress_cb:
                            try:
                                progress_cb(dict(last_progress))
                            except Exception:  # noqa: BLE001
                                pass

            if proc.poll() is None:
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    _terminate_ffmpeg_process(proc)
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
        finally:
            if proc.poll() is None:
                _terminate_ffmpeg_process(proc)
            for stream in (proc.stdout, proc.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass

        stderr_text = _truncate_text(
            bytes(stderr_buf).decode("utf-8", errors="replace"),
            self._max_stderr_bytes,
        )
        duration = time.monotonic() - started
        last_progress = {
            **last_progress,
            **parse_progress_blob(progress_text, duration_seconds=duration_seconds),
            "elapsed_seconds": round(duration, 3),
            "operation": operation,
        }

        if cancelled:
            raise MediaDomainError(
                MEDIA_CANCELLED,
                f"ffmpeg {operation} cancelled",
                details={"progress": last_progress, "stderr": stderr_text[:1000]},
            )
        if timed_out:
            raise MediaDomainError(
                MEDIA_TIMEOUT,
                f"ffmpeg {operation} timed out after {timeout_seconds}s",
                details={"progress": last_progress, "stderr": stderr_text[:1000]},
            )

        code = proc.returncode if proc.returncode is not None else -1
        if code != 0:
            raise MediaDomainError(
                MEDIA_TRANSCODE_FAILED,
                f"ffmpeg {operation} failed (exit {code})",
                details={
                    "returncode": code,
                    "stderr": stderr_text[:2000],
                    "progress": last_progress,
                    "argv0": run_argv[0] if run_argv else None,
                },
            )
        return last_progress
