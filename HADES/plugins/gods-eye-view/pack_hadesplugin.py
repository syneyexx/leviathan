#!/usr/bin/env python3
"""Build gods-eye-view-*.HadesPlugin from upstream source + HADES manifest.

Usage (from repo root or this folder):
  python plugins/gods-eye-view/pack_hadesplugin.py
  python plugins/gods-eye-view/pack_hadesplugin.py --out /path/to/dir

Requires: git, Python 3.10+.
The resulting .HadesPlugin can be imported in HADES Plugin Manager
(ZIP / .HadesPlugin). On import, HADES runs npm ci and registers the
start/health/status/logs/stop tools from hades-plugin.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

UPSTREAM = "https://github.com/bilawalsidhu/gods-eye-view.git"
DEFAULT_REF = "main"
EXCLUDE_DIR_NAMES = {".git", "node_modules", ".venv", "venv", "__pycache__", "docs/media"}
# Also drop README demo media tree if present as nested path parts
EXCLUDE_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def should_skip(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    parts = relative.parts
    if any(part in EXCLUDE_PARTS for part in parts):
        return True
    # Drop docs/media demo assets (not required at runtime).
    if len(parts) >= 2 and parts[0] == "docs" and parts[1] == "media":
        return True
    return False


def clone_upstream(destination: Path, ref: str) -> None:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git is required on PATH to pack this plugin.")
    process = subprocess.run(
        [git, "clone", "--depth", "1", "--branch", ref, UPSTREAM, str(destination)],
        capture_output=True,
        text=True,
        timeout=300,
        shell=False,
    )
    if process.returncode != 0:
        # Fallback when branch name is not a branch (tag / default).
        process = subprocess.run(
            [git, "clone", "--depth", "1", UPSTREAM, str(destination)],
            capture_output=True,
            text=True,
            timeout=300,
            shell=False,
        )
        if process.returncode != 0:
            raise RuntimeError((process.stderr or process.stdout).strip() or "git clone failed")
        if ref and ref != "main":
            fetch = subprocess.run(
                [git, "-C", str(destination), "fetch", "--depth", "1", "origin", ref],
                capture_output=True,
                text=True,
                timeout=120,
                shell=False,
            )
            if fetch.returncode == 0:
                checkout = subprocess.run(
                    [git, "-C", str(destination), "checkout", "--detach", "FETCH_HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    shell=False,
                )
                if checkout.returncode != 0:
                    raise RuntimeError((checkout.stderr or checkout.stdout).strip() or f"checkout {ref} failed")
    shutil.rmtree(destination / ".git", ignore_errors=True)


def pack(manifest_path: Path, out_dir: Path, ref: str) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugin_id = str(manifest["id"])
    version = str(manifest["version"])
    out_dir.mkdir(parents=True, exist_ok=True)
    package_path = out_dir / f"{plugin_id}-{version}.HadesPlugin"

    with tempfile.TemporaryDirectory(prefix="gev-hades-pack-") as tmp:
        root = Path(tmp) / "source"
        clone_upstream(root, ref)
        # Overlay HADES manifest into the runtime source tree.
        (root / "hades-plugin.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        integrity: dict[str, str] = {}
        files: list[tuple[Path, str]] = []
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if should_skip(path, root):
                continue
            relative = path.relative_to(root).as_posix()
            integrity[relative] = sha256_file(path)
            files.append((path, f"source/{relative}"))

        packaged_manifest = {**manifest, "integrity": integrity, "source_ref": f"{UPSTREAM}@{ref}"}
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("hades-plugin.json", json.dumps(packaged_manifest, ensure_ascii=False, indent=2))
            for path, archive_name in files:
                archive.write(path, archive_name)

    return package_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack God's Eye View as a .HadesPlugin")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "dist",
        help="Output directory for the .HadesPlugin file",
    )
    parser.add_argument("--ref", default=DEFAULT_REF, help="Upstream git ref (default: main)")
    args = parser.parse_args()
    manifest_path = Path(__file__).resolve().parent / "hades-plugin.json"
    if not manifest_path.is_file():
        print(f"Missing manifest: {manifest_path}", file=sys.stderr)
        return 1
    package = pack(manifest_path, args.out.resolve(), args.ref)
    size_mb = package.stat().st_size / (1024 * 1024)
    print(f"Wrote {package} ({size_mb:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
