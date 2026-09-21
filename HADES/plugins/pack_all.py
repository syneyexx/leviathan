#!/usr/bin/env python3
"""Pack one or all HADES plugins under plugins/."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def plugin_dirs() -> list[Path]:
    rows = []
    for path in sorted(ROOT.iterdir()):
        if path.is_dir() and (path / "hades-plugin.json").is_file() and (path / "pack_hadesplugin.py").is_file():
            rows.append(path)
    return rows


def pack_one(plugin: Path, out: Path | None = None) -> int:
    command = [sys.executable, str(plugin / "pack_hadesplugin.py")]
    if out is not None:
        command.extend(["--out", str(out)])
    print(f"==> packing {plugin.name}")
    process = subprocess.run(command, cwd=str(ROOT.parent), shell=False)
    return int(process.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack HADES plugins")
    parser.add_argument("--plugin", default="", help="Pack a single plugin id")
    parser.add_argument("--mode", choices=["all", "local"], default="all")
    parser.add_argument("--out-root", type=Path, default=None)
    args = parser.parse_args()

    local_only = {
        "markitdown",
        "graphrag",
        "unsloth",
        "composio",
        "voicestudio",
        "chrome-devtools-mcp",
        "desktop-commander-mcp",
        "gods-eye-view",
        "scrapling",
        "puppeteer",
        "headroom",
        "ghosttrack",
        "deep-web-downloader",
        "web-pdf-harvester",
        "fincept-data",
        "ultimate-news-feeder",
        "sinwindie-osint",
        "patchright",
        "dspy",
        "vibe-trading",
        # Batch 4 local-ready HADES-native wrappers
        "codebase-memory",
        "open-code-review",
        "worktrunk",
        "openai-skills",
        "no-ai-slop",
        "diagram-design",
        "trading-agents",
        "ruview",
        "data-formulator",
        "eli5",
        "graft",
        "openmontage",
        "autoclip",
        "ui-ux-pro-max",
        "superpowers",
        "frontend-design-toolkit",
        "karpathy-skills",
        "anthropic-agent-skills",
        "massgen",
        "context-engineering-skills",
        "omniroute",
        "knowledge-work-plugins",
        "claude-plugins-official",
        "firm-protocol",
    }

    selected = plugin_dirs()
    if args.plugin:
        selected = [ROOT / args.plugin]
        if not (selected[0] / "pack_hadesplugin.py").is_file():
            print(f"unknown plugin: {args.plugin}", file=sys.stderr)
            return 1
    elif args.mode == "local":
        selected = [path for path in selected if path.name in local_only]

    failures = 0
    for plugin in selected:
        out = None
        if args.out_root is not None:
            out = args.out_root / plugin.name
        code = pack_one(plugin, out)
        if code != 0:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
