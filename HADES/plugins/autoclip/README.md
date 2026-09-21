# AutoClip — HADES plugin

Installable `.HadesPlugin` wrapper around [https://github.com/zhouxiaoka/autoclip](https://github.com/zhouxiaoka/autoclip).

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
| `probe` | See manifest |
| `cut` | See manifest |

Autonomous disabled for cut. ffmpeg required for probe/cut; doctor stays honest.
