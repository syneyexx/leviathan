#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_FILES = ["crawler.py", "deep_engine.py", "deep_utils.py", "README.md"]

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    manifest_path = ROOT / "hades-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{manifest['id']}-{manifest['version']}.HadesPlugin"

    integrity = {}
    for name in SOURCE_FILES:
        integrity[name] = sha256(ROOT / name)
    packaged = {**manifest, "integrity": integrity}

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("hades-plugin.json", json.dumps(packaged, ensure_ascii=False, indent=2) + "\n")
        for name in SOURCE_FILES:
            z.write(ROOT / name, f"source/{name}")
    print(target)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
