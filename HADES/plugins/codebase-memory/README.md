# Codebase Memory — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp).

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
| `index` | See manifest |
| `query` | See manifest |
| `outline` | See manifest |

HADES-native indexer. The C MCP server is optional and not required for query/index to work.
