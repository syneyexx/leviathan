"""Convention-based package layout adapter.

Recognizes portable folder conventions without requiring a HADES manifest:
skills/, knowledge/, docs/, agents/, workflows/, commands/, tools/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import AdapterHit

_TEXT = {".md", ".mdc", ".txt", ".rst", ".json"}
_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}


def _iter_files(root: Path, folder: str, *, limit: int = 80) -> list[Path]:
    base = root / folder
    if not base.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT:
            continue
        if any(part in _SKIP for part in path.parts):
            continue
        found.append(path)
        if len(found) >= limit:
            break
    return found


class ConventionAdapter:
    adapter_id = "convention"

    def detect(self, root: Path, manifest: dict[str, Any] | None = None) -> AdapterHit:
        hits = 0
        notes: list[str] = []
        for folder in ("skills", "knowledge", "docs", "agents", "workflows", "commands", "tools"):
            if (root / folder).is_dir():
                hits += 1
                notes.append(folder)
        if hits == 0:
            return AdapterHit(self.adapter_id, 0.0)
        return AdapterHit(self.adapter_id, min(0.85, 0.25 + 0.12 * hits), notes)

    def parse(
        self,
        root: Path,
        *,
        plugin: dict[str, Any] | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        capabilities: list[dict[str, Any]] = []
        mapping = (
            ("skills", "skill"),
            ("knowledge", "knowledge"),
            ("docs", "knowledge"),
            # Markdown under agents/ is guidance until a richer adapter proves an executable worker.
            ("agents", "skill"),
            ("workflows", "workflow"),
            ("commands", "workflow"),
            ("tools", "knowledge"),
        )
        for folder, kind in mapping:
            for path in _iter_files(root, folder):
                rel = path.relative_to(root).as_posix()
                stem = path.stem
                try:
                    preview = path.read_text(encoding="utf-8", errors="replace")[:400]
                except Exception:
                    preview = ""
                capabilities.append(
                    {
                        "id": f"{folder}/{stem}",
                        "name": stem.replace("-", " ").replace("_", " "),
                        "description": preview,
                        "kind": kind,
                        "content_ref": rel,
                        "from": f"convention.{folder}",
                    }
                )
        return {"capabilities": capabilities, "unsupported": []}
