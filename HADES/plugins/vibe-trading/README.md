# Vibe-Trading — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading).

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
| `research` | See manifest |
| `list_tools` | See manifest |
| `call_tool` | See manifest |

Heavy finance stack. Set LANGCHAIN_MODEL to a dynamic LM Studio id before research/start. MCP surface is research-only.
