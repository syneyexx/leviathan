# Open Code Review — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/alibaba/open-code-review](https://github.com/alibaba/open-code-review).

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
| `review_file` | See manifest |
| `review_with_model` | See manifest |

Does not require the upstream Go binary. LM Studio model ids are caller-supplied.
