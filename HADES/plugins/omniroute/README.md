# OmniRoute — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/diegosouzapw/OmniRoute](https://github.com/diegosouzapw/OmniRoute).

This plugin is a **local-first OpenAI-compatible route table**. Inventory is discovered at runtime from LM Studio (default) and optional extra base URLs (`HADES_EXTRA_LLM_BASE_URLS`). It is not a hardcoded multi-provider cloud catalog.

HADES Coding can optionally execute model calls through this plugin. See `docs/CODING_OMNIROUTE.md`.

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
| `doctor` | Probe local LM Studio and configured extras |
| `list_routes` | Discover currently reachable OpenAI-compatible routes and models |
| `complete` | Small prompt completion against a chosen endpoint (fails closed if unreachable) |
| `chat` | Message-array completion via `--payload-file`; auto-selects among discovered routes when model is omitted |

Offline-first. Extra URLs are operator-configured. API keys come from the environment, never from coding job state.
