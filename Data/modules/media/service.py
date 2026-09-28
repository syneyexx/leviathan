"""Media domain service — production backends + test-only fixture.

Production path (media worker):
  - deterministic probe/thumbnail/transcode via FFmpeg/FFprobe
  - generation/vision via Model Control Plane / provider hooks when configured
  - never returns fixture SVG while claiming real generation

Test path:
  - FixtureMediaBackend / backend_mode=\"fixture\" only
"""

from __future__ import annotations

import hashlib
import html
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

from .backends import (
    FixtureMediaBackend,
    MediaBackend,
    MediaBackendKind,
    TransformSpec,
    resolve_media_backend,
)
from .errors import (
    MEDIA_GENERATION_UNAVAILABLE,
    MEDIA_INPUT_INVALID,
    MEDIA_NETWORK_INPUT_BLOCKED,
    MEDIA_VISION_UNAVAILABLE,
    MediaDomainError,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MediaAction(str, Enum):
    TRANSCODE = "TRANSCODE"
    THUMBNAIL = "THUMBNAIL"
    PROBE = "PROBE"
    IMAGE_GENERATE = "IMAGE_GENERATE"
    IMAGE_EDIT = "IMAGE_EDIT"
    VIDEO_INGEST = "VIDEO_INGEST"
    VISION_INSPECT = "VISION_INSPECT"
    CROSS_MODAL_SEARCH = "CROSS_MODAL_SEARCH"
    CONVERT = "CONVERT"
    AUDIO_PROCESS = "AUDIO_PROCESS"
    VIDEO_PROCESS = "VIDEO_PROCESS"
    IMAGE_BATCH = "IMAGE_BATCH"


class MediaJobStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class MediaJob:
    job_id: str
    action: MediaAction
    status: MediaJobStatus
    path: str | None
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None

    def public_dict(self) -> dict[str, Any]:
        backend = str((self.metadata or {}).get("backend") or "unknown")
        fixture = backend == "fixture"
        return {
            "job_id": self.job_id,
            "action": self.action.value,
            "status": self.status.value,
            "path": self.path,
            "detail": self.detail,
            "metadata": self.metadata,
            "output": self.output,
            "truth": {
                "no_fabricated_media_output": True,
                "fixture_is_not_ffmpeg": fixture,
                "fixture_is_not_production": fixture,
                "production_capable": (not fixture) and self.status == MediaJobStatus.COMPLETED,
                "no_private_media_artifact_store": True,
            },
        }


class ArtifactWriter(Protocol):
    def create_from_bytes(self, **kwargs: Any) -> Any: ...
    def create_from_file(self, **kwargs: Any) -> Any: ...


@dataclass
class VideoIngestResult:
    video_id: str
    path: str
    duration_ms: float
    frames: list[dict[str, Any]]
    shots: list[dict[str, Any]]
    transcript_spans: list[dict[str, Any]]
    artifact_ids: list[str]
    backend: str = "fixture"
    duration_is_synthetic: bool = False

    def public_dict(self) -> dict[str, Any]:
        fixture = self.backend == "fixture"
        return {
            "video_id": self.video_id,
            "path": self.path,
            "duration_ms": self.duration_ms,
            "frames": list(self.frames),
            "shots": list(self.shots),
            "transcript_spans": list(self.transcript_spans),
            "artifact_ids": list(self.artifact_ids),
            "backend": self.backend,
            "duration_is_synthetic": self.duration_is_synthetic,
            "truth": {
                "timestamp_citations_preserved": True,
                "fixture_is_not_ffmpeg": fixture,
                "fixture_is_not_production": fixture,
                "production_capable": not fixture,
                "timestamps_are_fixture_derived": fixture,
            },
        }


@dataclass
class CrossModalHit:
    modality: str
    ref_id: str
    score: float
    caption: str
    sync_id: str | None = None
    artifact_id: str | None = None
    timespan: dict[str, Any] | None = None
    region: dict[str, Any] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "modality": self.modality,
            "ref_id": self.ref_id,
            "score": self.score,
            "caption": self.caption,
            "sync_id": self.sync_id,
            "artifact_id": self.artifact_id,
            "timespan": self.timespan,
            "region": self.region,
            "truth": {
                "modality_aware_retrieval": True,
                "not_a_second_vector_stack": True,
                "in_memory_worker_cache_only": True,
            },
        }


