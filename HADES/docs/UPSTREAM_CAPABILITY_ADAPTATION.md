# Upstream capability adaptation

HADES is not Claude Code. Portable upstream artifacts are adapted into HADES kinds. Unsupported Claude-specific runtime is reported honestly and is never faked.

External representation → adapter → normalized HADES contracts. Core routing does not `if source == "claude"`.

## Mapping

| Upstream | HADES |
|---|---|
| `SKILL.md` / `skills/**/SKILL.md` | `skill` (untrusted) |
| `CLAUDE.md` | scoped `knowledge` / project guidance |
| Agent markdown with executable tools/delegation | `agent` only when it represents delegated execution |
| Prompt persona / `type: persona` | `skill` with `persona_only` |
| `commands/*.md` slash command | `workflow` |
| MCP server config | `mcp_provider` |
| Tool-instruction markdown | usage/`knowledge` metadata |
| Hooks | **unsupported** — no safe HADES lifecycle equivalent |

Plugin/upstream prose cannot acquire system authority.

## Adding a new ecosystem

1. Implement a `PackageAdapter` (`detect` + `parse`) in `backend/capability_intel/adapters/`.
2. Register it in `default_registry()`.
3. Return unknown structures as `unsupported` rather than guessing a kind.

Current plugins are validation data, not the architecture limit.
