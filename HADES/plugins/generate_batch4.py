#!/usr/bin/env python3
"""Generate HADES plugins for the Strijder-requested upstream batch.

Skills are vendored under skills/ so Capability Intelligence and skill_bridge
work without packing from git. Tool plugins use HADES-native stdlib bridges
that talk to local git/ffmpeg/LM Studio and fail closed when a dependency is
missing. Claude/Codex-only CLIs are not required at runtime.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from generate_catalog import (
    EMPTY,
    ROOT,
    SHARED,
    catalog_tools,
    copy_shared,
    packer_local,
    readme,
    skill_tools,
    write_json,
    write_text,
)

TEMPLATES = SHARED / "bridge_templates"


def _caps(effects: list[str], *, side: str = "process", cost: str = "cheap", latency: str = "fast") -> dict:
    failures = ["dependency", "schema", "timeout"]
    if "network" in effects:
        failures.append("network")
    return {
        "effects": effects,
        "side_effect_class": side,
        "cost_class": cost,
        "latency_class": latency,
        "failure_modes": failures,
    }


def _finalize(payload: dict) -> dict:
    payload.setdefault("isolation", "plugin_cwd")
    payload.setdefault("trust_default", "untrusted")
    payload.setdefault("hades_api", ">=0.4.1")
    payload.setdefault("version", "0.1.0")
    payload.setdefault("format", 1)
    effects = list(payload.get("capabilities", {}).get("effects") or [])
    if not effects:
        if "network" in (payload.get("permissions") or []):
            effects.append("network")
        if "filesystem" in (payload.get("permissions") or []):
            effects.extend(["read_files", "write_files"])
        effects.append("subprocess")
        seen: list[str] = []
        for item in effects:
            if item not in seen:
                seen.append(item)
        effects = seen
    payload.setdefault("capabilities", _caps(effects, cost="cheap", latency="fast"))
    market = {
        "pinned_version": payload.get("version", "0.1.0"),
        "source_url": payload.get("source", ""),
        "signed": False,
    }
    if payload.get("license"):
        market["license"] = payload["license"]
    payload.setdefault("marketplace", market)
    for tool in payload.get("tools") or []:
        tool.setdefault("mode", "command")
        tool.setdefault("capabilities", dict(payload["capabilities"]))
    return payload


def _copy_template(name: str, dest: Path, filename: str = "hades_bridge.py") -> None:
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATES / name, dest / filename)


def _skill_md(folder: Path, skill_id: str, title: str, body: str) -> None:
    path = folder / "skills" / skill_id / "SKILL.md"
    if path.is_file():
        return
    write_text(
        path,
        f"""---
name: {skill_id}
description: {title}
---

# {title}

