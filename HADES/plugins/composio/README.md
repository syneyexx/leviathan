# Composio — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/ComposioHQ/composio](https://github.com/ComposioHQ/composio).

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
| `doctor` | See manifest |
| `list_toolkits` | See manifest |

Set COMPOSIO_API_KEY in the HADES process environment before using authenticated toolkits.
