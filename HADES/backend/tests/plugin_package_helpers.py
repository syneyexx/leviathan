"""Helpers for plugin contract tests when Git LFS packages are unavailable."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


def is_git_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            head = handle.read(64)
    except OSError:
        return False
    return head.startswith(b"version https://git-lfs.github.com/spec/v1")


def write_overlay_hadesplugin(plugin_dir: Path, dest: Path, *, files: list[str]) -> Path:
    """Build a minimal .HadesPlugin from overlay sources (no upstream clone / LFS)."""
    manifest_path = plugin_dir / "hades-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("hades-plugin.json", json.dumps(manifest, indent=2))
        for name in files:
            src = plugin_dir / name
            if src.is_file():
                archive.write(src, arcname=f"source/{name}")
            elif name == "GhostTR.py":
                # Upstream binary not present without pack/LFS — stub for shape/doctor checks.
                archive.writestr("source/GhostTR.py", "# stub GhostTR for contract tests\nprint('GhostTR stub')\n")
    return dest