{body.strip()}
""",
    )


def make_skill_plugin(
    plugin_id: str,
    name: str,
    source: str,
    description: str,
    category: str,
    labels: list[str],
    *,
    license_id: str | None = None,
    extra_tools: list[dict] | None = None,
    extra_files: dict[str, str] | None = None,
    skill_seed: list[tuple[str, str, str]] | None = None,
    notes: str = "",
    autonomous: bool = True,
    knowledge_paths: list[str] | None = None,
) -> None:
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    copy_shared(overlay, ["skill_bridge.py"])
    copy_shared(folder, ["skill_bridge.py"])
    write_text(overlay / "requirements.txt", "# skill plugin — stdlib only\n")
    write_text(folder / "requirements.txt", "# skill plugin — stdlib only\n")
    tools = skill_tools(name)
    for tool in tools:
        tool["capabilities"] = _caps(["subprocess"])
        if tool["name"] in {"list_skills", "search_skills"}:
            tool["metadata"] = {"static_knowledge": True, "action": tool["action"]}
    if extra_tools:
        tools.extend(extra_tools)
    if extra_files:
        for rel, src_name in extra_files.items():
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(TEMPLATES / src_name, target)
            overlay_target = overlay / rel
            overlay_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(TEMPLATES / src_name, overlay_target)
    for skill_id, title, body in skill_seed or []:
        _skill_md(folder, skill_id, title, body)
    payload = _finalize(
        {
            "id": plugin_id,
            "name": name,
            "description": description,
            "runtime_type": "python",
            "entrypoint": "skill_bridge.py",
            "plugin_type": "tool",
            "category": category,
            "labels": labels,
            "permissions": ["subprocess"],
            "autonomous": autonomous,
            "source": source,
            "tools": tools,
            "knowledge_paths": knowledge_paths or ["README.md"],
        }
    )
    if license_id:
        payload["license"] = license_id
        payload["marketplace"]["license"] = license_id
    write_json(folder / "hades-plugin.json", payload)
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(
        folder / "README.md",
        readme(
            name,
            source,
            [t["name"] for t in tools],
            notes
            or (
                "HADES loads these skills through list_skills/get_skill/search_skills "
                "and indexes skills/ for Chat retrieval. Claude/Codex CLIs are not required."
            ),
        ),
    )


def _tool(
    name: str,
    action: str,
    description: str,
    command: list[str],
    schema: dict,
    *,
    effects: list[str] | None = None,
    cost: str = "cheap",
    latency: str = "fast",
    autonomous_ok: bool = True,
) -> dict:
    payload = {
        "name": name,
        "action": action,
        "mode": "command",
        "description": description,
        "command": command,
        "input_schema": schema,
        "capabilities": _caps(effects or ["subprocess"], cost=cost, latency=latency),
    }
    if not autonomous_ok:
        payload["autonomous"] = False
    return payload


def make_tool_plugin(
    plugin_id: str,
    name: str,
    source: str,
    description: str,
    category: str,
    labels: list[str],
    *,
    template: str,
    tools: list[dict],
    license_id: str | None = None,
    permissions: list[str] | None = None,
    autonomous: bool = True,
    needs_lm: bool = False,
    skill_seed: list[tuple[str, str, str]] | None = None,
    notes: str = "",
) -> None:
    folder = ROOT / plugin_id
    folder.mkdir(parents=True, exist_ok=True)
    overlay = folder / "overlay"
    overlay.mkdir(parents=True, exist_ok=True)
    _copy_template(template, folder)
    _copy_template(template, overlay)
    if needs_lm:
        shutil.copy2(SHARED / "lm_client.py", folder / "lm_client.py")
        shutil.copy2(SHARED / "lm_client.py", overlay / "lm_client.py")
    write_text(folder / "requirements.txt", "# stdlib only — optional LM Studio via urllib\n")
    write_text(overlay / "requirements.txt", "# stdlib only — optional LM Studio via urllib\n")
    for skill_id, title, body in skill_seed or []:
        _skill_md(folder, skill_id, title, body)
    payload = _finalize(
        {
            "id": plugin_id,
            "name": name,
            "description": description,
            "runtime_type": "python",
            "entrypoint": "hades_bridge.py",
            "plugin_type": "tool",
            "category": category,
            "labels": labels,
            "permissions": permissions or ["subprocess"],
            "autonomous": autonomous,
            "source": source,
            "tools": tools,
            "knowledge_paths": ["README.md"],
        }
    )
    if license_id:
        payload["license"] = license_id
        payload["marketplace"]["license"] = license_id
    write_json(folder / "hades-plugin.json", payload)
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(folder / "README.md", readme(name, source, [t["name"] for t in tools], notes))


def make_catalog_plugin(
    plugin_id: str,
    name: str,
    source: str,
    description: str,
    category: str,
    labels: list[str],
    *,
    license_id: str | None = None,
    skill_seed: list[tuple[str, str, str]] | None = None,
    extra_tools: list[dict] | None = None,
    extra_files: dict[str, str] | None = None,
    notes: str = "",
) -> None:
    folder = ROOT / plugin_id
    overlay = folder / "overlay"
    copy_shared(overlay, ["catalog_bridge.py", "skill_bridge.py"])
    copy_shared(folder, ["catalog_bridge.py", "skill_bridge.py"])
    write_text(overlay / "requirements.txt", "# catalog/skill plugin — stdlib only\n")
    write_text(folder / "requirements.txt", "# catalog/skill plugin — stdlib only\n")
    if extra_files:
        for rel, src_name in extra_files.items():
            shutil.copy2(TEMPLATES / src_name, folder / rel)
            shutil.copy2(TEMPLATES / src_name, overlay / rel)
    tools = catalog_tools(name) + skill_tools(name)
    if extra_tools:
        tools.extend(extra_tools)
    for tool in tools:
        tool.setdefault("capabilities", _caps(["subprocess"]))
        if tool["name"] in {"list_entries", "search", "list_skills", "search_skills"}:
            tool["metadata"] = {"static_knowledge": True, "action": tool["action"]}
    for skill_id, title, body in skill_seed or []:
        _skill_md(folder, skill_id, title, body)
    payload = _finalize(
        {
            "id": plugin_id,
            "name": name,
            "description": description,
            "runtime_type": "python",
            "entrypoint": "skill_bridge.py",
            "plugin_type": "tool",
            "category": category,
            "labels": labels,
            "permissions": ["subprocess"],
            "autonomous": True,
            "source": source,
            "tools": tools,
            "knowledge_paths": ["README.md"],
        }
    )
    if license_id:
        payload["license"] = license_id
        payload["marketplace"]["license"] = license_id
    write_json(folder / "hades-plugin.json", payload)
    write_text(folder / "pack_hadesplugin.py", packer_local(plugin_id))
    write_text(folder / "README.md", readme(name, source, [t["name"] for t in tools], notes))


def _refresh_readme() -> None:
    ids = sorted(p.name for p in ROOT.iterdir() if p.is_dir() and (p / "hades-plugin.json").is_file())
    write_text(
        ROOT / "README.md",
        f"""
        # HADES plugins

        Installable `.HadesPlugin` packages and manifests.

        ## Catalog ({len(ids)})

        {chr(10).join(f"- `{item}`" for item in ids)}

        ## Pack one plugin

        ```bat
        python plugins\\markitdown\\pack_hadesplugin.py --out plugins\\markitdown\\dist
        ```

        ## Pack all local-ready plugins

        ```bat
        python plugins\\pack_all.py --mode local
        ```

        Catalog plugin source lives here. Release-ready packages normally ship a `dist/<id>-<version>.HadesPlugin` artifact through Git LFS; rebuild with `python plugins\\pack_all.py` or the per-plugin packer when an artifact is not committed.

        Shared bridges live in `plugins/_shared/`.

        ## Batch 3 notes

        - `impeccable`, `gsap-skills`, `design-dna` — skill libraries for design/animation guidance
        - `patchright` — stealth Chromium fetch/screenshot (Python package)
        - `dspy` — DSPy predict/compile against LM Studio
        - `moneyprinter-turbo` — short-video WebUI service
        - `vibe-trading` — finance research UI + MCP
        - `bikini/exploitarium` is intentionally **not** packaged (exploit PoC archive)

        ## Batch 4 notes

        - Skill libraries (`openai-skills`, `superpowers`, Anthropic agent skills, …) ship `skills/**/SKILL.md` so Chat/Capability Intelligence can retrieve them.
        - Tool plugins (`codebase-memory`, `worktrunk`, `graft`, `data-formulator`, …) are HADES-native: they run locally and fail closed when git/ffmpeg/LM Studio is missing.
        - Claude/Codex CLIs are not required. LM Studio model ids stay caller-supplied.
        - TradingAgents wrapper is paper/simulation only.
        """,
    )


def main() -> None:
    make_tool_plugin(
        "codebase-memory",
        "Codebase Memory",
        "https://github.com/DeusData/codebase-memory-mcp",
        "Local symbol/FTS index of a workspace so HADES can query a codebase without the upstream C MCP binary.",
        "Developer",
        ["code-intelligence", "index", "memory"],
        template="codebase-memory.py",
        license_id="MIT",
        permissions=["subprocess", "filesystem"],
        skill_seed=[
            (
                "codebase-memory",
                "Codebase Memory",
                """Use this plugin when HADES needs durable local recall of a repository.

