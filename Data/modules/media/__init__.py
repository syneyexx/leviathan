"""Media automation — fixture MediaService + production FFmpeg backends (Wave 7+)."""

from .service import (
    CrossModalHit,
    CrossModalIndex,
    MediaAction,
    MediaAutomationStub,
    MediaJob,
    MediaJobStatus,
    MediaService,
    VideoIngestResult,
)
from .errors import MediaDomainError, MEDIA_ERROR_HTTP_STATUS
from .backends import (
    FixtureMediaBackend,
    MediaBackend,
    MediaBackendKind,
    ThumbnailResult,
    TranscodeResult,
    TransformSpec,
    resolve_media_backend,
)
from .ffmpeg_backend import (
    ALLOWED_AUDIO_CODECS,
    ALLOWED_CONTAINERS,
    ALLOWED_VIDEO_CODECS,
    FfmpegMediaBackend,
    assert_local_media_path,
    disk_preflight_for_media,
)

__all__ = [
    "ALLOWED_AUDIO_CODECS",
    "ALLOWED_CONTAINERS",
    "ALLOWED_VIDEO_CODECS",
    "CrossModalHit",
    "CrossModalIndex",
    "FfmpegMediaBackend",
    "FixtureMediaBackend",
    "MEDIA_ERROR_HTTP_STATUS",
    "MediaAction",
    "MediaAutomationStub",
    "MediaBackend",
    "MediaBackendKind",
    "MediaDomainError",
    "MediaJob",
    "MediaJobStatus",
    "MediaService",
    "ThumbnailResult",
    "TranscodeResult",
    "TransformSpec",
    "VideoIngestResult",
    "assert_local_media_path",
    "disk_preflight_for_media",
    "resolve_media_backend",
]
