#!/usr/bin/env python3
"""Build geolibre-*.HadesPlugin from pinned upstream source + HADES manifest.

Usage (from the HADES repository root or this folder):
  python plugins/geolibre/pack_hadesplugin.py
  python plugins/geolibre/pack_hadesplugin.py --out plugins/geolibre/dist
  python plugins/geolibre/pack_hadesplugin.py --ref <git-ref>

Requires: git, Python 3.10+.
The resulting .HadesPlugin can be imported through HADES Plugin Manager.
On import HADES runs npm ci, then exposes geospatial data tools plus
doctor/start/health/status/logs/stop for the local Vite UI.
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

UPSTREAM = "https://github.com/opengeos/GeoLibre.git"
DEFAULT_REF = "cf02ccd881a3bc7b72f1af68a668dddffa0ffd7d"
EXCLUDE_PARTS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "coverage",
    "playwright-report",
    "target",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def should_skip(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return any(part in EXCLUDE_PARTS for part in relative.parts)


def run_git(arguments: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    if process.returncode != 0:
        raise RuntimeError((process.stderr or process.stdout).strip() or "git command failed")
    return process


def clone_upstream(destination: Path, ref: str) -> str:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git is required on PATH to pack this plugin.")

    destination.mkdir(parents=True, exist_ok=False)
    run_git([git, "init", str(destination)], timeout=60)
    run_git([git, "-C", str(destination), "remote", "add", "origin", UPSTREAM], timeout=30)
    run_git([git, "-C", str(destination), "fetch", "--depth", "1", "origin", ref], timeout=300)
    run_git([git, "-C", str(destination), "checkout", "--detach", "FETCH_HEAD"], timeout=60)
    resolved = run_git([git, "-C", str(destination), "rev-parse", "HEAD"], timeout=30).stdout.strip()
    shutil.rmtree(destination / ".git", ignore_errors=True)
    return resolved


def pack(manifest_path: Path, out_dir: Path, ref: str) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugin_id = str(manifest["id"])
    version = str(manifest["version"])
    out_dir.mkdir(parents=True, exist_ok=True)
    package_path = out_dir / f"{plugin_id}-{version}.HadesPlugin"

    with tempfile.TemporaryDirectory(prefix="geolibre-hades-pack-") as tmp:
        root = Path(tmp) / "source"
        resolved_ref = clone_upstream(root, ref)

        upstream_package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        required_node = str(upstream_package.get("engines", {}).get("node", ""))
        if not required_node:
            raise RuntimeError("GeoLibre package.json does not declare a Node.js engine requirement.")
        if not (root / "package-lock.json").is_file():
            raise RuntimeError("GeoLibre package-lock.json is missing; reproducible npm ci install is unavailable.")

        runtime_manifest = {
            **manifest,
            "upstream_ref": resolved_ref,
            "upstream_version": str(upstream_package.get("version", manifest.get("upstream_version", ""))),
            "upstream_node_engine": required_node,
        }
        (root / "hades-plugin.json").write_text(
            json.dumps(runtime_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # Overlay HADES-native geospatial adapter + fixtures (not part of upstream).
        plugin_dir = Path(__file__).resolve().parent
        adapter = plugin_dir / "geolibre_hades.py"
        if not adapter.is_file():
            raise RuntimeError(f"Missing HADES adapter: {adapter}")
        shutil.copy2(adapter, root / "geolibre_hades.py")
        fixtures_src = plugin_dir / "fixtures"
        if fixtures_src.is_dir():
            fixtures_dst = root / "fixtures"
            fixtures_dst.mkdir(parents=True, exist_ok=True)
            for fixture in fixtures_src.glob("*"):
                if fixture.is_file():
                    shutil.copy2(fixture, fixtures_dst / fixture.name)
        readme = plugin_dir / "README.md"
        if readme.is_file():
            shutil.copy2(readme, root / "HADES_PLUGIN_README.md")

        integrity: dict[str, str] = {}
        files: list[tuple[Path, str]] = []
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink() or should_skip(path, root):
                continue
            relative = path.relative_to(root).as_posix()
            integrity[relative] = sha256_file(path)
            files.append((path, f"source/{relative}"))

        packaged_manifest = {
            **runtime_manifest,
            "integrity": integrity,
            "source_ref": f"{UPSTREAM}@{resolved_ref}",
        }
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "hades-plugin.json",
                json.dumps(packaged_manifest, ensure_ascii=False, indent=2) + "\n",
            )
            for path, archive_name in files:
                archive.write(path, archive_name)

    return package_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack GeoLibre as a .HadesPlugin")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "dist",
        help="Output directory for the .HadesPlugin file",
    )
    parser.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help=f"Upstream git ref (default pinned commit: {DEFAULT_REF})",
    )
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