1. `index` a project root (creates SQLite FTS + symbol names).
2. `query` for a symbol, filename, or phrase.
3. `outline` for a bounded file list.

Do not claim the upstream C MCP graph is running unless doctor/index evidence says so.
Windows paths are first-class. Skip `node_modules`, `.venv`, and other dependency trees.
""",
            )
        ],
        tools=[
            _tool("doctor", "doctor", "Report local indexer status.", ["{python}", "hades_bridge.py", "doctor"], EMPTY),
            _tool(
                "index",
                "index",
                "Index a local source tree into SQLite FTS.",
                ["{python}", "hades_bridge.py", "index", "--root", "{root}", "--db", "{db}", "--limit", "{limit}"],
                {
                    "type": "object",
                    "required": ["root"],
                    "properties": {
                        "root": {"type": "string", "minLength": 1, "maxLength": 400},
                        "db": {"type": "string", "default": "codebase-memory.sqlite", "maxLength": 300},
                        "limit": {"type": "integer", "default": 4000, "minimum": 10, "maximum": 20000},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files", "write_files"],
                autonomous_ok=False,
            ),
            _tool(
                "query",
                "search",
                "Search the local codebase memory index.",
                ["{python}", "hades_bridge.py", "query", "--query", "{query}", "--db", "{db}", "--limit", "{limit}"],
                {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "minLength": 1, "maxLength": 200},
                        "db": {"type": "string", "default": "codebase-memory.sqlite", "maxLength": 300},
                        "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files"],
            ),
            _tool(
                "outline",
                "list",
                "List indexable source files under a root.",
                ["{python}", "hades_bridge.py", "outline", "--root", "{root}", "--limit", "{limit}"],
                {
                    "type": "object",
                    "required": ["root"],
                    "properties": {
                        "root": {"type": "string", "minLength": 1, "maxLength": 400},
                        "limit": {"type": "integer", "default": 200, "minimum": 1, "maximum": 2000},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files"],
            ),
        ],
        notes="HADES-native indexer. The C MCP server is optional and not required for query/index to work.",
    )

    make_tool_plugin(
        "open-code-review",
        "Open Code Review",
        "https://github.com/alibaba/open-code-review",
        "Line-level review comments for local files: deterministic heuristics always, optional LM Studio pass.",
        "Developer",
        ["code-review", "quality"],
        template="open-code-review.py",
        license_id="Apache-2.0",
        permissions=["subprocess", "filesystem", "network"],
        needs_lm=True,
        skill_seed=[
            (
                "open-code-review",
                "Open Code Review",
                """Review local files the way a careful teammate would.

Always run `review_file` first (offline heuristics: secrets, eval, bare except, TODOs, long lines).
Use `review_with_model` only when a dynamic LM Studio model id is available.
Return line-level comments. Do not invent files. Do not claim the Alibaba Go harness ran unless it did.
""",
            )
        ],
        tools=[
            _tool("doctor", "doctor", "Check review bridge and LM client.", ["{python}", "hades_bridge.py", "doctor"], EMPTY, effects=["subprocess"]),
            _tool(
                "review_file",
                "review",
                "Static heuristic review of one local file.",
                ["{python}", "hades_bridge.py", "review_file", "--path", "{path}", "--max-chars", "{max_chars}"],
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "maxLength": 400},
                        "max_chars": {"type": "integer", "default": 24000, "minimum": 500, "maximum": 80000},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files"],
            ),
            _tool(
                "review_with_model",
                "review",
                "Static review plus LM Studio comments. Fails closed if the endpoint is down.",
                [
                    "{python}",
                    "hades_bridge.py",
                    "review_with_model",
                    "--path",
                    "{path}",
                    "--model",
                    "{model}",
                    "--base-url",
                    "{base_url}",
                    "--api-key",
                    "{api_key}",
                    "--max-chars",
                    "{max_chars}",
                ],
                {
                    "type": "object",
                    "required": ["path", "model"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "maxLength": 400},
                        "model": {"type": "string", "minLength": 1, "maxLength": 200},
                        "base_url": {"type": "string", "default": "", "maxLength": 400},
                        "api_key": {"type": "string", "default": "", "maxLength": 400},
                        "max_chars": {"type": "integer", "default": 24000, "minimum": 500, "maximum": 80000},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files", "network"],
                cost="moderate",
                latency="slow",
            ),
        ],
        notes="Does not require the upstream Go binary. LM Studio model ids are caller-supplied.",
    )

    make_tool_plugin(
        "worktrunk",
        "Worktrunk",
        "https://github.com/max-sixty/worktrunk",
        "Git worktree list/add/remove for parallel HADES agent workspaces. Uses git directly (no Rust binary required).",
        "Developer",
        ["git", "worktrees", "agents"],
        template="worktrunk.py",
        permissions=["subprocess", "filesystem"],
        autonomous=False,
        skill_seed=[
            (
                "worktrunk",
                "Worktrunk worktrees",
                """Use git worktrees when HADES needs isolated checkouts for parallel coding jobs.

- `list` the worktrees of a repo.
- `add` a path, optionally creating a branch.
- `remove` only with explicit operator approval (autonomous disabled).

