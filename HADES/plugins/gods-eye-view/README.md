# God's Eye View — HADES plugin

Installable `.HadesPlugin` wrapper around the MIT-licensed
[bilawalsidhu/gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view)
spatial globe app.

## Requirements

- **Node.js 24.14+ or 26.x** (upstream rejects Node 25 / older 22.x)
- npm on PATH
- Network for live public feeds (aircraft, ships, satellites, etc.)
- Optional keys inside the app **POWER UP** panel (Cesium ion, Google Maps, OpenAI)

## Install in HADES

1. Build the package (or use a prebuilt artifact from a release/agent run):

```bat
python plugins\gods-eye-view\pack_hadesplugin.py --out plugins\gods-eye-view\dist
```

2. In HADES → **Plugins** → **ZIP / .HadesPlugin**
3. Select `gods-eye-view-0.1.1.HadesPlugin`
4. Approve dependency install when prompted (`npm ci`)
5. Enable the plugin if it is Ready
6. Run tool **start** — when health passes, open **http://127.0.0.1:4173**

### Alternative: Git import

You can also import the upstream repo via **Git** in Plugin Manager, but only
after this `hades-plugin.json` is present in the source root (service start
requires an explicit healthcheck). Prefer the packaged `.HadesPlugin`.

## Tools

| Tool | Purpose |
|------|---------|
| `doctor` | Upstream setup doctor |
| `start` | Managed Vite service on `127.0.0.1:4173` |
| `health` / `status` | Healthcheck / status |
| `logs` | Persisted service logs |
| `stop` | Stop managed service |

Autonomous use is **disabled** (`autonomous: false`): start the globe from the Plugins UI.

## License notes

- Application source: MIT (Bilawal Sidhu)
- Bundled local datasets and third-party live feeds remain under their own terms — see upstream `LICENSE` / `SECURITY.md`
- Demo GIFs under `docs/media` are omitted from the pack to keep the archive smaller; they are not required to run
