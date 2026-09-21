# Headroom — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/headroomlabs-ai/headroom](https://github.com/headroomlabs-ai/headroom).

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
| `compress` | See manifest |
| `start` | See manifest |
| `health` | See manifest |
| `status` | See manifest |
| `logs` | See manifest |
| `stop` | See manifest |

compress works offline for local files. start requires the proxy extra from headroom-ai[all].
