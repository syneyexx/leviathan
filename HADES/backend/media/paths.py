"""Containment-safe Media filesystem layout under HADES data root."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from path_boundary import join_within_root, resolve_root, validate_run_id

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def validate_media_id(value: str, *, kind: str = "id") -> str:
    text = str(value or "").strip()
    if not text or not _SAFE_ID.match(text):
        raise ValueError(f"Invalid media {kind}: {value!r}")
    # Reuse run_id escape checks (separators / parent segments).
    validate_run_id(text)
    return text


class MediaPaths:
    def __init__(self, data_root: str | Path) -> None:
        self.root = resolve_root(Path(data_root) / "media")
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("channels", "projects", "cache", "exports", "tmp", "library"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def channel_dir(self, channel_id: str) -> Path:
        safe = validate_media_id(channel_id, kind="channel_id")
        path = join_within_root(self.root / "channels", safe)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def project_dir(self, project_id: str) -> Path:
        safe = validate_media_id(project_id, kind="project_id")
        path = join_within_root(self.root / "projects", safe)
        path.mkdir(parents=True, exist_ok=True)
        for sub in ("sources", "transcripts", "assets", "renders", "variants", "audio", "storyboards"):
            (path / sub).mkdir(parents=True, exist_ok=True)
        return path

    def cache_path(self, *parts: str) -> Path:
        rel = "/".join(validate_media_id(p, kind="cache_part") for p in parts)
        path = join_within_root(self.root / "cache", rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def export_path(self, name: str) -> Path:
        safe = validate_media_id(name, kind="export")
        return join_within_root(self.root / "exports", safe)

    def library_path(self, *parts: str) -> Path:
        rel = "/".join(validate_media_id(p, kind="library_part") for p in parts)
        path = join_within_root(self.root / "library", rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def tmp_dir(self, project_id: str) -> Path:
        safe = validate_media_id(project_id, kind="project_id")
        path = join_within_root(self.root / "tmp", safe)
        path.mkdir(parents=True, exist_ok=True)
        return path


def content_hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash_file(path: Path, *, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def prompt_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()
