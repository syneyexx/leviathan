# Worktrunk — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/max-sixty/worktrunk](https://github.com/max-sixty/worktrunk).

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
| `list_worktrees` | See manifest |
| `add_worktree` | See manifest |
| `remove_worktree` | See manifest |

Autonomous disabled because add/remove mutate git worktrees. Git on PATH is enough.