Prefer this over copying folders. Fail if git is missing. Do not force-remove unless asked.
""",
            )
        ],
        tools=[
            _tool("doctor", "doctor", "Check git availability.", ["{python}", "hades_bridge.py", "doctor"], EMPTY),
            _tool(
                "list_worktrees",
                "list",
                "List git worktrees for a repo.",
                ["{python}", "hades_bridge.py", "list", "--repo", "{repo}"],
                {
                    "type": "object",
                    "properties": {"repo": {"type": "string", "default": "", "maxLength": 400}},
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files"],
            ),
            _tool(
                "add_worktree",
                "write",
                "Add a git worktree (writes to disk).",
                [
                    "{python}",
                    "hades_bridge.py",
                    "add",
                    "--repo",
                    "{repo}",
                    "--path",
                    "{path}",
                    "--branch",
                    "{branch}",
                    "--start-point",
                    "{start_point}",
                    "--create-branch",
                    "{create_branch}",
                ],
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "repo": {"type": "string", "default": "", "maxLength": 400},
                        "path": {"type": "string", "minLength": 1, "maxLength": 400},
                        "branch": {"type": "string", "default": "", "maxLength": 200},
                        "start_point": {"type": "string", "default": "", "maxLength": 200},
                        "create_branch": {"type": "string", "default": "false", "enum": ["true", "false"]},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files", "write_files"],
                autonomous_ok=False,
            ),
            _tool(
                "remove_worktree",
                "write",
                "Remove a git worktree.",
                ["{python}", "hades_bridge.py", "remove", "--repo", "{repo}", "--path", "{path}", "--force", "{force}"],
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "repo": {"type": "string", "default": "", "maxLength": 400},
                        "path": {"type": "string", "minLength": 1, "maxLength": 400},
                        "force": {"type": "string", "default": "false", "enum": ["true", "false"]},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "write_files"],
                autonomous_ok=False,
            ),
        ],
        notes="Autonomous disabled because add/remove mutate git worktrees. Git on PATH is enough.",
    )

    make_skill_plugin(
        "openai-skills",
        "OpenAI Skills",
        "https://github.com/openai/skills",
        "Codex/OpenAI agent skills catalog, searchable from HADES Chat and Plugin tools.",
        "Developer",
        ["skills", "codex", "openai"],
        skill_seed=[
            (
                "openai-skills",
                "OpenAI Skills",
                """Load a skill with get_skill before following it.

These skills were written for Codex; in HADES:
- Use Plugin tools and Chat instead of Codex CLI.
- Keep model ids dynamic (LM Studio).
- Prefer local files over network.
""",
            )
        ],
    )

    make_skill_plugin(
        "no-ai-slop",
        "No AI Slop",
        "https://github.com/petergyang/no-ai-slop",
        "Remove common AI-writing patterns. HADES can load the skill and run a local cleaner.",
        "Developer",
        ["writing", "skills", "editing"],
        license_id="MIT",
        extra_files={"hades_bridge.py": "writing-design.py"},
        extra_tools=[
            _tool(
                "clean",
                "transform",
                "Strip common AI-slop phrases from text.",
                ["{python}", "hades_bridge.py", "clean", "--text", "{text}"],
                {
                    "type": "object",
                    "required": ["text"],
                    "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 20000}},
                    "additionalProperties": False,
                },
            )
        ],
        skill_seed=[
            (
                "no-ai-slop",
                "No AI Slop",
                """Rewrite so it sounds like a specific human, not a generic assistant.

Ban: delve, tapestry, furthermore, moreover, leverage, utilize, paradigm shift,
game-changer, robust, cutting-edge, in today's fast-paced world, in conclusion.

Prefer concrete nouns, short sentences, and honest uncertainty.
After drafting, run the `clean` tool and then do a manual pass.
""",
            )
        ],
    )

    make_skill_plugin(
        "diagram-design",
        "Diagram Design",
        "https://github.com/cathrynlavery/diagram-design",
        "Editorial diagram types for HADES. Renders simple HTML/SVG locally (no Mermaid slop).",
        "Developer",
        ["diagrams", "svg", "skills"],
        license_id="MIT",
        extra_files={"hades_bridge.py": "writing-design.py"},
        extra_tools=[
            _tool(
                "render_boxes",
                "render",
                "Render a simple editorial box diagram to HTML/SVG.",
                ["{python}", "hades_bridge.py", "diagram", "--kind", "{kind}", "--title", "{title}", "--items", "{items}"],
                {
                    "type": "object",
                    "required": ["items"],
                    "properties": {
                        "kind": {"type": "string", "default": "boxes", "maxLength": 40},
                        "title": {"type": "string", "default": "Diagram", "maxLength": 120},
                        "items": {"type": "string", "minLength": 1, "maxLength": 2000},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "write_files"],
            )
        ],
        skill_seed=[
            (
                "diagram-design",
                "Diagram Design",
                """Prefer self-contained HTML + SVG. No drop shadows. No Mermaid.

Use `render_boxes` for a quick sequence of labeled boxes.
For richer types (swimlane, isometric, timeline) load the upstream skill docs after fetch/pack
and draw SVG by hand following those rules.
""",
            )
        ],
    )

    make_tool_plugin(
        "trading-agents",
        "Trading Agents",
        "https://github.com/TauricResearch/TradingAgents",
        "Paper-only multi-agent market debate (analyst/bull/bear/trader/risk) via LM Studio. Never places live orders.",
        "Finance",
        ["trading", "paper", "multi-agent"],
        template="trading-agents.py",
        license_id="Apache-2.0",
        permissions=["subprocess", "network", "filesystem"],
        needs_lm=True,
        skill_seed=[
            (
                "trading-agents",
                "Trading Agents (paper)",
                """SIMULATION/PAPER ONLY.

