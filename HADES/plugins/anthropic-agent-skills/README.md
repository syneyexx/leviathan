# Anthropic Agent Skills — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/anthropics/skills](https://github.com/anthropics/skills).

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

Five Anthropic public skills, adapted so HADES Chat/tools can load them without Claude Code.
