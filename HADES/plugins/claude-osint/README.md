# Claude OSINT — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/elementalsouls/Claude-OSINT](https://github.com/elementalsouls/Claude-OSINT).

## Install in HADES

1. Build the package:

```bat
python plugins\<plugin-id>\pack_hadesplugin.py --out plugins\<plugin-id>\dist
```

2. HADES → **Plugins** → **ZIP / .HadesPlugin**
3. Approve dependency install when prompted
4. Enable the plugin when status is Ready
5. Run tools from the Plugins page (or via autonomous shortlist when `autonomous: true`)

## Tools

| Tool | Purpose |
|------|---------|
| `list_skills` | See manifest |
| `get_skill` | See manifest |
| `search_skills` | See manifest |

Read-only skill lookup over Claude-OSINT SKILL.md packages. This plugin exposes list/get/search only; it does not run offensive recon scripts from upstream skills/*/scripts folders.