prepare → optional run_round with a dynamic local model id.
Risk must veto live-trading language and unbounded size.
Do not call brokers. HADES Trading Lab remains the execution/simulation engine.
""",
            )
        ],
        tools=[
            _tool("doctor", "doctor", "List paper roles and LM client status.", ["{python}", "hades_bridge.py", "doctor"], EMPTY, effects=["subprocess"]),
            _tool(
                "prepare",
                "prepare",
                "Build a paper debate brief for a ticker.",
                ["{python}", "hades_bridge.py", "prepare", "--ticker", "{ticker}", "--notes", "{notes}"],
                {
                    "type": "object",
                    "required": ["ticker"],
                    "properties": {
                        "ticker": {"type": "string", "minLength": 1, "maxLength": 20},
                        "notes": {"type": "string", "default": "", "maxLength": 8000},
                    },
                    "additionalProperties": False,
                },
            ),
            _tool(
                "run_round",
                "run",
                "Run a paper debate round on LM Studio. Fails closed if the model endpoint is down.",
                [
                    "{python}",
                    "hades_bridge.py",
                    "run_round",
                    "--ticker",
                    "{ticker}",
                    "--notes",
                    "{notes}",
                    "--model",
                    "{model}",
                    "--base-url",
                    "{base_url}",
                    "--api-key",
                    "{api_key}",
                ],
                {
                    "type": "object",
                    "required": ["ticker", "model"],
                    "properties": {
                        "ticker": {"type": "string", "minLength": 1, "maxLength": 20},
                        "notes": {"type": "string", "default": "", "maxLength": 8000},
                        "model": {"type": "string", "minLength": 1, "maxLength": 200},
                        "base_url": {"type": "string", "default": "", "maxLength": 400},
                        "api_key": {"type": "string", "default": "", "maxLength": 400},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "network", "write_files"],
                cost="expensive",
                latency="slow",
                autonomous_ok=False,
            ),
        ],
        notes="Paper/simulation only. No broker session. run_round needs a live local model and is not autonomous.",
    )

    make_tool_plugin(
        "ruview",
        "RuView",
        "https://github.com/ruvnet/RuView",
        "Parse local WiFi CSI dumps. Does not invent presence or vital signs without hardware evidence.",
        "Research",
        ["wifi", "csi", "sensing"],
        template="ruview.py",
        license_id="MIT",
        permissions=["subprocess", "filesystem"],
        skill_seed=[
            (
                "ruview",
                "RuView CSI",
                """RuView turns WiFi CSI into spatial intelligence only when hardware captures exist.

HADES can `parse_csi` on a local CSV/JSON dump and report statistics.
Never claim heartbeat, occupancy, or DensePose results from missing data.
""",
            )
        ],
        tools=[
            _tool("doctor", "doctor", "Explain hardware requirement honestly.", ["{python}", "hades_bridge.py", "doctor"], EMPTY),
            _tool(
                "parse_csi",
                "parse",
                "Parse a local CSI CSV/JSON capture.",
                ["{python}", "hades_bridge.py", "parse_csi", "--path", "{path}", "--max-rows", "{max_rows}"],
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "maxLength": 400},
                        "max_rows": {"type": "integer", "default": 2000, "minimum": 1, "maximum": 50000},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files"],
            ),
        ],
        notes="Fail closed without a local CSI file. No fake vital signs.",
    )

    make_tool_plugin(
        "data-formulator",
        "Data Formulator",
        "https://github.com/microsoft/data-formulator",
        "Offline CSV profiling and SVG/HTML charts for HADES. Does not start the Microsoft web UI.",
        "Data",
        ["csv", "charts", "visualization"],
        template="data-formulator.py",
        license_id="MIT",
        permissions=["subprocess", "filesystem"],
        skill_seed=[
            (
                "data-formulator",
                "Data Formulator",
                """Profile a CSV with `summarize`, then `chart` a bar or table to HTML.

Pick x/y from real column names. Do not invent columns.
This is local SVG/HTML — not the full Data Formulator concept-erasure UI.
""",
            )
        ],
        tools=[
            _tool("doctor", "doctor", "Confirm the local chart bridge.", ["{python}", "hades_bridge.py", "doctor"], EMPTY),
            _tool(
                "summarize",
                "summarize",
                "Profile a local CSV (columns, numeric stats).",
                ["{python}", "hades_bridge.py", "summarize", "--path", "{path}", "--max-rows", "{max_rows}"],
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "maxLength": 400},
                        "max_rows": {"type": "integer", "default": 500, "minimum": 1, "maximum": 20000},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files"],
            ),
            _tool(
                "chart",
                "render",
                "Write a local HTML/SVG chart from a CSV.",
                [
                    "{python}",
                    "hades_bridge.py",
                    "chart",
                    "--path",
                    "{path}",
                    "--x",
                    "{x}",
                    "--y",
                    "{y}",
                    "--type",
                    "{type}",
                    "--output",
                    "{output}",
                    "--max-rows",
                    "{max_rows}",
                ],
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "maxLength": 400},
                        "x": {"type": "string", "default": "", "maxLength": 80},
                        "y": {"type": "string", "default": "", "maxLength": 80},
                        "type": {"type": "string", "default": "bar", "enum": ["bar", "table"]},
                        "output": {"type": "string", "default": "chart.html", "maxLength": 300},
                        "max_rows": {"type": "integer", "default": 500, "minimum": 1, "maximum": 20000},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files", "write_files"],
            ),
        ],
        notes="Works fully offline on local CSV files.",
    )

    make_skill_plugin(
        "eli5",
        "ELI5",
        "https://github.com/DreambigOu/ELI5",
        "Explain anything to a chosen audience. HADES gets the skill plus a local explanation scaffold.",
        "Developer",
        ["education", "writing", "skills"],
        license_id="MIT",
        extra_files={"hades_bridge.py": "writing-design.py"},
        extra_tools=[
            _tool(
                "explain",
                "explain",
                "Build an ELI5 explanation scaffold for a topic and audience.",
                ["{python}", "hades_bridge.py", "eli5", "--topic", "{topic}", "--audience", "{audience}"],
                {
                    "type": "object",
                    "required": ["topic"],
                    "properties": {
                        "topic": {"type": "string", "minLength": 1, "maxLength": 400},
                        "audience": {"type": "string", "default": "curious adult", "maxLength": 80},
                    },
                    "additionalProperties": False,
                },
            )
        ],
        skill_seed=[
            (
                "eli5",
                "ELI5",
                """Match vocabulary to the audience (kid, manager, engineer, parent).

