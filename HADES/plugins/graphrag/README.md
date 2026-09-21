# GraphRAG — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/microsoft/graphrag](https://github.com/microsoft/graphrag).

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
| `init` | See manifest |
| `index` | See manifest |
| `query` | See manifest |

Autonomous use is disabled because indexing/query can incur LLM costs.
