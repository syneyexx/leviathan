"""Temporary AI preview asset storage.

Ephemeral files for generation previews — never pollutes permanent asset library
until Accept copies through the normal upload path.
"""

from __future__ import annotations

import base64
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
MAX_BYTES = 8_000_000
DEFAULT_TTL_SECONDS = 3600


class TempAssetStore:
    def __init__(self, root: Path, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.root = root
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._meta: dict[str, dict[str, Any]] = {}
        self.root.mkdir(parents=True, exist_ok=True)
        self.cleanup_expired()

    def put(
        self,
        raw: bytes,
        *,
        ext: str = ".png",
        mime: str = "image/png",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ext = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
        if ext not in ALLOWED_EXT:
            raise ValueError("unsupported temp asset type")
        if len(raw) > MAX_BYTES:
            raise ValueError("temp asset too large")
        asset_id = uuid.uuid4().hex
        name = f"{asset_id}{ext}"
        path = self.root / name
        with self._lock:
            path.write_bytes(raw)
            record = {
                "id": asset_id,
                "filename": name,
                "ext": ext,
                "mime": mime,
                "bytes": len(raw),
                "createdAt": time.time(),
                "meta": dict(meta or {}),
            }
            self._meta[asset_id] = record
        return {
            **record,
            "url": f"/api/editor-ai/preview/{asset_id}",
            "ref": f"temp:{asset_id}",
        }

    def put_data_url(self, data_url: str, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        mime = "image/png"
        b64 = data_url
        if "," in data_url and data_url.strip().startswith("data:"):
            header, b64 = data_url.split(",", 1)
            if ";" in header:
                mime = header[5:].split(";", 1)[0] or mime
        raw = base64.b64decode(b64, validate=False)
        ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/svg+xml": ".svg",
        }.get(mime, ".png")
        return self.put(raw, ext=ext, mime=mime, meta=meta)

    def get(self, asset_id: str) -> tuple[bytes, dict[str, Any]] | None:
        if not SAFE_ID.match(asset_id):
            return None
        with self._lock:
            record = self._meta.get(asset_id)
            if not record:
                # Try discover from disk
                for path in self.root.glob(f"{asset_id}.*"):
                    if path.suffix.lower() in ALLOWED_EXT:
                        record = {
                            "id": asset_id,
                            "filename": path.name,
                            "ext": path.suffix.lower(),
                            "mime": _mime_for(path.suffix.lower()),
                            "bytes": path.stat().st_size,
                            "createdAt": path.stat().st_mtime,
                            "meta": {},
                        }
                        self._meta[asset_id] = record
                        break
            if not record:
                return None
            path = self.root / record["filename"]
            if not path.is_file():
                self._meta.pop(asset_id, None)
                return None
            if time.time() - float(record.get("createdAt") or 0) > self.ttl_seconds:
                self.delete(asset_id)
                return None
            return path.read_bytes(), record

    def delete(self, asset_id: str) -> bool:
        if not SAFE_ID.match(asset_id):
            return False
        with self._lock:
            record = self._meta.pop(asset_id, None)
            removed = False
            if record:
                path = self.root / record["filename"]
                if path.is_file():
                    path.unlink()
                    removed = True
            for path in self.root.glob(f"{asset_id}.*"):
                if path.is_file():
                    path.unlink()
                    removed = True
            return removed

    def cleanup_expired(self) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            for path in list(self.root.glob("*")):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in ALLOWED_EXT:
                    continue
                age = now - path.stat().st_mtime
                if age > self.ttl_seconds:
                    asset_id = path.stem
                    path.unlink(missing_ok=True)
                    self._meta.pop(asset_id, None)
                    removed += 1
        return removed

    def cleanup_request(self, request_id: str) -> int:
        removed = 0
        with self._lock:
            victims = [
                aid
                for aid, rec in self._meta.items()
                if str((rec.get("meta") or {}).get("requestId") or "") == request_id
            ]
            for aid in victims:
                if self.delete(aid):
                    removed += 1
        return removed


def _mime_for(ext: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
    }.get(ext, "application/octet-stream")