One-sentence definition → daily-life analogy → why it matters → one limitation.
No condescension. No fake certainty. Use the `explain` tool to get a scaffold, then write the answer in Chat.
""",
            )
        ],
    )

    make_tool_plugin(
        "graft",
        "Graft",
        "https://github.com/trailhq/Graft",
        "Local import/symbol graph so HADES can navigate a codebase cheaper than dumping whole files.",
        "Developer",
        ["code-graph", "context"],
        template="graft.py",
        license_id="MIT",
        permissions=["subprocess", "filesystem"],
        skill_seed=[
            (
                "graft",
                "Graft graph",
                """Index a repo, then query neighbors/search instead of stuffing entire trees into context.

Use results to pick files for Chat or the coding agent. Do not claim Graft cloud ranking.
""",
            )
        ],
        tools=[
            _tool("doctor", "doctor", "Confirm the local graph bridge.", ["{python}", "hades_bridge.py", "doctor"], EMPTY),
            _tool(
                "index",
                "index",
                "Build an import graph JSON for a source root.",
                ["{python}", "hades_bridge.py", "index", "--root", "{root}", "--output", "{output}", "--limit", "{limit}"],
                {
                    "type": "object",
                    "required": ["root"],
                    "properties": {
                        "root": {"type": "string", "minLength": 1, "maxLength": 400},
                        "output": {"type": "string", "default": "graft-graph.json", "maxLength": 300},
                        "limit": {"type": "integer", "default": 4000, "minimum": 10, "maximum": 20000},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files", "write_files"],
                autonomous_ok=False,
            ),
            _tool(
                "neighbors",
                "query",
                "Show imports / imported-by for a file in the graph.",
                ["{python}", "hades_bridge.py", "neighbors", "--graph", "{graph}", "--file", "{file}", "--limit", "{limit}"],
                {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "graph": {"type": "string", "default": "graft-graph.json", "maxLength": 300},
                        "file": {"type": "string", "minLength": 1, "maxLength": 400},
                        "limit": {"type": "integer", "default": 40, "minimum": 1, "maximum": 200},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files"],
            ),
            _tool(
                "search",
                "search",
                "Search the import graph for a symbol or path fragment.",
                ["{python}", "hades_bridge.py", "search", "--graph", "{graph}", "--query", "{query}", "--limit", "{limit}"],
                {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "graph": {"type": "string", "default": "graft-graph.json", "maxLength": 300},
                        "query": {"type": "string", "minLength": 1, "maxLength": 200},
                        "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files"],
            ),
        ],
        notes="Local import graph only. No Graft cloud service.",
    )

    make_catalog_plugin(
        "openmontage",
        "OpenMontage",
        "https://github.com/calesthio/OpenMontage",
        "Agentic video-production skills plus local ffmpeg probe/cut tools for HADES.",
        "Media",
        ["video", "ffmpeg", "skills"],
        license_id="AGPL-3.0",
        extra_files={"hades_bridge.py": "autoclip.py"},
        extra_tools=[
            _tool("doctor", "doctor", "Check ffmpeg/ffprobe.", ["{python}", "hades_bridge.py", "doctor"], EMPTY, effects=["subprocess"]),
            _tool(
                "probe",
                "probe",
                "Probe a local video with ffprobe.",
                ["{python}", "hades_bridge.py", "probe", "--path", "{path}"],
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 400}},
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files"],
            ),
            _tool(
                "cut",
                "cut",
                "Cut a local clip with ffmpeg stream copy.",
                [
                    "{python}",
                    "hades_bridge.py",
                    "cut",
                    "--path",
                    "{path}",
                    "--start",
                    "{start}",
                    "--duration",
                    "{duration}",
                    "--output",
                    "{output}",
                ],
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "maxLength": 400},
                        "start": {"type": "string", "default": "0", "maxLength": 32},
                        "duration": {"type": "string", "default": "10", "maxLength": 32},
                        "output": {"type": "string", "default": "clip.mp4", "maxLength": 300},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files", "write_files"],
                autonomous_ok=False,
            ),
        ],
        skill_seed=[
            (
                "openmontage",
                "OpenMontage",
                """Treat video work as a production pipeline: brief → assets → edit → export.

In HADES: load skills, then use probe/cut when ffmpeg is installed.
Do not claim ElevenLabs or cloud renderers ran. Fail closed without ffmpeg.
""",
            )
        ],
        notes="Skills are searchable. Probe/cut require ffmpeg and fail closed without it.",
    )

    make_tool_plugin(
        "autoclip",
        "AutoClip",
        "https://github.com/zhouxiaoka/autoclip",
        "Local ffmpeg probe/cut for highlight clips. Fails closed without ffmpeg.",
        "Media",
        ["video", "ffmpeg", "clips"],
        template="autoclip.py",
        license_id="MIT",
        permissions=["subprocess", "filesystem"],
        autonomous=False,
        skill_seed=[
            (
                "autoclip",
                "AutoClip",
                """Probe a local video, then cut a start/duration window with stream copy.

This is not cloud highlight detection. If ffmpeg is missing, stop and say so.
""",
            )
        ],
        tools=[
            _tool("doctor", "doctor", "Check ffmpeg/ffprobe.", ["{python}", "hades_bridge.py", "doctor"], EMPTY),
            _tool(
                "probe",
                "probe",
                "Probe a local video.",
                ["{python}", "hades_bridge.py", "probe", "--path", "{path}"],
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 400}},
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files"],
            ),
            _tool(
                "cut",
                "cut",
                "Cut a clip from a local video.",
                [
                    "{python}",
                    "hades_bridge.py",
                    "cut",
                    "--path",
                    "{path}",
                    "--start",
                    "{start}",
                    "--duration",
                    "{duration}",
                    "--output",
                    "{output}",
                ],
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1, "maxLength": 400},
                        "start": {"type": "string", "default": "0", "maxLength": 32},
                        "duration": {"type": "string", "default": "10", "maxLength": 32},
                        "output": {"type": "string", "default": "clip.mp4", "maxLength": 300},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "read_files", "write_files"],
                autonomous_ok=False,
            ),
        ],
        notes="Autonomous disabled for cut. ffmpeg required for probe/cut; doctor stays honest.",
    )

    make_skill_plugin(
        "ui-ux-pro-max",
        "UI UX Pro Max",
        "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill",
        "Design intelligence skill for professional UI/UX across platforms, usable from HADES Chat.",
        "Developer",
        ["ui", "ux", "skills", "design"],
        license_id="MIT",
        skill_seed=[
            (
                "ui-ux-pro-max",
                "UI UX Pro Max",
                """Before generating UI: name the platform, audience, and constraint.

