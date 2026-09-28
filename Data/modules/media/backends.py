"""Media backend abstraction — fixture (test-only) + production FFmpeg.

MediaService (rewritten separately) selects a backend; this module defines the
shared contract and the deterministic fixture implementation used in CI.
"""

from __future__ import annotations

import hashlib
import html
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable


class MediaBackendKind(str, Enum):
    FIXTURE = "fixture"
    FFMPEG = "ffmpeg"


@dataclass(frozen=True)
class TransformSpec:
    """Declarative transcode / convert request.

    Outputs land under ``staging_dir``; the caller registers them with ArtifactStore.
    """

    input_path: str | Path
    staging_dir: str | Path
    container: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    bitrate: str | int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    trim_start: float | None = None  # seconds
    trim_end: float | None = None  # seconds
    quality_preset: str | None = None  # e.g. ultrafast|fast|medium|slow
    output_basename: str | None = None
    timeout_seconds: float = 600.0
    threads: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def resolved_input(self) -> Path:
        return Path(self.input_path)

    def resolved_staging(self) -> Path:
        return Path(self.staging_dir)


@dataclass
class ThumbnailResult:
    """Path-first thumbnail result — avoid loading large media into memory."""

    path: Path
    format: str
    width: int | None = None
    height: int | None = None
    at_seconds: float = 0.0
    size_bytes: int | None = None
    receipt: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "at_seconds": self.at_seconds,
            "size_bytes": self.size_bytes,
            "receipt": dict(self.receipt),
        }


@dataclass
class TranscodeResult:
    """Staged output path + provenance receipt for ArtifactStore registration."""

    path: Path
    container: str | None = None
    size_bytes: int | None = None
    progress: dict[str, Any] | None = None
    receipt: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "container": self.container,
            "size_bytes": self.size_bytes,
            "progress": dict(self.progress) if self.progress else None,
            "receipt": dict(self.receipt),
        }


@runtime_checkable
class MediaBackend(Protocol):
    """Production media transform backend contract."""

    kind: MediaBackendKind

    def readiness(self, *, force: bool = False) -> dict[str, Any]:
        """Return measured readiness — never claim READY without a real probe."""
        ...

    def probe(self, path: str | Path, *, timeout_seconds: float = 60.0) -> dict[str, Any]:
        """Inspect media metadata. Returns a dict (ffprobe-shaped or fixture)."""
        ...

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
        ...

    def transcode(
        self,
        spec: TransformSpec,
        *,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> TranscodeResult:
        ...


def _svg_bytes(title: str, subtitle: str = "", *, width: int = 640, height: int = 480) -> bytes:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" height="{int(height)}">'
        f'<rect width="100%" height="100%" fill="#222"/>'
        f'<text x="24" y="48" fill="#eee" font-size="22">{html.escape(title)}</text>'
        f'<text x="24" y="84" fill="#aaa" font-size="14">{html.escape(subtitle)}</text>'
        f"</svg>"
    )
    return svg.encode("utf-8")


