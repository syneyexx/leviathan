"""Media domain service — fixture-backed image/video pipelines (U245–U249, U259).

No private model registry / artifact store / scheduler. Outputs are Artifacts;
long work uses shared Jobs/Gateway. Fixture backend avoids ffmpeg in CI.
"""

from __future__ import annotations

import hashlib
import html
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol


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
                "fixture_is_not_ffmpeg": True,
                "fixture_is_not_production": True,
                "production_capable": False,
                "no_private_media_artifact_store": True,
            },
        }


class ArtifactWriter(Protocol):
    def create_from_bytes(self, **kwargs: Any) -> Any: ...


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

    def public_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "path": self.path,
            "duration_ms": self.duration_ms,
            "frames": list(self.frames),
            "shots": list(self.shots),
            "transcript_spans": list(self.transcript_spans),
            "artifact_ids": list(self.artifact_ids),
            "backend": self.backend,
            "truth": {
                "timestamp_citations_preserved": True,
                "fixture_is_not_ffmpeg": True,
                "fixture_is_not_production": True,
                "production_capable": False,
                "timestamps_are_fixture_derived": True,
            },
        }


@dataclass
class CrossModalHit:
    modality: str  # image_region | audio_span | video_scene | text
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
            "truth": {"modality_aware_retrieval": True},
        }


class CrossModalIndex:
    """In-memory modality-aware caption index (U249) — no second vector stack."""

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