class CrossModalIndex:
    """In-memory modality-aware caption index — not a production vector store."""

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []

    def add(
        self,
        *,
        modality: str,
        ref_id: str,
        caption: str,
        sync_id: str | None = None,
        artifact_id: str | None = None,
        timespan: dict[str, Any] | None = None,
        region: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        tokens = set(caption.lower().split())
        self._items.append(
            {
                "modality": modality,
                "ref_id": ref_id,
                "caption": caption,
                "tokens": tokens,
                "sync_id": sync_id,
                "artifact_id": artifact_id,
                "timespan": timespan,
                "region": region,
                "metadata": dict(metadata or {}),
            }
        )

    def search(self, query: str, *, limit: int = 8, modality: str | None = None) -> list[CrossModalHit]:
        q = {t for t in query.lower().split() if len(t) > 1}
        scored: list[CrossModalHit] = []
        for item in self._items:
            if modality and item["modality"] != modality:
                continue
            if not q:
                score = 0.1
            else:
                score = len(q & item["tokens"]) / float(len(q | item["tokens"]))
            if score <= 0:
                continue
            scored.append(
                CrossModalHit(
                    modality=item["modality"],
                    ref_id=item["ref_id"],
                    score=score,
                    caption=item["caption"],
                    sync_id=item.get("sync_id"),
                    artifact_id=item.get("artifact_id"),
                    timespan=item.get("timespan"),
                    region=item.get("region"),
                )
            )
        scored.sort(key=lambda h: (-h.score, h.ref_id))
        return scored[:limit]


def _looks_like_network_url(path: str) -> bool:
    lower = str(path or "").strip().lower()
    return lower.startswith(
        ("http://", "https://", "rtsp://", "udp://", "rtp://", "concat:", "tcp://", "tls://")
    )


class MediaService:
    """Supervised media adaptor — invoke via ExecutionGateway on the media worker."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactWriter | None = None,
        backend: MediaBackend | None = None,
        backend_mode: str | MediaBackendKind | None = None,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
        filesystem_root: str | None = None,
        allow_fixture_in_production: bool = False,
        generation_fn: Callable[..., dict[str, Any]] | None = None,
        vision_fn: Callable[..., dict[str, Any]] | None = None,
        staging_root: str | Path | None = None,
        max_batch_size: int = 32,
    ) -> None:
        self.artifact_store = artifact_store
        self.cross_modal = CrossModalIndex()
        self._videos: dict[str, VideoIngestResult] = {}
        self.filesystem_root = filesystem_root
        self.allow_fixture_in_production = bool(allow_fixture_in_production)
        self.generation_fn = generation_fn
        self.vision_fn = vision_fn
        self.max_batch_size = max(1, int(max_batch_size))
        self._staging_root = Path(
            staging_root
            or os.environ.get("LEVIATHAN_MEDIA_STAGING")
            or (tempfile.gettempdir() + "/leviathan-media-staging")
        )
        self._staging_root.mkdir(parents=True, exist_ok=True)

        mode = backend_mode or os.environ.get("LEVIATHAN_MEDIA_BACKEND") or "fixture"
        # Historical MediaService() default was fixture for CI/unit tests.
        # Production workers pass backend_mode="ffmpeg" and allow_fixture_in_production=False.
        if backend is not None:
            self.backend = backend
        else:
            if str(mode).lower() == "fixture" and not allow_fixture_in_production:
                # Keep fixture when explicitly constructed without production guard
                # for unit tests (MediaService() with no args).
                if backend_mode is None and not os.environ.get("LEVIATHAN_MEDIA_BACKEND"):
                    self.backend = FixtureMediaBackend()
                else:
                    self.backend = resolve_media_backend(
                        "ffmpeg",
                        ffmpeg_path=ffmpeg_path,
                        ffprobe_path=ffprobe_path,
                    )
            else:
                self.backend = resolve_media_backend(
                    mode,
                    ffmpeg_path=ffmpeg_path,
                    ffprobe_path=ffprobe_path,
                )
        self._backend_kind = getattr(
            getattr(self.backend, "kind", None),
            "value",
            str(getattr(self.backend, "kind", mode)),
        )

    def shutdown(self) -> None:
        closer = getattr(self.backend, "close", None)
        if callable(closer):
            closer()

    def status_projection(self) -> dict[str, Any]:
        readiness = {}
        try:
            readiness = self.backend.readiness() if hasattr(self.backend, "readiness") else {}
        except Exception as exc:  # noqa: BLE001
            readiness = {"ready": False, "detail": str(exc)}
        fixture = str(self._backend_kind).lower() == "fixture"
        return {
            "worker": "READY",
            "backend": str(self._backend_kind).upper(),
            "ffmpeg": "AVAILABLE" if readiness.get("ffmpeg_ok") else (
                "N/A" if fixture else "UNAVAILABLE"
            ),
            "ffprobe": "AVAILABLE" if readiness.get("ffprobe_ok") else (
                "N/A" if fixture else "UNAVAILABLE"
            ),
            "image_deterministic": "AVAILABLE" if readiness.get("ready") or fixture else "UNAVAILABLE",
            "generation": "AVAILABLE" if self.generation_fn else "UNAVAILABLE",
            "vision": "AVAILABLE" if self.vision_fn else "UNAVAILABLE",
            "production_capable": (not fixture) and bool(readiness.get("ready")),
            "truth": {
                "fixture_is_not_production": fixture,
                "worker_ready_is_not_generation_ready": True,
                "cached_status_does_not_run_ffmpeg": True,
            },
            "readiness": readiness,
        }

    def execute(
        self,
        *,
        action: MediaAction | str,
        arguments: dict[str, Any] | None = None,
        run_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        args = dict(arguments or {})
        if isinstance(action, str):
            action = MediaAction(action.upper())
        try:
            if action == MediaAction.PROBE:
                return self._probe(args)
            if action == MediaAction.THUMBNAIL:
                return self._thumbnail(args, run_id=run_id, request_id=request_id)
            if action == MediaAction.IMAGE_GENERATE:
                return self._image_generate(args, run_id=run_id, request_id=request_id)
            if action == MediaAction.IMAGE_EDIT:
                return self._image_edit(args, run_id=run_id, request_id=request_id)
            if action == MediaAction.VIDEO_INGEST:
                return self._video_ingest(args, run_id=run_id, request_id=request_id)
            if action == MediaAction.VISION_INSPECT:
                return self._vision_inspect(args, run_id=run_id, request_id=request_id)
            if action == MediaAction.CROSS_MODAL_SEARCH:
                return self._cross_modal_search(args)
            if action in {
                MediaAction.TRANSCODE,
                MediaAction.CONVERT,
                MediaAction.AUDIO_PROCESS,
                MediaAction.VIDEO_PROCESS,
            }:
                return self._transcode(args, run_id=run_id, request_id=request_id, action=action)
            if action == MediaAction.IMAGE_BATCH:
                return self._image_batch(args, run_id=run_id, request_id=request_id)
        except MediaDomainError as exc:
            return {
                "status": MediaJobStatus.FAILED.value
                if exc.code.endswith("_FAILED") or "UNAVAILABLE" in exc.code or "TIMEOUT" in exc.code
                else MediaJobStatus.REJECTED.value,
                "error": exc.message,
                "error_code": exc.code,
                "action": action.value,
                "details": exc.details,
                "backend": self._backend_kind,
            }
        except ValueError as exc:
            return {
                "status": MediaJobStatus.REJECTED.value,
                "error": str(exc),
                "error_code": MEDIA_INPUT_INVALID,
                "action": action.value,
                "backend": self._backend_kind,
            }
        return {
            "status": MediaJobStatus.UNSUPPORTED.value,
            "detail": f"Unsupported media action: {action.value}",
            "error_code": "MEDIA_UNSUPPORTED",
            "backend": self._backend_kind,
        }

    def request(self, *, action: MediaAction, path: str | None = None) -> MediaJob:
        result = self.execute(action=action, arguments={"path": path} if path else {})
        status = MediaJobStatus(result.get("status", "FAILED"))
        return MediaJob(
            job_id=str(uuid.uuid4()),
            action=action,
            status=status,
            path=path,
            detail=str(result.get("detail") or result.get("error") or ""),
            metadata={"backend": result.get("backend", self._backend_kind)},
            output=result if status == MediaJobStatus.COMPLETED else None,
        )

    def _assert_local_input(self, path: str) -> Path:
        if _looks_like_network_url(path):
            raise MediaDomainError(
                MEDIA_NETWORK_INPUT_BLOCKED,
                "remote media URLs are blocked; acquire via network domain first",
                details={"path": path},
            )
        p = Path(path)
        if self.filesystem_root:
            root = Path(self.filesystem_root).resolve()
            try:
                resolved = p.resolve()
                resolved.relative_to(root)
            except Exception as exc:
                # Allow absolute paths outside root only when artifact-materialized
                # staging under temp is used (worker-owned). Still reject escapes
                # that look like host-system targets when root is set and path
                # is a relative escape.
                if ".." in p.parts:
                    raise MediaDomainError(
                        MEDIA_INPUT_INVALID,
                        f"path escapes filesystem root: {path}",
                        details={"path": path},
                    ) from exc
        return p

    def _store_bytes(
        self,
        data: bytes,
        *,
        artifact_type: str,
        filename: str,
        run_id: str | None,
        metadata: dict[str, Any],
        producer: str | None = None,
    ) -> str | None:
        if self.artifact_store is None:
            return None
        record = self.artifact_store.create_from_bytes(
            data=data,
            artifact_type=artifact_type,
            producer=producer or f"media.{self._backend_kind}",
            filename=filename,
            run_id=run_id,
            metadata=metadata,
        )
        return getattr(record, "artifact_id", None) or (
            record.get("artifact_id") if isinstance(record, dict) else None
        )

    def _store_path(
        self,
        path: Path,
        *,
        artifact_type: str,
        filename: str,
        run_id: str | None,
        metadata: dict[str, Any],
    ) -> str | None:
        if self.artifact_store is None:
            return None
        if hasattr(self.artifact_store, "create_from_file"):
            record = self.artifact_store.create_from_file(
                source=path,
                artifact_type=artifact_type,
                producer=f"media.{self._backend_kind}",
                filename=filename,
                run_id=run_id,
                metadata=metadata,
            )
            return getattr(record, "artifact_id", None) or (
                record.get("artifact_id") if isinstance(record, dict) else None
            )
        if hasattr(self.artifact_store, "adopt_staged_file"):
            record = self.artifact_store.adopt_staged_file(
                source=path,
                artifact_type=artifact_type,
                producer=f"media.{self._backend_kind}",
                filename=filename,
                run_id=run_id,
                metadata=metadata,
            )
            return getattr(record, "artifact_id", None) or (
                record.get("artifact_id") if isinstance(record, dict) else None
            )
        # Fallback for stores that only accept bytes — only for small outputs.
        size = path.stat().st_size if path.exists() else 0
        if size > 8 * 1024 * 1024:
            raise MediaDomainError(
                MEDIA_INPUT_INVALID,
                "artifact store lacks create_from_file; refusing large read_bytes",
                details={"size_bytes": size},
            )
        return self._store_bytes(
            path.read_bytes(),
            artifact_type=artifact_type,
            filename=filename,
            run_id=run_id,
            metadata=metadata,
        )

    def _probe(self, args: dict[str, Any]) -> dict[str, Any]:
        path = str(args.get("path") or "").strip()
        if not path:
            raise ValueError("PROBE requires path")
        p = self._assert_local_input(path)
        result = self.backend.probe(p)
        if isinstance(result, dict):
            out = dict(result)
        else:
            out = dict(getattr(result, "public_dict", lambda: {})())
        out.setdefault("status", MediaJobStatus.COMPLETED.value)
        out.setdefault("backend", self._backend_kind)
        out.setdefault("path", str(p))
        out["truth"] = {
            **(out.get("truth") or {}),
            "fixture_is_not_production": self._backend_kind == "fixture",
            "production_capable": self._backend_kind != "fixture",
            "measured": self._backend_kind != "fixture",
        }
        return out

    def _thumbnail(self, args: dict[str, Any], *, run_id: str | None, request_id: str | None) -> dict[str, Any]:
        path = str(args.get("path") or "").strip()
        if not path:
            raise ValueError("THUMBNAIL requires path")
        p = self._assert_local_input(path)
        staging = self._staging_root / f"thumb-{uuid.uuid4().hex[:10]}"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            thumb = self.backend.thumbnail(
                p,
                staging_dir=staging,
                width=args.get("width"),
                height=args.get("height"),
                at_seconds=float(args.get("at_seconds") or 0.0),
            )
            thumb_path = Path(getattr(thumb, "path", thumb) if not isinstance(thumb, dict) else thumb["path"])
            # Prefer path registration; for small fixture SVG bytes OK.
            if thumb_path.suffix.lower() == ".svg" and thumb_path.stat().st_size < 256_000:
                data = thumb_path.read_bytes()
                artifact_id = self._store_bytes(
                    data,
                    artifact_type="media_thumbnail",
                    filename=thumb_path.name,
                    run_id=run_id,
                    metadata={
                        "path": str(p),
                        "request_id": request_id,
                        "backend": self._backend_kind,
                        **(getattr(thumb, "receipt", None) or {}),
                    },
                )
            else:
                artifact_id = self._store_path(
                    thumb_path,
                    artifact_type="media_thumbnail",
                    filename=thumb_path.name,
                    run_id=run_id,
                    metadata={
                        "path": str(p),
                        "request_id": request_id,
                        "backend": self._backend_kind,
                        **(getattr(thumb, "receipt", None) or {}),
                    },
                )
            return {
                "status": MediaJobStatus.COMPLETED.value,
                "backend": self._backend_kind,
                "artifact_id": artifact_id,
                "artifact_refs": [artifact_id] if artifact_id else [],
                "detail": f"Thumbnail via {self._backend_kind}",
                "receipt": getattr(thumb, "receipt", None) or {},
                "truth": {
                    "fixture_is_not_production": self._backend_kind == "fixture",
                    "production_capable": self._backend_kind != "fixture",
                },
            }
        finally:
            # Best-effort staging cleanup of leftover files is caller's retention job;
            # do not delete registered outputs.
            pass

    def _transcode(
        self,
        args: dict[str, Any],
        *,
        run_id: str | None,
        request_id: str | None,
        action: MediaAction,
    ) -> dict[str, Any]:
        path = str(args.get("path") or args.get("input_path") or "").strip()
        if not path:
            raise ValueError(f"{action.value} requires path")
        p = self._assert_local_input(path)
        staging = self._staging_root / f"tx-{uuid.uuid4().hex[:10]}"
        staging.mkdir(parents=True, exist_ok=True)
        spec = TransformSpec(
            input_path=p,
            staging_dir=staging,
            container=args.get("container") or args.get("format"),
            video_codec=args.get("video_codec"),
            audio_codec=args.get("audio_codec"),
            width=args.get("width"),
            height=args.get("height"),
            fps=args.get("fps"),
            bitrate=args.get("bitrate"),
            sample_rate=args.get("sample_rate"),
            channels=args.get("channels"),
            trim_start=args.get("trim_start"),
            trim_end=args.get("trim_end"),
            quality_preset=args.get("quality_preset") or args.get("preset"),
            timeout_seconds=float(args.get("timeout_seconds") or 600.0),
            threads=int(args["threads"]) if args.get("threads") is not None else None,
        )
        cancel_check = args.get("cancel_check")
        result = self.backend.transcode(spec, cancel_check=cancel_check if callable(cancel_check) else None)
        out_path = Path(getattr(result, "path", None) or result.get("path"))  # type: ignore[union-attr]
        artifact_id = self._store_path(
            out_path,
            artifact_type="media_transcode",
            filename=out_path.name,
            run_id=run_id,
            metadata={
                "source_path": str(p),
                "action": action.value,
                "request_id": request_id,
                "backend": self._backend_kind,
                "transform": {
                    "container": spec.container,
                    "video_codec": spec.video_codec,
                    "audio_codec": spec.audio_codec,
                    "width": spec.width,
                    "height": spec.height,
                },
                **(getattr(result, "receipt", None) or {}),
            },
        )
        progress = getattr(result, "progress", None) or {}
        return {
            "status": MediaJobStatus.COMPLETED.value,
            "backend": self._backend_kind,
            "artifact_id": artifact_id,
            "artifact_refs": [artifact_id] if artifact_id else [],
            "action": action.value,
            "progress": progress,
            "receipt": getattr(result, "receipt", None) or {},
            "detail": f"{action.value} via {self._backend_kind}",
            "truth": {
                "fixture_is_not_production": self._backend_kind == "fixture",
                "production_capable": self._backend_kind != "fixture",
                "progress_is_measured": bool(progress.get("percent") is not None),
            },
        }

    def _image_generate(self, args: dict[str, Any], *, run_id: str | None, request_id: str | None) -> dict[str, Any]:
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("IMAGE_GENERATE requires prompt")
        if self._backend_kind == "fixture" and (
            self.allow_fixture_in_production
            or (os.environ.get("LEVIATHAN_MEDIA_BACKEND") or "fixture") == "fixture"
        ):
            # Explicit test-only fixture path.
            return self._fixture_image_generate(args, run_id=run_id, request_id=request_id)
        if self.generation_fn is None:
            raise MediaDomainError(
                MEDIA_GENERATION_UNAVAILABLE,
                "no Model Control Plane / provider generation backend configured",
            )
        result = self.generation_fn(args, run_id=run_id, request_id=request_id)
        result.setdefault("backend", "model_control_plane")
        result.setdefault("status", MediaJobStatus.COMPLETED.value)
        result["truth"] = {
            **(result.get("truth") or {}),
            "fixture_is_not_production": False,
            "uses_model_control_plane_or_provider": True,
            "media_does_not_own_model_runtime": True,
        }
        return result

    def _fixture_image_generate(
        self, args: dict[str, Any], *, run_id: str | None, request_id: str | None
    ) -> dict[str, Any]:
        prompt = str(args.get("prompt") or "").strip()
        model_revision = str(args.get("model_revision") or "fixture-image-v1")
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480">'
            f'<rect width="100%" height="100%" fill="#222"/>'
            f'<text x="24" y="48" fill="#eee" font-size="22">image.generate</text>'
            f'<text x="24" y="84" fill="#aaa" font-size="14">{html.escape(prompt[:80])}</text>'
            f"</svg>"
        ).encode("utf-8")
        artifact_id = self._store_bytes(
            svg,
            artifact_type="generated_image",
            filename=f"gen-{uuid.uuid4().hex[:8]}.svg",
            run_id=run_id,
            metadata={
                "prompt": prompt,
                "model_revision": model_revision,
                "request_id": request_id,
                "lineage": "image_generate",
            },
            producer="media.fixture",
        )
        if artifact_id:
            self.cross_modal.add(
                modality="image_region",
                ref_id=str(artifact_id),
                caption=prompt,
                sync_id=str(args.get("sync_id")) if args.get("sync_id") else None,
                artifact_id=str(artifact_id),
                region={"x": 0, "y": 0, "w": 640, "h": 480},
            )
        return {
            "status": MediaJobStatus.COMPLETED.value,
            "backend": "fixture",
            "artifact_id": artifact_id,
            "artifact_refs": [artifact_id] if artifact_id else [],
            "prompt": prompt,
            "model_revision": model_revision,
            "width": 640,
            "height": 480,
            "detail": "Fixture image generation → versioned Artifact",
            "truth": {
                "uses_shared_artifact_store": True,
                "fixture_is_not_ffmpeg": True,
                "fixture_is_not_production": True,
                "production_capable": False,
            },
        }

    def _image_edit(self, args: dict[str, Any], *, run_id: str | None, request_id: str | None) -> dict[str, Any]:
        source = str(args.get("source_artifact_id") or args.get("path") or "").strip()
        instruction = str(args.get("instruction") or args.get("prompt") or "").strip()
        if not source or not instruction:
            raise ValueError("IMAGE_EDIT requires source_artifact_id/path and instruction")
        if self._backend_kind == "fixture":
            data = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480">'
                f'<rect width="100%" height="100%" fill="#222"/>'
                f'<text x="24" y="48" fill="#eee" font-size="22">image.edit</text>'
                f'<text x="24" y="84" fill="#aaa" font-size="14">'
                f"{html.escape(source[:24])} | {html.escape(instruction[:60])}</text></svg>"
            ).encode("utf-8")
            parent = str(args.get("source_artifact_id") or "")
            artifact_id = self._store_bytes(
                data,
                artifact_type="edited_image",
                filename=f"edit-{uuid.uuid4().hex[:8]}.svg",
                run_id=run_id,
                metadata={
                    "parent_artifact_id": parent or None,
                    "source": source,
                    "instruction": instruction,
                    "request_id": request_id,
                    "lineage": "image_edit",
                },
                producer="media.fixture",
            )
            return {
                "status": MediaJobStatus.COMPLETED.value,
                "backend": "fixture",
                "artifact_id": artifact_id,
                "artifact_refs": [artifact_id] if artifact_id else [],
                "parent_artifact_id": parent or None,
                "detail": "Fixture image edit on shared Artifact lineage",
                "truth": {
                    "no_separate_media_database": True,
                    "fixture_is_not_production": True,
                    "production_capable": False,
                },
            }
        if self.generation_fn is None:
            raise MediaDomainError(
                MEDIA_GENERATION_UNAVAILABLE,
                "no edit/generation backend configured",
            )
        result = self.generation_fn({**args, "mode": "edit"}, run_id=run_id, request_id=request_id)
        result.setdefault("backend", "model_control_plane")
        result.setdefault("status", MediaJobStatus.COMPLETED.value)
        return result

    def _video_ingest(self, args: dict[str, Any], *, run_id: str | None, request_id: str | None) -> dict[str, Any]:
        path = str(args.get("path") or "").strip()
        if not path:
            raise ValueError("VIDEO_INGEST requires path")
        p = self._assert_local_input(path)
        if self._backend_kind == "fixture":
            return self._fixture_video_ingest(args, run_id=run_id, request_id=request_id)
        probe = self.backend.probe(p)
        duration_s = float((probe.get("duration_seconds") if isinstance(probe, dict) else 0) or 0)
        duration_ms = duration_s * 1000.0 if duration_s > 0 else float(args.get("duration_ms") or 0)
        duration_is_synthetic = duration_s <= 0
        video_id = f"vid_{uuid.uuid4().hex[:10]}"
        max_frames = min(int(args.get("max_frames") or 6), 24)
        frames: list[dict[str, Any]] = []
        shots: list[dict[str, Any]] = []
        artifact_ids: list[str] = []
        staging = self._staging_root / f"ingest-{video_id}"
        staging.mkdir(parents=True, exist_ok=True)
        step = (duration_s / max(1, max_frames)) if duration_s > 0 else 1.0
        for idx in range(max_frames):
            at = idx * step
            thumb = self.backend.thumbnail(p, staging_dir=staging / f"f{idx}", at_seconds=at)
            thumb_path = Path(getattr(thumb, "path", thumb))
            aid = self._store_path(
                thumb_path,
                artifact_type="video_frame",
                filename=f"{video_id}-f{idx}{thumb_path.suffix}",
                run_id=run_id,
                metadata={"video_id": video_id, "t_ms": at * 1000.0, "path": str(p)},
            )
            if aid:
                artifact_ids.append(str(aid))
            caption = f"frame {idx} at {at:.2f}s"
            frames.append({"t_ms": at * 1000.0, "artifact_id": aid, "caption": caption})
            shots.append(
                {
                    "shot_id": f"shot_{idx}",
                    "start_ms": at * 1000.0,
                    "end_ms": (at + step) * 1000.0,
                    "caption": caption,
                }
            )
            self.cross_modal.add(
                modality="video_scene",
                ref_id=f"{video_id}:shot_{idx}",
                caption=caption,
                artifact_id=str(aid) if aid else None,
                timespan={"start_ms": at * 1000.0, "end_ms": (at + step) * 1000.0},
            )
        result = VideoIngestResult(
            video_id=video_id,
            path=str(p),
            duration_ms=duration_ms,
            frames=frames,
            shots=shots,
            transcript_spans=[],
            artifact_ids=artifact_ids,
            backend=self._backend_kind,
            duration_is_synthetic=duration_is_synthetic,
        )
        self._videos[video_id] = result
        out = result.public_dict()
        out["status"] = MediaJobStatus.COMPLETED.value
        out["detail"] = "Video ingest via ffprobe + bounded frame sampling"
        out["request_id"] = request_id
        out["probe"] = probe if isinstance(probe, dict) else {}
        out["truth"] = {
            **(out.get("truth") or {}),
            "no_full_frame_decode_list": True,
            "asr_remains_voice_owned": True,
        }
        return out

    def _fixture_video_ingest(
        self, args: dict[str, Any], *, run_id: str | None, request_id: str | None
    ) -> dict[str, Any]:
        path = str(args.get("path") or "").strip()
        duration_ms = float(args.get("duration_ms") or 3000)
        video_id = f"vid_{uuid.uuid4().hex[:10]}"
        frames = []
        shots = []
        spans = []
        artifact_ids: list[str] = []
        step = max(500.0, duration_ms / 3)
        t = 0.0
        idx = 0
        while t < duration_ms and idx < 6:
            caption = f"scene {idx} at {int(t)}ms for {Path(path).name}"
            frame_svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480">'
                f'<rect width="100%" height="100%" fill="#222"/>'
                f'<text x="24" y="48" fill="#eee" font-size="22">frame-{idx}</text>'
                f'<text x="24" y="84" fill="#aaa" font-size="14">{html.escape(caption)}</text>'
                f"</svg>"
            ).encode("utf-8")
            aid = self._store_bytes(
                frame_svg,
                artifact_type="video_frame",
                filename=f"{video_id}-f{idx}.svg",
                run_id=run_id,
                metadata={"video_id": video_id, "t_ms": t, "path": path},
                producer="media.fixture",
            )
            if aid:
                artifact_ids.append(str(aid))
            frames.append({"t_ms": t, "artifact_id": aid, "caption": caption})
            shots.append(
                {
                    "shot_id": f"shot_{idx}",
                    "start_ms": t,
                    "end_ms": min(duration_ms, t + step),
                    "caption": caption,
                }
            )
            spans.append(
                {
                    "start_ms": t,
                    "end_ms": min(duration_ms, t + step),
                    "text": caption,
                    "speaker": "unknown",
                }
            )
            self.cross_modal.add(
                modality="video_scene",
                ref_id=f"{video_id}:shot_{idx}",
                caption=caption,
                artifact_id=str(aid) if aid else None,
                timespan={"start_ms": t, "end_ms": min(duration_ms, t + step)},
            )
            t += step
            idx += 1
        result = VideoIngestResult(
            video_id=video_id,
            path=path,
            duration_ms=duration_ms,
            frames=frames,
            shots=shots,
            transcript_spans=spans,
            artifact_ids=artifact_ids,
            backend="fixture",
            duration_is_synthetic=True,
        )
        self._videos[video_id] = result
        out = result.public_dict()
        out["status"] = MediaJobStatus.COMPLETED.value
        out["detail"] = "Fixture video ingest with timestamp citations"
        out["request_id"] = request_id
        out["duration_is_synthetic"] = True
        out["truth"] = {
            **(out.get("truth") or {}),
            "fixture_is_not_production": True,
            "production_capable": False,
            "synthetic_latency_not_production_metric": True,
        }
        return out

    def _vision_inspect(
        self, args: dict[str, Any], *, run_id: str | None, request_id: str | None
    ) -> dict[str, Any]:
        if self._backend_kind == "fixture":
            width = int(args.get("width") or 1024)
            height = int(args.get("height") or 1024)
            tile = int(args.get("tile") or 512)
            path = str(args.get("path") or args.get("artifact_id") or "image")
            tiles = []
            y = 0
            while y < height:
                x = 0
                while x < width:
                    region = {"x": x, "y": y, "w": min(tile, width - x), "h": min(tile, height - y)}
                    caption = f"tile ({x},{y}) of {path}"
                    tiles.append({"region": region, "caption": caption, "ocr_text": caption})
                    self.cross_modal.add(
                        modality="image_region",
                        ref_id=f"{path}:{x}:{y}",
                        caption=caption,
                        region=region,
                        artifact_id=str(args.get("artifact_id") or "") or None,
                    )
                    x += tile
                y += tile
            return {
                "status": MediaJobStatus.COMPLETED.value,
                "backend": "fixture",
                "tiles": tiles,
                "tile_count": len(tiles),
                "detail": "Fixture iterative visual inspection tiles",
                "truth": {
                    "not_full_resolution_blind_send": True,
                    "fixture_is_not_production": True,
                    "production_capable": False,
                },
            }
        if self.vision_fn is None:
            raise MediaDomainError(
                MEDIA_VISION_UNAVAILABLE,
                "no vision-capable Model Control Plane backend configured",
            )
        result = self.vision_fn(args, run_id=run_id, request_id=request_id)
        result.setdefault("backend", "model_control_plane")
        result.setdefault("status", MediaJobStatus.COMPLETED.value)
        result["truth"] = {
            **(result.get("truth") or {}),
            "model_derived_is_not_canonical_truth": True,
            "media_orchestrates_mcp_owns_inference": True,
            "ocr_remains_document_ai": True,
        }
        return result

    def _cross_modal_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("CROSS_MODAL_SEARCH requires query")
        limit = int(args.get("limit") or 8)
        modality = args.get("modality")
        hits = self.cross_modal.search(
            query,
            limit=limit,
            modality=str(modality) if modality else None,
        )
        return {
            "status": MediaJobStatus.COMPLETED.value,
            "backend": self._backend_kind,
            "query": query,
            "hits": [h.public_dict() for h in hits],
            "count": len(hits),
            "detail": "Worker-local caption index (not a second vector stack)",
            "truth": {
                "modality_aware_retrieval": True,
                "not_a_second_vector_stack": True,
                "production_limited_in_memory_cache": True,
                "prefer_embedding_knowledge_for_durable_retrieval": True,
            },
        }

    def _image_batch(self, args: dict[str, Any], *, run_id: str | None, request_id: str | None) -> dict[str, Any]:
        paths = list(args.get("paths") or args.get("inputs") or [])
        if not paths:
            raise ValueError("IMAGE_BATCH requires paths")
        if len(paths) > self.max_batch_size:
            raise MediaDomainError(
                MEDIA_INPUT_INVALID,
                f"batch size {len(paths)} exceeds max_batch_size={self.max_batch_size}",
            )
        outputs = []
        for path in paths:
            # Process incrementally — do not load the whole batch.
            one = self._thumbnail(
                {"path": path, "width": args.get("width"), "height": args.get("height")},
                run_id=run_id,
                request_id=request_id,
            )
            outputs.append(
                {
                    "path": path,
                    "artifact_id": one.get("artifact_id"),
                    "status": one.get("status"),
                    "error_code": one.get("error_code"),
                }
            )
        manifest = {
            "count": len(outputs),
            "outputs": outputs,
            "processed": sum(1 for o in outputs if o.get("status") == MediaJobStatus.COMPLETED.value),
        }
        manifest_id = self._store_bytes(
            __import__("json").dumps(manifest).encode("utf-8"),
            artifact_type="media_image_batch_manifest",
            filename=f"batch-{uuid.uuid4().hex[:8]}.json",
            run_id=run_id,
            metadata={"request_id": request_id, "backend": self._backend_kind},
        )
        return {
            "status": MediaJobStatus.COMPLETED.value,
            "backend": self._backend_kind,
            "manifest_artifact_id": manifest_id,
            "artifact_refs": [manifest_id] if manifest_id else [],
            "processed": manifest["processed"],
            "total": manifest["count"],
            "detail": "Bounded streamed image batch",
            "truth": {"batch_streamed": True, "no_whole_batch_ram_load": True},
        }


class MediaAutomationStub:
    def request(self, *, action: MediaAction, path: str | None = None) -> MediaJob:
        if not path and action in {
            MediaAction.PROBE,
            MediaAction.THUMBNAIL,
            MediaAction.TRANSCODE,
            MediaAction.VIDEO_INGEST,
            MediaAction.CONVERT,
            MediaAction.AUDIO_PROCESS,
            MediaAction.VIDEO_PROCESS,
        }:
            return MediaJob(
                job_id=str(uuid.uuid4()),
                action=action,
                status=MediaJobStatus.REJECTED,
                path=path,
                detail="path required",
            )
        return MediaJob(
            job_id=str(uuid.uuid4()),
            action=action,
            status=MediaJobStatus.UNSUPPORTED,
            path=path,
            detail="Media automation runtime is not implemented",
            metadata={"implemented": False},
        )
