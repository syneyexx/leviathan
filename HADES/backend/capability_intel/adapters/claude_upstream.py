"""Claude / upstream artifact adapter.

Maps portable Claude-origin files onto HADES capability kinds.
Unsupported Claude-specific runtime (hooks, slash-command execution, fake
agents) is reported honestly and never given system authority.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import AdapterHit

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)
_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__"}


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Minimal YAML-ish frontmatter parser. No PyYAML dependency."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip("'\"")
        if key:
            meta[key] = value
    return meta, text[match.end() :]


def _read(path: Path, *, limit: int = 48_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _files(root: Path, relative: str) -> list[Path]:
    base = root / relative
    if base.is_file():
        return [base]
    if not base.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP for part in path.parts):
            continue
        if path.suffix.lower() not in {".md", ".mdc", ".txt", ".json"}:
            continue
        out.append(path)
        if len(out) >= 80:
            break
    return out


class ClaudeUpstreamAdapter:
    adapter_id = "claude_upstream"

    def detect(self, root: Path, manifest: dict[str, Any] | None = None) -> AdapterHit:
        markers = []
        for rel in ("SKILL.md", "CLAUDE.md", "agents", "commands", "rules", ".claude", "hooks"):
            if (root / rel).exists():
                markers.append(rel)
        if (root / "skills").is_dir() and any((root / "skills").rglob("SKILL.md")):
            markers.append("skills/**/SKILL.md")
        if not markers:
            return AdapterHit(self.adapter_id, 0.0)
        return AdapterHit(self.adapter_id, min(0.9, 0.35 + 0.12 * len(markers)), markers)

    def parse(
        self,
        root: Path,
        *,
        plugin: dict[str, Any] | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        capabilities: list[dict[str, Any]] = []
        unsupported: list[dict[str, str]] = []

        for skill_path in [root / "SKILL.md", *_files(root, "skills")]:
            if skill_path.name.upper() not in {"SKILL.MD", "SKILL.MDC"} and "skills" not in skill_path.parts:
                if skill_path.name != "SKILL.md":
                    continue
            text = _read(skill_path)
            if not text:
                continue
            meta, body = parse_frontmatter(text)
            rel = skill_path.relative_to(root).as_posix()
            capabilities.append(
                {
                    "id": meta.get("id") or meta.get("name") or skill_path.parent.name or skill_path.stem,
                    "name": meta.get("name") or skill_path.parent.name or "skill",
                    "description": meta.get("description") or body.strip().splitlines()[0][:240] if body.strip() else "",
                    "kind": "skill",
                    "domains": [item.strip() for item in meta.get("domains", "").split(",") if item.strip()],
                    "content_ref": rel,
                    "from": "claude.SKILL.md",
                    "untrusted": True,
                }
            )

        claude_md = root / "CLAUDE.md"
        if claude_md.is_file():
            text = _read(claude_md)
            meta, body = parse_frontmatter(text)
            capabilities.append(
                {
                    "id": "project-guidance",
                    "name": meta.get("name") or "Project guidance",
                    "description": (body.strip().splitlines() or ["CLAUDE.md project guidance"])[0][:240],
                    "kind": "knowledge",
                    "content_ref": "CLAUDE.md",
                    "from": "claude.CLAUDE.md",
                    "untrusted": True,
                    "scope": "project",
                }
            )

        for path in _files(root, "agents"):
            text = _read(path)
            meta, body = parse_frontmatter(text)
            claimed = (meta.get("type") or meta.get("kind") or "").lower()
            executable_markers = (
                meta.get("tools"),
                meta.get("model"),
                meta.get("runtime"),
                "delegate" in body.lower(),
                "execute" in body.lower() and "tool" in body.lower(),
            )
            is_executable = any(bool(item) for item in executable_markers) and claimed in {"agent", "subagent", ""}
            # Prompt personas are skills/specialists, not fake HADES agents.
            if not is_executable or claimed in {"persona", "prompt", "specialist"}:
                capabilities.append(
                    {
                        "id": meta.get("name") or path.stem,
                        "name": meta.get("name") or path.stem,
                        "description": meta.get("description") or (body.strip().splitlines() or [""])[0][:240],
                        "kind": "skill",
                        "content_ref": path.relative_to(root).as_posix(),
                        "from": "claude.agent_persona",
                        "persona_only": True,
                        "untrusted": True,
                    }
                )
            else:
                capabilities.append(
                    {
                        "id": meta.get("id") or meta.get("name") or path.stem,
                        "name": meta.get("name") or path.stem,
                        "description": meta.get("description") or "",
                        "kind": "agent",
                        "specialties": [item.strip() for item in meta.get("specialties", "").split(",") if item.strip()],
                        "accepts": [item.strip() for item in meta.get("accepts", "").split(",") if item.strip()],
                        "produces": [item.strip() for item in meta.get("produces", "").split(",") if item.strip()],
                        "content_ref": path.relative_to(root).as_posix(),
                        "from": "claude.subagent",
                        "executable": True,
                        "untrusted": True,
                    }
                )

        for path in list(_files(root, "commands")) + list(_files(root, ".claude/commands")):
            text = _read(path)
            meta, body = parse_frontmatter(text)
            capabilities.append(
                {
                    "id": meta.get("name") or path.stem,
                    "name": meta.get("name") or f"/{path.stem}",
                    "description": meta.get("description") or (body.strip().splitlines() or [""])[0][:240],
                    "kind": "workflow",
                    "content_ref": path.relative_to(root).as_posix(),
                    "from": "claude.slash_command",
                    "untrusted": True,
                }
            )

        for path in _files(root, "rules"):
            capabilities.append(
                {
                    "id": path.stem,
                    "name": path.stem,
                    "kind": "skill",
                    "content_ref": path.relative_to(root).as_posix(),
                    "from": "claude.rules",
                    "untrusted": True,
                }
            )

        hooks_dir = root / "hooks"
        claude_hooks = root / ".claude" / "hooks"
        for hook_root in (hooks_dir, claude_hooks):
            if not hook_root.exists():
                continue
            for path in sorted(hook_root.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                unsupported.append(
                    {
                        "path": rel,
                        "claimed_kind": "hook",
                        "reason": "Claude hooks have no safe HADES lifecycle equivalent; not registered as executable capabilities.",
                        "adapter_id": self.adapter_id,
                    }
                )

        # Tool-instruction markdown is usage metadata, not a new tool.
        for path in _files(root, "tool-guidance") + _files(root, "tools"):
            if path.suffix.lower() not in {".md", ".mdc", ".txt"}:
                continue
            capabilities.append(
                {
                    "id": f"usage/{path.stem}",
                    "name": path.stem,
                    "kind": "knowledge",
                    "content_ref": path.relative_to(root).as_posix(),
                    "from": "claude.tool_instruction",
                    "untrusted": True,
                }
            )

        return {"capabilities": capabilities, "unsupported": unsupported}
