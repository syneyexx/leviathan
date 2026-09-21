# Puppeteer — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/puppeteer/puppeteer](https://github.com/puppeteer/puppeteer).

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
| `fetch` | See manifest |
| `screenshot` | See manifest |

npm install downloads Chromium. Autonomous use is disabled; allow network policy for page loads.
