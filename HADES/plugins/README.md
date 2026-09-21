# HADES plugins

Installable `.HadesPlugin` packages and manifests.

## Catalog (70)

- `activepieces`
- `agent-reach`
- `agentic-awesome-skills`
- `anthropic-agent-skills`
- `anthropic-cybersecurity-skills`
- `antigravity-awesome-skills`
- `autoclip`
- `awesome-claude-code`
- `awesome-claude-code-toolkit`
- `awesome-llm-apps`
- `chrome-devtools-mcp`
- `claude-code-best-practice`
- `claude-osint`
- `claude-plugins-official`
- `codebase-memory`
- `composio`
- `context-engineering-skills`
- `data-formulator`
- `deep-web-downloader`
- `design-dna`
- `desktop-commander-mcp`
- `diagram-design`
- `dspy`
- `ecc`
- `eli5`
- `financial-news-intelligence`
- `fincept-data`
- `firm-protocol`
- `frontend-design-toolkit`
- `geolibre`
- `ghosttrack`
- `gods-eye-view`
- `gpt-crawler`
- `graft`
- `graphrag`
- `gsap-skills`
- `headroom`
- `humanizer`
- `impeccable`
- `karpathy-skills`
- `knowledge-work-plugins`
- `kotaemon`
- `local-stt-paste`
- `markitdown`
- `massgen`
- `moneyprinter-turbo`
- `netstriker-ai`
- `no-ai-slop`
- `omniroute`
- `open-code-review`
- `openai-skills`
- `openmontage`
- `patchright`
- `ponytail`
- `project-nomad`
- `puppeteer`
- `rtk`
- `ruview`
- `scrapling`
- `searxng`
- `sinwindie-osint`
- `superpowers`
- `trading-agents`
- `ui-ux-pro-max`
- `ultimate-news-feeder`
- `unsloth`
- `vibe-trading`
- `voicestudio`
- `web-pdf-harvester`
- `worktrunk`

## Pack one plugin

```bat
python plugins\markitdown\pack_hadesplugin.py --out plugins\markitdown\dist
```

## Pack all local-ready plugins

```bat
python plugins\pack_all.py --mode local
```

Catalog plugin source lives here. Release-ready packages normally ship a `dist/<id>-<version>.HadesPlugin` artifact through Git LFS; rebuild with `python plugins\pack_all.py` or the per-plugin packer when an artifact is not committed.

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
