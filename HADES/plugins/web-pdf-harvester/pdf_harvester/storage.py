"""Filesystem layout, filename sanitization and atomic writes."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, *, fallback: str = "download", max_len: int = 160) -> str:
    name = (name or "").replace("\x00", "").strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r'[<>:"|?*\x00-\x1f]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = fallback
    stem, suffix = os.path.splitext(name)
    if stem.upper() in WINDOWS_RESERVED:
        stem = f"_{stem}"
    name = f"{stem}{suffix}"[:max_len].rstrip(" .")
    return name or fallback


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


class StoragePaths:
    """Canonical on-disk layout under data/pdf_harvester/."""

    def __init__(self, root: str | Path = "data/pdf_harvester") -> None:
        self.root = Path(root).expanduser()
        if not self.root.is_absolute():
            self.root = (Path.cwd() / self.root).resolve()
        else:
            self.root = self.root.resolve()
        self.indexes = self.root / "indexes"
        self.downloads = self.root / "downloads"
        self.state = self.root / "state"
        self.logs = self.root / "logs"

    def ensure(self) -> StoragePaths:
        for path in (self.indexes, self.downloads, self.state, self.logs):
            path.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def resources_jsonl(self) -> Path:
        return self.indexes / "discovered_resources.jsonl"

    @property
    def resources_sqlite(self) -> Path:
        return self.indexes / "discovered_resources.sqlite3"

    @property
    def pdf_links_txt(self) -> Path:
        return self.indexes / "pdf_links.txt"

    @property
    def crawl_state(self) -> Path:
        return self.state / "crawl_state.json"

    @property
    def cancel_flag(self) -> Path:
        return self.state / "cancel.flag"

    @property
    def session_stats(self) -> Path:
        return self.state / "last_session.json"

    def host_download_dir(self, hostname: str) -> Path:
        safe = sanitize_filename(hostname or "unknown-host", fallback="unknown-host")
        path = self.downloads / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    def download_target(self, hostname: str, filename: str) -> Path:
        return self.host_download_dir(hostname) / sanitize_filename(filename, fallback="unknown.pdf")
