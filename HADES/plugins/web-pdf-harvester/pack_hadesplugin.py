#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_FILES = [
    "harvester_cli.py",
    "requirements.txt",
    "requirements-browser.txt",
    "README.md",
]
SOURCE_DIRS = ["pdf_harvester"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files() -> list[Path]:
    files: list[Path] = []
    for name in SOURCE_FILES:
        files.append(ROOT / name)
    for dirname in SOURCE_DIRS:
        base = ROOT / dirname
        for path in sorted(base.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    manifest_path = ROOT / "hades-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{manifest['id']}-{manifest['version']}.HadesPlugin"

    integrity: dict[str, str] = {}
    rel_files: list[tuple[str, Path]] = []
    for path in iter_files():
        rel = path.relative_to(ROOT).as_posix()
        integrity[rel] = sha256(path)
        rel_files.append((rel, path))

    packaged = {**manifest, "integrity": integrity}
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("hades-plugin.json", json.dumps(packaged, ensure_ascii=False, indent=2) + "\n")
        for rel, path in rel_files:
            zf.write(path, f"source/{rel}")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