Check hierarchy, spacing rhythm, contrast, tap targets, empty states, and error text.
Preserve HADES visual identity unless the operator asked to change it.
Prefer existing components over new design systems.
""",
            )
        ],
    )

    make_skill_plugin(
        "superpowers",
        "Superpowers",
        "https://github.com/obra/superpowers",
        "Agentic software-development methodology skills (brainstorm, plan, TDD, subagent habits) for HADES.",
        "Developer",
        ["skills", "sdlc", "methodology"],
        license_id="MIT",
        skill_seed=[
            (
                "superpowers",
                "Superpowers",
                """Work like a senior pair: brainstorm → plan → implement in small slices → verify.

Use HADES Work Runtime / coding jobs instead of Claude Code task tools.
Do not skip tests. Do not claim verification you did not run.
""",
            )
        ],
    )

    make_skill_plugin(
        "frontend-design-toolkit",
        "Frontend Design Toolkit",
        "https://github.com/wilwaldon/Claude-Code-Frontend-Design-Toolkit",
        "Frontend craft notes, skills, and checklists originally for Claude Code — loaded as HADES skills.",
        "Developer",
        ["frontend", "design", "skills"],
        skill_seed=[
            (
                "frontend-design-toolkit",
                "Frontend Design Toolkit",
                """Aim for distinctive layout, type, and motion — not generic AI cards.

Load specific skills before writing CSS/React.
Use HADES Plugins/MCP instead of Claude Code marketplace plugins.
Keep accessibility: focus, contrast, reduced motion.
""",
            )
        ],
    )

    make_skill_plugin(
        "karpathy-skills",
        "Karpathy Skills",
        "https://github.com/multica-ai/andrej-karpathy-skills",
        "Karpathy-inspired coding pitfalls as a HADES skill: less magic, more verification.",
        "Developer",
        ["skills", "coding", "quality"],
        skill_seed=[
            (
                "karpathy-skills",
                "Karpathy Skills",
                """LLMs over-edit, over-abstract, and skip running the code.

Rules for HADES: smallest diff, run tests, read errors, don't dump huge files,
don't invent APIs, prefer boring code. Verify instead of narrating confidence.
""",
            )
        ],
    )

    make_skill_plugin(
        "anthropic-agent-skills",
        "Anthropic Agent Skills",
        "https://github.com/anthropics/skills",
        "Official Anthropic skills used by HADES: frontend-design, algorithmic-art, canvas-design, theme-factory, web-artifacts-builder.",
        "Developer",
        ["anthropic", "skills", "design", "frontend"],
        skill_seed=[
            (
                "frontend-design",
                "Frontend Design",
                """Produce distinctive, production-grade frontend.

Avoid generic AI aesthetics (purple gradients, Inter, hero-card grids).
Commit to a bold type pairing, a clear layout idea, and real content.
Use HADES Chat + this skill; Claude Code is not required.
""",
            ),
            (
                "algorithmic-art",
                "Algorithmic Art",
                """Write generative art as original code (canvas/SVG).

Parameterize, iterate, and keep the RNG seed visible.
Do not paste stock illustrations. Prefer one strong algorithm.
""",
            ),
            (
                "canvas-design",
                "Canvas Design",
                """Design on a fixed canvas (poster, slide, social).

Establish grid, margin, and type hierarchy first.
Export SVG/HTML. No random Unsplash collages.
""",
            ),
            (
                "theme-factory",
                "Theme Factory",
                """Build a coherent theme: color, type, radius, elevation, density.

Output tokens HADES can apply. Do not restyle the frozen HADES GUI unless asked.
""",
            ),
            (
                "web-artifacts-builder",
                "Web Artifacts Builder",
                """Ship a self-contained HTML/CSS/JS artifact.

One folder, relative paths, no required CDN if avoidable.
State what was not verified in a browser.
""",
            ),
        ],
        notes="Five Anthropic public skills, adapted so HADES Chat/tools can load them without Claude Code.",
    )

    make_tool_plugin(
        "massgen",
        "MassGen",
        "https://github.com/massgen/MassGen",
        "Local committee of planner/critic/synthesizer via LM Studio. Does not launch the MassGen TUI or cloud providers.",
        "AI",
        ["multi-agent", "committee"],
        template="massgen.py",
        permissions=["subprocess", "network"],
        needs_lm=True,
        skill_seed=[
            (
                "massgen",
                "MassGen committee",
                """Use run_committee when a task benefits from independent critique.

