"""Generic SKILL.md / Agent Skills importer.

Skills are declarative procedure/context packages — not shell authority.
Instructions load on demand; catalogs index metadata only.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
SKILL_NAME_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SkillRecord:
    skill_id: str
    name: str
    description: str
    source_repo: str | None = None
    source_path: str | None = None
    source_ref: str | None = None
    version: str | None = None
    content_hash: str = ""
    instructions: str = ""
    instruction_artifact: str | None = None
    resource_refs: list[str] = field(default_factory=list)
    script_refs: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    trigger_description: str | None = None
    enabled: bool = True
    catalog_only: bool = False
    module_id: str | None = None
    imported_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self, *, include_instructions: bool = False) -> dict[str, Any]:
        payload = {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "source_repo": self.source_repo,
            "source_path": self.source_path,
            "source_ref": self.source_ref,
            "version": self.version,
            "content_hash": self.content_hash,
            "instruction_artifact": self.instruction_artifact,
            "resource_refs": list(self.resource_refs),
            "script_refs": list(self.script_refs),
            "required_capabilities": list(self.required_capabilities),
            "trigger_description": self.trigger_description,
            "enabled": self.enabled,
            "catalog_only": self.catalog_only,
            "module_id": self.module_id,
            "imported_at": self.imported_at,
            "metadata": dict(self.metadata),
            "truth": {
                "skills_are_not_shell_authority": True,
                "instructions_load_on_demand": True,
            },
        }
        if include_instructions:
            payload["instructions"] = self.instructions
        return payload


class SkillImporter:
    """Discover and parse SKILL.md packages without loading thousands into prompts."""

    def discover_skill_files(self, root: Path, globs: tuple[str, ...] = ("**/SKILL.md",)) -> list[Path]:
        found: list[Path] = []
        seen: set[Path] = set()
        if not root.exists():
            return found
        for pattern in globs:
            for path in root.glob(pattern):
                if not path.is_file():
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                # Skip node_modules / .git noise.
                if any(part in {".git", "node_modules", ".venv"} for part in path.parts):
                    continue
                seen.add(resolved)
                found.append(path)
        return sorted(found)

    def parse_skill_file(
        self,
        path: Path,
        *,
        source_repo: str | None = None,
        source_ref: str | None = None,
        module_id: str | None = None,
        catalog_only: bool = False,
    ) -> SkillRecord:
        text = path.read_text(encoding="utf-8", errors="replace")
        frontmatter, body = _split_frontmatter(text)
        name = str(frontmatter.get("name") or "").strip()
        if not name:
            match = SKILL_NAME_RE.search(body)
            name = match.group(1).strip() if match else path.parent.name
        description = str(frontmatter.get("description") or "").strip()
        if not description:
            # First non-empty paragraph after title.
            for line in body.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    description = stripped[:500]
                    break
        version = str(frontmatter.get("version") or "").strip() or None
        trigger = str(frontmatter.get("trigger") or frontmatter.get("when_to_use") or "").strip() or None
        required = frontmatter.get("required_capabilities") or frontmatter.get("capabilities") or []
        if isinstance(required, str):
            required = [required]
        required_caps = [str(x) for x in required] if isinstance(required, list) else []

        resource_refs = _collect_relative(path.parent, ("resources", "references", "assets"))
        script_refs = _collect_relative(path.parent, ("scripts",))

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        skill_id = _stable_skill_id(name=name, source_repo=source_repo, content_hash=content_hash, path=path)

        return SkillRecord(
            skill_id=skill_id,
            name=name,
            description=description,
            source_repo=source_repo,
            source_path=str(path),
            source_ref=source_ref,
            version=version,
            content_hash=content_hash,
            instructions=body.strip(),
            resource_refs=resource_refs,
            script_refs=script_refs,
            required_capabilities=required_caps,
            trigger_description=trigger or description,
            enabled=not catalog_only,
            catalog_only=catalog_only,
            module_id=module_id,
            metadata={"frontmatter_keys": sorted(frontmatter.keys())},
        )

    def import_tree(
        self,
        root: Path,
        *,
        source_repo: str | None = None,
        source_ref: str | None = None,
        module_id: str | None = None,
        globs: tuple[str, ...] = ("**/SKILL.md",),
        catalog_only: bool = False,
        limit: int | None = None,
    ) -> list[SkillRecord]:
        files = self.discover_skill_files(root, globs)
        records: list[SkillRecord] = []
        for path in files:
            try:
                records.append(
                    self.parse_skill_file(
                        path,
                        source_repo=source_repo,
                        source_ref=source_ref,
                        module_id=module_id,
                        catalog_only=catalog_only,
                    )
                )
            except Exception:  # noqa: BLE001 — unknown optional files must not poison discovery
                continue
            if limit is not None and len(records) >= limit:
                break
        return _dedupe(records)

    def import_catalog_index(
        self,
        root: Path,
        *,
        source_repo: str | None = None,
        module_id: str | None = None,
        limit: int = 5000,
    ) -> list[SkillRecord]:
        """Index catalog entries as metadata-only skills (no instruction bodies in prompts)."""
        # Prefer README bullet lists / markdown links naming skills.
        records: list[SkillRecord] = []
        readme = root / "README.md"
        if readme.exists():
            text = readme.read_text(encoding="utf-8", errors="replace")
            for name, desc, link in _parse_catalog_readme(text):
                content_hash = hashlib.sha256(f"{name}|{link}|{desc}".encode("utf-8")).hexdigest()
                records.append(
                    SkillRecord(
                        skill_id=_stable_skill_id(name=name, source_repo=source_repo, content_hash=content_hash, path=readme),
                        name=name,
                        description=desc,
                        source_repo=source_repo or link,
                        source_path=str(readme),
                        content_hash=content_hash,
                        instructions="",
                        trigger_description=desc,
                        enabled=False,
                        catalog_only=True,
                        module_id=module_id,
                        metadata={"catalog_link": link},
                    )
                )
                if len(records) >= limit:
                    break
        # Also index any SKILL.md as catalog_only metadata without loading bodies into prompts.
        for skill in self.import_tree(
            root,
            source_repo=source_repo,
            module_id=module_id,
            catalog_only=True,
            limit=max(0, limit - len(records)),
        ):
            skill.instructions = ""  # catalog: metadata only
            skill.catalog_only = True
            skill.enabled = False
            records.append(skill)
            if len(records) >= limit:
                break
        return _dedupe(records)


def load_skill_instructions(record: SkillRecord | dict[str, Any]) -> str:
    """On-demand instruction load — never inject catalog-scale bodies into system prompts."""
    if isinstance(record, SkillRecord):
        if record.instructions:
            return record.instructions
        path = record.source_path
    else:
        if record.get("instructions"):
            return str(record["instructions"])
        path = record.get("source_path")
    if path and Path(path).is_file():
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        _, body = _split_frontmatter(text)
        return body.strip()
    return ""


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw_fm, body = match.group(1), match.group(2)
    data: dict[str, Any] = {}
    for line in raw_fm.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip("\"'")
        if not key:
            continue
        # Minimal YAML-ish list support: [a, b]
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[key] = [part.strip().strip("\"'") for part in inner.split(",") if part.strip()] if inner else []
        else:
            data[key] = value
    return data, body


def _collect_relative(root: Path, dir_names: tuple[str, ...]) -> list[str]:
    refs: list[str] = []
    for name in dir_names:
        folder = root / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_file() and not any(p in {".git", "node_modules"} for p in path.parts):
                refs.append(str(path.relative_to(root)))
                if len(refs) >= 200:
                    return refs
    return refs


def _stable_skill_id(*, name: str, source_repo: str | None, content_hash: str, path: Path) -> str:
    basis = f"{name}|{source_repo or ''}|{content_hash}|{path.as_posix()}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "skill"
    return f"skill:{slug}:{digest}"


def _dedupe(records: list[SkillRecord]) -> list[SkillRecord]:
    """Fingerprint by name + normalized source + content hash."""
    seen: set[tuple[str, str, str]] = set()
    out: list[SkillRecord] = []
    for record in records:
        key = (
            record.name.strip().lower(),
            (record.source_repo or "").strip().lower(),
            record.content_hash,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(record)
    return out


def _parse_catalog_readme(text: str) -> Iterator[tuple[str, str, str]]:
    """Extract markdown list entries like `- [Name](url) - description`."""
    pattern = re.compile(
        r"^[\-\*]\s+\[([^\]]+)\]\(([^)]+)\)(?:\s*[\-\:—:]\s*(.+))?$",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        name = match.group(1).strip()
        link = match.group(2).strip()
        desc = (match.group(3) or "").strip()
        if name:
            yield name, desc, link
