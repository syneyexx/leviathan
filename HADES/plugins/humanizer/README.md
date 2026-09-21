# Humanizer — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/blader/humanizer](https://github.com/blader/humanizer).

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

Use list/get/search to load skill content into HADES tool results.