class FixtureMediaBackend:
    """Deterministic test-only backend — SVG fixtures, no FFmpeg dependency.

    Lightly mirrors the historical MediaService SVG probe/thumbnail behaviour so
    CI can exercise the MediaBackend contract without binaries.
    """

    kind = MediaBackendKind.FIXTURE

    def __init__(self, *, staging_dir: str | Path | None = None) -> None:
        self._default_staging = Path(staging_dir) if staging_dir else None
        self._readiness_cache: dict[str, Any] | None = None

    def readiness(self, *, force: bool = False) -> dict[str, Any]:
        if self._readiness_cache is not None and not force:
            return dict(self._readiness_cache)
        snap = {
            "status": "READY",
            "ready": True,
            "backend": self.kind.value,
            "production_capable": False,
            "ffmpeg_available": False,
            "ffprobe_available": False,
            "detail": "fixture backend (test-only; not production media)",
            "truth": {
                "fixture_is_not_ffmpeg": True,
                "fixture_is_not_production": True,
                "production_capable": False,
            },
        }
        self._readiness_cache = snap
        return dict(snap)

    def probe(self, path: str | Path, *, timeout_seconds: float = 60.0) -> dict[str, Any]:
        del timeout_seconds  # fixture is instantaneous
        p = Path(path)
        exists = p.exists()
        size = p.stat().st_size if exists and p.is_file() else 0
        suffix = p.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
            kind = "image"
            mime = "image/png" if suffix != ".svg" else "image/svg+xml"
        elif suffix in {".mp4", ".webm", ".mkv", ".mov", ".avi"}:
            kind = "video"
            mime = "video/mp4"
        elif suffix in {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"}:
            kind = "audio"
            mime = "audio/wav"
        else:
            kind = "file"
            mime = "application/octet-stream"
        return {
            "backend": self.kind.value,
            "path": str(p),
            "exists": exists,
            "size_bytes": size,
            "media_kind": kind,
            "mime_guess": mime,
            "format": {"format_name": suffix.lstrip(".") or "unknown", "size": str(size)},
            "streams": [],
            "detail": "Fixture probe (no ffmpeg)",
            "receipt": {
                "backend": self.kind.value,
                "ffmpeg_version": None,
                "ffprobe_version": None,
            },
            "truth": {
                "fixture_is_not_ffmpeg": True,
                "fixture_is_not_production": True,
                "production_capable": False,
            },
        }

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
        del timeout_seconds, cancel_check
        # Fixture always emits SVG regardless of requested fmt — honest about non-decode.
        out_fmt = "svg"
        w = int(width or 320)
        h = int(height or max(1, int(w * 3 / 4)))
        staging = Path(staging_dir) if staging_dir else self._default_staging
        if staging is None:
            staging = Path.cwd() / ".media_fixture_staging"
        staging.mkdir(parents=True, exist_ok=True)
        out = staging / f"thumb-{uuid.uuid4().hex[:10]}.{out_fmt}"
        data = _svg_bytes("thumbnail", str(path), width=w, height=h)
        out.write_bytes(data)
        return ThumbnailResult(
            path=out,
            format=out_fmt,
            width=w,
            height=h,
            at_seconds=float(at_seconds or 0.0),
            size_bytes=len(data),
            receipt={
                "backend": self.kind.value,
                "sha256": hashlib.sha256(data).hexdigest(),
                "requested_format": fmt,
                "ffmpeg_version": None,
                "ffprobe_version": None,
                "truth": {
                    "fixture_is_not_ffmpeg": True,
                    "fixture_is_not_production": True,
                },
            },
        )

    def transcode(
        self,
        spec: TransformSpec,
        *,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> TranscodeResult:
        del progress_cb, cancel_check
        staging = spec.resolved_staging()
        staging.mkdir(parents=True, exist_ok=True)
        container = (spec.container or "svg").lstrip(".").lower()
        # Fixture cannot decode — emit a labeled SVG placeholder.
        if container not in {"svg", "png", "jpg", "jpeg", "webp"}:
            container = "svg"
        base = spec.output_basename or f"fixture-transcode-{uuid.uuid4().hex[:10]}"
        if "." not in base:
            base = f"{base}.{container if container == 'svg' else 'svg'}"
        out = staging / base
        if out.suffix.lower() != ".svg":
            out = out.with_suffix(".svg")
        data = _svg_bytes(
            "fixture.transcode",
            f"{spec.resolved_input().name} → {out.name}",
            width=int(spec.width or 640),
            height=int(spec.height or 480),
        )
        out.write_bytes(data)
        return TranscodeResult(
            path=out,
            container="svg",
            size_bytes=len(data),
            progress=None,  # never invent percent
            receipt={
                "backend": self.kind.value,
                "input": str(spec.resolved_input()),
                "sha256": hashlib.sha256(data).hexdigest(),
                "ffmpeg_version": None,
                "ffprobe_version": None,
                "truth": {
                    "fixture_is_not_ffmpeg": True,
                    "fixture_is_not_production": True,
                    "production_capable": False,
                },
            },
        )


def resolve_media_backend(
    mode: str | None,
    *,
    ffmpeg_path: str | Path | None = None,
    ffprobe_path: str | Path | None = None,
    staging_dir: str | Path | None = None,
    threads: int = 2,
    allow_fixture: bool = True,
) -> MediaBackend:
    """Factory used by workers/tests. Default production path is ffmpeg."""
    key = (mode or "ffmpeg").strip().lower()
    if key in {"fixture", "test", "stub"}:
        if not allow_fixture:
            from Data.modules.media.errors import MEDIA_BACKEND_UNAVAILABLE, MediaDomainError

            raise MediaDomainError(
                MEDIA_BACKEND_UNAVAILABLE,
                "Fixture media backend is not allowed in this context",
            )
        return FixtureMediaBackend(staging_dir=staging_dir)
    from Data.modules.media.ffmpeg_backend import FfmpegMediaBackend

    return FfmpegMediaBackend(
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        staging_dir=staging_dir,
        threads=threads,
    )
