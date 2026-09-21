"""Shared helpers for packing HADES .HadesPlugin archives."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

EXCLUDE_PARTS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".tox",
    "dist",
    "build",
    ".turbo",
    ".next",
    "target",
}

# Demo / binary media not required for HADES tool bridges; keeps packages GitHub-importable.
EXCLUDE_SUFFIXES = {
    ".mp4",
    ".mov",
    ".webm",
    ".avi",
    ".mkv",
    ".mp3",
    ".wav",
    ".flac",
    ".psd",
    ".ai",
    ".sketch",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def should_skip(
    path: Path,
    root: Path,
    extra_parts: Iterable[str] | None = None,
    extra_suffixes: Iterable[str] | None = None,
) -> bool:
    relative = path.relative_to(root)
    blocked = set(EXCLUDE_PARTS)
    if extra_parts:
        blocked.update(extra_parts)
    if any(part in blocked for part in relative.parts):
        return True
    suffixes = set(EXCLUDE_SUFFIXES)
    if extra_suffixes:
        suffixes.update(s.lower() if s.startswith('.') else f'.{s.lower()}' for s in extra_suffixes)
    return path.suffix.lower() in suffixes


def clone_upstream(destination: Path, upstream: str, ref: str) -> None:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git is required on PATH to pack this plugin.")
    process = subprocess.run(
        [git, "clone", "--depth", "1", "--branch", ref, upstream, str(destination)],
        capture_output=True,
        text=True,
        timeout=600,
        shell=False,
    )
    if process.returncode != 0:
        process = subprocess.run(
            [git, "clone", "--depth", "1", upstream, str(destination)],
            capture_output=True,
            text=True,
            timeout=600,
            shell=False,
        )
        if process.returncode != 0:
            raise RuntimeError((process.stderr or process.stdout).strip() or "git clone failed")
        if ref:
            fetch = subprocess.run(
                [git, "-C", str(destination), "fetch", "--depth", "1", "origin", ref],
                capture_output=True,
                text=True,
                timeout=180,
                shell=False,
            )
            if fetch.returncode == 0:
                checkout = subprocess.run(
                    [git, "-C", str(destination), "checkout", "--detach", "FETCH_HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    shell=False,
                )
                if checkout.returncode != 0:
                    raise RuntimeError((checkout.stderr or checkout.stdout).strip() or f"checkout {ref} failed")
    shutil.rmtree(destination / ".git", ignore_errors=True)


def copy_tree(source: Path, destination: Path, extra_parts: Iterable[str] | None = None) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if should_skip(path, source, extra_parts):
            continue
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def apply_overlay(overlay: Path, root: Path) -> None:
    if not overlay.is_dir():
        return
    for path in overlay.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(overlay)
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def write_package(
    *,
    manifest: dict,
    root: Path,
    package_path: Path,
    upstream: str | None = None,
    ref: str | None = None,
    extra_parts: Iterable[str] | None = None,
) -> Path:
    package_path.parent.mkdir(parents=True, exist_ok=True)
    integrity: dict[str, str] = {}
    files: list[tuple[Path, str]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if should_skip(path, root, extra_parts):
            continue
        relative = path.relative_to(root).as_posix()
        integrity[relative] = sha256_file(path)
        files.append((path, f"source/{relative}"))

    packaged_manifest = dict(manifest)
    packaged_manifest["integrity"] = integrity
    if upstream:
        packaged_manifest["source_ref"] = f"{upstream}@{ref or 'HEAD'}"

    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("hades-plugin.json", json.dumps(packaged_manifest, ensure_ascii=False, indent=2))
        for path, archive_name in files:
            archive.write(path, archive_name)
    return package_path


def pack_local(
    *,
    plugin_dir: Path,
    out_dir: Path,
    extra_parts: Iterable[str] | None = None,
) -> Path:
    manifest_path = plugin_dir / "hades-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugin_id = str(manifest["id"])
    version = str(manifest["version"])
    package_path = out_dir / f"{plugin_id}-{version}.HadesPlugin"

    with tempfile.TemporaryDirectory(prefix=f"hades-pack-{plugin_id}-") as tmp:
        root = Path(tmp) / "source"
        copy_tree(plugin_dir, root, extra_parts={"dist", "overlay", *list(extra_parts or [])})
        # Keep overlay helpers if present as first-class runtime files.
        apply_overlay(plugin_dir / "overlay", root)
        (root / "hades-plugin.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return write_package(
            manifest=manifest,
            root=root,
            package_path=package_path,
            upstream=str(manifest.get("source") or ""),
            ref="local",
            extra_parts=extra_parts,
        )


def pack_git(
    *,
    plugin_dir: Path,
    out_dir: Path,
    upstream: str,
    ref: str = "main",
    extra_parts: Iterable[str] | None = None,
) -> Path:
    manifest_path = plugin_dir / "hades-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugin_id = str(manifest["id"])
    version = str(manifest["version"])
    package_path = out_dir / f"{plugin_id}-{version}.HadesPlugin"

    with tempfile.TemporaryDirectory(prefix=f"hades-pack-{plugin_id}-") as tmp:
        root = Path(tmp) / "source"
        clone_upstream(root, upstream, ref)
        apply_overlay(plugin_dir / "overlay", root)
        # Copy HADES helper modules from the plugin folder root into the upstream tree.
        for name in (
            "catalog_bridge.py",
            "skill_bridge.py",
            "mcp_bridge.py",
            "cli_bridge.py",
            "hades_bridge.py",
            "hades_bridge.mjs",
            "requirements.txt",
        ):
            source = plugin_dir / name
            if source.is_file():
                shutil.copy2(source, root / name)
        (root / "hades-plugin.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return write_package(
            manifest=manifest,
            root=root,
            package_path=package_path,
            upstream=upstream,
            ref=ref,
            extra_parts=extra_parts,
        )
