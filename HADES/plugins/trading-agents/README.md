# Trading Agents — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents).

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
| `prepare` | See manifest |
| `run_round` | See manifest |

Paper/simulation only. No broker session. run_round needs a live local model and is not autonomous.