class MediaService:
    """Supervised media adaptor — invoke via ExecutionGateway when registered."""

    def __init__(self, *, artifact_store: ArtifactWriter | None = None) -> None:
        self.artifact_store = artifact_store
        self.cross_modal = CrossModalIndex()
        self._videos: dict[str, VideoIngestResult] = {}

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
                return self._vision_inspect(args)
            if action == MediaAction.CROSS_MODAL_SEARCH:
                return self._cross_modal_search(args)
            if action == MediaAction.TRANSCODE:
                return {
                    "status": MediaJobStatus.UNSUPPORTED.value,
                    "detail": "Transcode requires an external media worker binary",
                    "truth": {"fixture_is_not_ffmpeg": True},
                }
        except ValueError as exc:
            return {
                "status": MediaJobStatus.REJECTED.value,
                "error": str(exc),
                "action": action.value,
            }
        return {
            "status": MediaJobStatus.UNSUPPORTED.value,
            "detail": f"Unsupported media action: {action.value}",
        }

    # Backward-compatible stub-shaped API
    def request(self, *, action: MediaAction, path: str | None = None) -> MediaJob:
        result = self.execute(action=action, arguments={"path": path} if path else {})
        status = MediaJobStatus(result.get("status", "FAILED"))
        return MediaJob(
            job_id=str(uuid.uuid4()),
            action=action,
            status=status,
            path=path,
            detail=str(result.get("detail") or result.get("error") or ""),
            metadata={"backend": result.get("backend", "fixture")},
            output=result if status == MediaJobStatus.COMPLETED else None,
        )

    def _probe(self, args: dict[str, Any]) -> dict[str, Any]:
        path = str(args.get("path") or "").strip()
        if not path:
            raise ValueError("PROBE requires path")
        p = Path(path)
        exists = p.exists()
        size = p.stat().st_size if exists and p.is_file() else 0
        suffix = p.suffix.lower()
        kind = "image" if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"} else (
            "video" if suffix in {".mp4", ".webm", ".mkv", ".mov"} else (
                "audio" if suffix in {".wav", ".mp3", ".ogg", ".flac"} else "file"
            )
        )
        return {
            "status": MediaJobStatus.COMPLETED.value,
            "backend": "fixture",
            "path": path,
            "exists": exists,
            "size_bytes": size,
            "media_kind": kind,
            "mime_guess": {
                "image": "image/png",
                "video": "video/mp4",
                "audio": "audio/wav",
                "file": "application/octet-stream",
            }[kind],
            "detail": "Fixture probe (no ffmpeg)",
        }

    def _svg_bytes(self, title: str, subtitle: str = "") -> bytes:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480">'
            f'<rect width="100%" height="100%" fill="#222"/>'
            f'<text x="24" y="48" fill="#eee" font-size="22">{html.escape(title)}</text>'
            f'<text x="24" y="84" fill="#aaa" font-size="14">{html.escape(subtitle)}</text>'
            f"</svg>"
        )
        return svg.encode("utf-8")

    def _store_artifact(
        self,
        data: bytes,
        *,
        artifact_type: str,
        filename: str,
        run_id: str | None,
        metadata: dict[str, Any],
    ) -> str | None:
        if self.artifact_store is None:
            return None
        record = self.artifact_store.create_from_bytes(
            data=data,
            artifact_type=artifact_type,
            producer="media.fixture",
            filename=filename,
            run_id=run_id,
            metadata=metadata,
        )
        return getattr(record, "artifact_id", None) or (
            record.get("artifact_id") if isinstance(record, dict) else None
        )

    def _thumbnail(self, args: dict[str, Any], *, run_id: str | None, request_id: str | None) -> dict[str, Any]:
        path = str(args.get("path") or "asset")
        data = self._svg_bytes("thumbnail", path)
        artifact_id = self._store_artifact(
            data,
            artifact_type="media_thumbnail",
            filename=f"thumb-{uuid.uuid4().hex[:8]}.svg",
            run_id=run_id,
            metadata={"path": path, "request_id": request_id, "backend": "fixture"},
        )
        return {
            "status": MediaJobStatus.COMPLETED.value,
            "backend": "fixture",
            "artifact_id": artifact_id,
            "artifact_refs": [artifact_id] if artifact_id else [],
            "detail": "Fixture thumbnail SVG",
        }

    def _image_generate(self, args: dict[str, Any], *, run_id: str | None, request_id: str | None) -> dict[str, Any]:
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("IMAGE_GENERATE requires prompt")
        model_revision = str(args.get("model_revision") or "fixture-image-v1")
        data = self._svg_bytes("image.generate", prompt[:80])
        artifact_id = self._store_artifact(
            data,
            artifact_type="generated_image",
            filename=f"gen-{uuid.uuid4().hex[:8]}.svg",
            run_id=run_id,
            metadata={
                "prompt": prompt,
                "model_revision": model_revision,
                "request_id": request_id,
                "lineage": "image_generate",
            },
        )
        sync_id = args.get("sync_id")
        if artifact_id:
            self.cross_modal.add(
                modality="image_region",
                ref_id=str(artifact_id),
                caption=prompt,
                sync_id=str(sync_id) if sync_id else None,
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
        data = self._svg_bytes("image.edit", f"{source[:24]} | {instruction[:60]}")
        parent = str(args.get("source_artifact_id") or "")
        artifact_id = self._store_artifact(
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
        )
        return {
            "status": MediaJobStatus.COMPLETED.value,
            "backend": "fixture",
            "artifact_id": artifact_id,
            "artifact_refs": [artifact_id] if artifact_id else [],
            "parent_artifact_id": parent or None,
            "detail": "Fixture image edit on shared Artifact lineage",
            "truth": {"no_separate_media_database": True},
        }

    def _video_ingest(self, args: dict[str, Any], *, run_id: str | None, request_id: str | None) -> dict[str, Any]:
        path = str(args.get("path") or "").strip()
        if not path:
            raise ValueError("VIDEO_INGEST requires path")
        # Fixture: synthesize time-aligned frames/shots/transcript without decoding.
        # duration_ms from args is caller-supplied / synthetic — not measured decode.
        duration_ms = float(args.get("duration_ms") or 3000)
        duration_is_synthetic = True  # fixture never measures real decode duration
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
            frame_svg = self._svg_bytes(f"frame-{idx}", caption)
            aid = self._store_artifact(
                frame_svg,
                artifact_type="video_frame",
                filename=f"{video_id}-f{idx}.svg",
                run_id=run_id,
                metadata={"video_id": video_id, "t_ms": t, "path": path},
            )
            if aid:
                artifact_ids.append(str(aid))
            frames.append({"t_ms": t, "artifact_id": aid, "caption": caption})
            shots.append({"shot_id": f"shot_{idx}", "start_ms": t, "end_ms": min(duration_ms, t + step), "caption": caption})
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
        )
        self._videos[video_id] = result
        out = result.public_dict()
        out["status"] = MediaJobStatus.COMPLETED.value
        out["detail"] = "Fixture video ingest with timestamp citations"
        out["request_id"] = request_id
        out["duration_is_synthetic"] = duration_is_synthetic
        out["truth"] = {
            **(out.get("truth") or {}),
            "fixture_is_not_production": True,
            "production_capable": False,
            "synthetic_latency_not_production_metric": True,
        }
        return out

    def _vision_inspect(self, args: dict[str, Any]) -> dict[str, Any]:
        """High-res tiling / region selection (U243) — fixture OCR/layout hints."""
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
            "truth": {"not_full_resolution_blind_send": True},
        }

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
            "backend": "fixture",
            "query": query,
            "hits": [h.public_dict() for h in hits],
            "count": len(hits),
            "detail": "Modality-aware caption retrieval (no second vector stack)",
            "truth": {"modality_aware_retrieval": True},
        }


# Honest unavailable stub retained for feature-off.
class MediaAutomationStub:
    def request(self, *, action: MediaAction, path: str | None = None) -> MediaJob:
        if not path and action in {MediaAction.PROBE, MediaAction.THUMBNAIL, MediaAction.TRANSCODE, MediaAction.VIDEO_INGEST}:
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