Pass a dynamic local model id. Do not start MassGen's full orchestrator.
If LM Studio is down, fail closed and continue in Chat with the skill only.
""",
            )
        ],
        tools=[
            _tool("doctor", "doctor", "Report committee bridge status.", ["{python}", "hades_bridge.py", "doctor"], EMPTY, effects=["subprocess"]),
            _tool(
                "run_committee",
                "run",
                "Run planner/critic/synthesizer on a local model. Fails closed if LM Studio is down.",
                [
                    "{python}",
                    "hades_bridge.py",
                    "run_committee",
                    "--prompt",
                    "{prompt}",
                    "--model",
                    "{model}",
                    "--base-url",
                    "{base_url}",
                    "--api-key",
                    "{api_key}",
                    "--agents",
                    "{agents}",
                ],
                {
                    "type": "object",
                    "required": ["prompt", "model"],
                    "properties": {
                        "prompt": {"type": "string", "minLength": 1, "maxLength": 8000},
                        "model": {"type": "string", "minLength": 1, "maxLength": 200},
                        "base_url": {"type": "string", "default": "", "maxLength": 400},
                        "api_key": {"type": "string", "default": "", "maxLength": 400},
                        "agents": {"type": "string", "default": "planner,critic,synthesizer", "maxLength": 200},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "network"],
                cost="expensive",
                latency="slow",
                autonomous_ok=False,
            ),
        ],
        notes="Local LM Studio committee only. Cloud MassGen providers are not used.",
    )

    make_skill_plugin(
        "context-engineering-skills",
        "Context Engineering Skills",
        "https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering",
        "Skills for context engineering, memory, and multi-agent design — retrieved by HADES Chat.",
        "AI",
        ["context", "skills", "agents"],
        license_id="MIT",
        skill_seed=[
            (
                "context-engineering",
                "Context Engineering",
                """Treat context as a scarce budget.

Prefer retrieval (skills, knowledge index, codebase-memory, graft) over pasting everything.
Separate durable decisions from scratch notes.
When building agents in HADES, use Capability Intelligence + Work Runtime instead of ad-hoc prompt stacks.
""",
            )
        ],
    )

    make_tool_plugin(
        "omniroute",
        "OmniRoute",
        "https://github.com/diegosouzapw/OmniRoute",
        "Local-first LLM route table: LM Studio by default, optional extra OpenAI-compatible URLs. Not a 352-provider cloud gateway.",
        "AI",
        ["gateway", "lm-studio", "routing"],
        template="omniroute.py",
        license_id="MIT",
        permissions=["subprocess", "network"],
        needs_lm=True,
        skill_seed=[
            (
                "omniroute",
                "OmniRoute (local-first)",
                """Default to HADES LM Studio (127.0.0.1:1234).

Extra providers only if HADES_EXTRA_LLM_BASE_URLS is set.
Never require internet. Model ids stay dynamic.
If a remote route fails, stay on local.
""",
            )
        ],
        tools=[
            _tool("doctor", "doctor", "Probe local LM Studio and configured extras.", ["{python}", "hades_bridge.py", "doctor"], EMPTY, effects=["subprocess", "network"]),
            _tool("list_routes", "list", "List local and extra OpenAI-compatible routes.", ["{python}", "hades_bridge.py", "list_routes"], EMPTY, effects=["subprocess", "network"]),
            _tool(
                "complete",
                "complete",
                "Send a prompt to a chosen local/compatible endpoint. Fails closed if unreachable.",
                [
                    "{python}",
                    "hades_bridge.py",
                    "complete",
                    "--prompt",
                    "{prompt}",
                    "--model",
                    "{model}",
                    "--base-url",
                    "{base_url}",
                    "--api-key",
                    "{api_key}",
                ],
                {
                    "type": "object",
                    "required": ["prompt", "model"],
                    "properties": {
                        "prompt": {"type": "string", "minLength": 1, "maxLength": 8000},
                        "model": {"type": "string", "minLength": 1, "maxLength": 200},
                        "base_url": {"type": "string", "default": "", "maxLength": 400},
                        "api_key": {"type": "string", "default": "", "maxLength": 400},
                    },
                    "additionalProperties": False,
                },
                effects=["subprocess", "network"],
                cost="moderate",
                latency="slow",
            ),
        ],
        notes="Offline-first. Does not scrape 352 cloud providers. Extra URLs are operator-configured.",
    )

    make_catalog_plugin(
        "knowledge-work-plugins",
        "Knowledge Work Plugins",
        "https://github.com/anthropics/knowledge-work-plugins",
        "Anthropic knowledge-work plugin/skill library, searchable inside HADES.",
        "Research",
        ["knowledge", "anthropic", "skills"],
        license_id="Apache-2.0",
        skill_seed=[
            (
                "knowledge-work",
                "Knowledge Work",
                """Use these plugins as research/writing playbooks, not as Claude Cowork binaries.

Search/read the packaged docs, then apply the process in HADES Chat, Knowledge, and Files.
Keep sources explicit. Do not invent citations.
""",
            )
        ],
        notes="Catalog + skills. Claude Cowork is not launched.",
    )

    make_catalog_plugin(
        "claude-plugins-official",
        "Claude Plugins Official",
        "https://github.com/anthropics/claude-plugins-official",
        "Official Anthropic Claude Code plugin directory, exposed as HADES skills/docs (no Claude Code required).",
        "Developer",
        ["anthropic", "plugins", "skills"],
        license_id="Apache-2.0",
        skill_seed=[
            (
                "claude-plugins-official",
                "Claude Plugins Official",
                """These were packaged for Claude Code. In HADES:

- Load skills with get_skill / search.
- Map MCP servers to HADES MCP Host instead of Claude's MCP.
- Ignore Claude-only installer commands.
""",
            )
        ],
        notes="Read/search only. Does not execute Claude Code plugin installers.",
    )

    make_catalog_plugin(
        "firm-protocol",
        "Firm Protocol",
        "https://github.com/firm-org/firm-protocol",
        "Knowledge pack for internet-native company roles/protocol. HADES can read and apply the playbooks; it does not run a chain.",
        "Research",
        ["protocol", "org", "knowledge"],
        license_id="GPL-3.0",
        skill_seed=[
            (
                "firm-protocol",
                "Firm Protocol",
                """Use Firm as an organizational protocol: roles, decisions, and artifacts.

HADES can store those as project continuity / knowledge notes.
Do not deploy Solidity or treat this as a live company runtime.
""",
            )
        ],
        notes="Docs/skills only. No blockchain execution.",
    )

    _refresh_readme()
    ids = sorted(p.name for p in ROOT.iterdir() if p.is_dir() and (p / "hades-plugin.json").is_file())
    print("generated catalog", len(ids))


if __name__ == "__main__":
    main()
