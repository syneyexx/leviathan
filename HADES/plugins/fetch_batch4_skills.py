#!/usr/bin/env python3
"""Fetch upstream SKILL.md / CLAUDE.md files into batch-4 HADES plugins.

Network is optional: failures are printed and the HADES adapter skills remain.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
KEEP_NAMES = {"skill.md", "skills.md", "claude.md", "agents.md", "readme.md"}
TEXT_SUFFIXES = {".md", ".mdc", ".txt"}

SOURCES: list[dict] = [
    {"plugin": "openai-skills", "url": "https://github.com/openai/skills.git", "ref": "main", "max_files": 80},
    {"plugin": "no-ai-slop", "url": "https://github.com/petergyang/no-ai-slop.git", "ref": "main", "max_files": 40},
    {"plugin": "diagram-design", "url": "https://github.com/cathrynlavery/diagram-design.git", "ref": "main", "max_files": 60},
    {"plugin": "eli5", "url": "https://github.com/DreambigOu/ELI5.git", "ref": "main", "max_files": 20},
    {"plugin": "ui-ux-pro-max", "url": "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git", "ref": "main", "max_files": 40},
    {"plugin": "superpowers", "url": "https://github.com/obra/superpowers.git", "ref": "main", "max_files": 80},
    {
        "plugin": "frontend-design-toolkit",
        "url": "https://github.com/wilwaldon/Claude-Code-Frontend-Design-Toolkit.git",
        "ref": "main",
        "max_files": 40,
    },
    {
        "plugin": "karpathy-skills",
        "url": "https://github.com/multica-ai/andrej-karpathy-skills.git",
        "ref": "main",
        "max_files": 20,
    },
    {
        "plugin": "anthropic-agent-skills",
        "url": "https://github.com/anthropics/skills.git",
        "ref": "main",
        "sparse": [
            "skills/frontend-design",
            "skills/algorithmic-art",
            "skills/canvas-design",
            "skills/theme-factory",
            "skills/web-artifacts-builder",
        ],
        "max_files": 80,
    },
    {
        "plugin": "context-engineering-skills",
        "url": "https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering.git",
        "ref": "main",
        "max_files": 80,
    },
    {
        "plugin": "knowledge-work-plugins",
        "url": "https://github.com/anthropics/knowledge-work-plugins.git",
        "ref": "main",
        "max_files": 80,
    },
    {
        "plugin": "claude-plugins-official",
        "url": "https://github.com/anthropics/claude-plugins-official.git",
        "ref": "main",
        "max_files": 80,
    },
    {"plugin": "openmontage", "url": "https://github.com/calesthio/OpenMontage.git", "ref": "main", "max_files": 80, "sparse": ["skills"]},
    {"plugin": "firm-protocol", "url": "https://github.com/firm-org/firm-protocol.git", "ref": "master", "max_files": 40},
]


def _run(command: list[str], cwd: Path | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout, shell=False)


def _clone(url: str, ref: str, dest: Path, sparse: list[str] | None) -> bool:
    git = shutil.which("git")
    if not git:
        print("git missing; skip", url)
        return False
    cmd = [git, "clone", "--depth", "1", "--filter=blob:none"]
    if sparse:
        cmd.append("--sparse")
    cmd.extend(["--branch", ref, url, str(dest)])
    process = _run(cmd, timeout=240)
    if process.returncode != 0:
        process = _run([git, "clone", "--depth", "1", url, str(dest)], timeout=240)
        if process.returncode != 0:
            print("clone failed", url, (process.stderr or process.stdout)[-400:])
            return False
    if sparse and (dest / ".git").exists():
        _run([git, "-C", str(dest), "sparse-checkout", "set", *sparse], timeout=60)
    return dest.is_dir()


def _iter_docs(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        name = path.name.lower()
        if name in KEEP_NAMES or path.suffix.lower() in TEXT_SUFFIXES:
            if "skill" in path.as_posix().lower() or name in KEEP_NAMES or path.parent.name.lower() in {"skills", "skill", "plugins"}:
                yield path


def _copy_docs(source: Path, plugin_dir: Path, max_files: int) -> int:
    dest_root = plugin_dir / "skills" / "upstream"
    copied = 0
    for path in _iter_docs(source):
        if copied >= max_files:
            break
        try:
            if path.stat().st_size > 200_000:
                continue
        except OSError:
            continue
        rel = path.relative_to(source)
        target = dest_root / rel
        if target.suffix.lower() not in TEXT_SUFFIXES and path.name.lower() not in KEEP_NAMES:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    for skill in dest_root.rglob("SKILL.md"):
        skill_id = skill.parent.name
        if skill_id.lower() in {".", "skills", "skill", "upstream"}:
            continue
        promoted = plugin_dir / "skills" / skill_id / "SKILL.md"
        promoted.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill, promoted)
    return copied


def main() -> int:
    failures = 0
    for spec in SOURCES:
        plugin_dir = ROOT / spec["plugin"]
        if not (plugin_dir / "hades-plugin.json").is_file():
            print("missing plugin", spec["plugin"])
            failures += 1
            continue
        with tempfile.TemporaryDirectory(prefix=f"hades-{spec['plugin']}-") as tmp:
            dest = Path(tmp) / "src"
            if not _clone(spec["url"], spec.get("ref") or "main", dest, spec.get("sparse")):
                failures += 1
                continue
            copied = _copy_docs(dest, plugin_dir, int(spec.get("max_files") or 40))
            print(f"{spec['plugin']}: copied {copied} docs")
            if copied == 0:
                failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
