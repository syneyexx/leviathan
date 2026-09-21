# Activepieces — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/activepieces/activepieces](https://github.com/activepieces/activepieces).

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
| `start` | See manifest |
| `health` | See manifest |
| `status` | See manifest |
| `logs` | See manifest |
| `stop` | See manifest |

Requires Docker. Configure `.env` from upstream examples before start.
