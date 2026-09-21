#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_FILES = ["ultimate_news_feeder.py", "pipeline_v12.py", "news_core.py", "article_crawler.py", "site_discovery.py", "story_intelligence.py", "source_catalog.py", "README.md"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    manifest_path = ROOT / "hades-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{manifest['id']}-{manifest['version']}.HadesPlugin"
    integrity = {name: sha256(ROOT / name) for name in SOURCE_FILES}
    packaged = {**manifest, "integrity": integrity}
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("hades-plugin.json", json.dumps(packaged, ensure_ascii=False, indent=2) + "\n")
        for name in SOURCE_FILES:
            archive.write(ROOT / name, f"source/{name}")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
