# Scrapling — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling).

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
| `install_browsers` | See manifest |
| `fetch` | See manifest |
| `extract` | See manifest |

Autonomous use is disabled. Allow network policy before fetch/extract. Run install_browsers once for stealth/dynamic modes.
