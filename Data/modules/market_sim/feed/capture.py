"""Optional market feed capture via ArtifactStore — never per-tick SQLite."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Data.modules.market_sim.feed.types import CaptureMode
from Data.modules.market_sim.market_event import MarketEvent, MarketEventType


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CaptureSegment:
    segment_id: str
    feed_id: str
    provider_id: str
    symbol: str
    mode: CaptureMode
    started_at: str
    path: str
    event_count: int = 0
    closed: bool = False
    content_hash: str | None = None
    artifact_id: str | None = None


class FeedCaptureWriter:
    """Append/rotated segment writer. Registers artifacts on segment close."""

    def __init__(
        self,
        root: Path,
        *,
        mode: CaptureMode = CaptureMode.BAR_ONLY,
        segment_seconds: float = 300.0,
        artifact_store: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self.mode = mode
        self.segment_seconds = max(30.0, float(segment_seconds))
        self.artifact_store = artifact_store
        self._lock = threading.Lock()
        self._open: dict[str, CaptureSegment] = {}
        self._handles: dict[str, Any] = {}
        self._segment_started: dict[str, float] = {}
        self.closed_segments: list[CaptureSegment] = []

    def should_capture(self, event: MarketEvent) -> bool:
        if self.mode == CaptureMode.OFF:
            return False
        if self.mode == CaptureMode.BAR_ONLY:
            return event.event_type in {MarketEventType.BAR_CLOSE, MarketEventType.BAR_UPDATE}
        return True

    def write(self, feed_id: str, event: MarketEvent) -> None:
        if not self.should_capture(event):
            return
        key = f"{feed_id}:{event.symbol}"
        with self._lock:
            self._ensure_segment(key, feed_id, event)
            fh = self._handles[key]
            fh.write(json.dumps(event.public_dict(), separators=(",", ":")) + "\n")
            fh.flush()
            seg = self._open[key]
            seg.event_count += 1
            started = self._segment_started[key]
            if time.monotonic() - started >= self.segment_seconds:
                self._close_segment_locked(key)

    def close_all(self) -> list[CaptureSegment]:
        with self._lock:
            keys = list(self._open.keys())
            for key in keys:
                self._close_segment_locked(key)
            return list(self.closed_segments)

    def _ensure_segment(self, key: str, feed_id: str, event: MarketEvent) -> None:
        if key in self._open:
            return
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        seg_id = f"seg_{uuid.uuid4().hex[:12]}"
        directory = self.root / event.provider_id / event.symbol / day
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{seg_id}.jsonl"
        fh = path.open("a", encoding="utf-8")
        seg = CaptureSegment(
            segment_id=seg_id,
            feed_id=feed_id,
            provider_id=event.provider_id,
            symbol=event.symbol,
            mode=self.mode,
            started_at=_utc_now(),
            path=str(path),
        )
        self._open[key] = seg
        self._handles[key] = fh
        self._segment_started[key] = time.monotonic()

    def _close_segment_locked(self, key: str) -> None:
        seg = self._open.pop(key, None)
        fh = self._handles.pop(key, None)
        self._segment_started.pop(key, None)
        if seg is None:
            return
        if fh is not None:
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass
        path = Path(seg.path)
        data = path.read_bytes() if path.exists() else b""
        import hashlib

        seg.content_hash = hashlib.sha256(data).hexdigest()
        seg.closed = True
        if self.artifact_store is not None and data:
            try:
                art = self.artifact_store.create_from_bytes(
                    data=data,
                    artifact_type="market_feed_segment",
                    producer="market_sim.feed",
                    filename=path.name,
                    metadata={
                        "feed_id": seg.feed_id,
                        "provider_id": seg.provider_id,
                        "symbol": seg.symbol,
                        "mode": seg.mode.value,
                        "event_count": seg.event_count,
                        "content_hash": seg.content_hash,
                    },
                )
                seg.artifact_id = getattr(art, "artifact_id", None) or (
                    art.get("artifact_id") if isinstance(art, dict) else None
                )
            except Exception:  # noqa: BLE001
                pass
        self.closed_segments.append(seg)
