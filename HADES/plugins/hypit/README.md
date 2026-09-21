# Hypit — HADES plugin

Installable `.HadesPlugin` wrapper around [hypit-ai/hypit](https://github.com/hypit-ai/hypit).

Hypit gives agents a video language (SVML/SVS/SVRun): clone a reference, swap host/product/language, and compile a re-runnable composition. This plugin is how HADES Chat and the Plugins page actually run that workflow.

## What HADES can do immediately (offline)

After marketplace install or ZIP import the plugin is **Ready** (stdlib Python). Enable it, then:

| Tool | Purpose |
|------|---------|
| `doctor` | Skill files + Node + whether the hypit CLI is present |
| `list_skills` / `get_skill` / `search_skills` | Hypit production skill, playbooks, syntax |
| `list_entries` / `search` / `read` | Packaged docs |
| `list_examples` / `inspect_source` | `.svml` / `.svs` / `.svrun` structural read (not a compile) |

Chat can load `SKILL.md` and inspect a local composition without Node.

## What needs the real Hypit CLI

Run **`prepare`** once (needs network + Node 22.15+ / npm). That installs pinned `@hypit/hypit` into the plugin vendor directory. Then:

| Tool | Hypit command |
|------|----------------|
| `version` | `hypit version --json` |
| `help` | `hypit help [topic]` |
| `paths` | `hypit paths --workspace` |
| `runtime_init` | `hypit runtime init` |
| `doctor_runtime` | `hypit doctor` (honest diagnostics, not a fake healthy runtime) |
| `check` / `plan` | verify / show work without executing |
| `media_probe` / `media_cut` / `media_fetch` | local media evidence |
| `build` / `status` / `logs` | submit and observe a Build (credentials required for generation) |

`prepare` skips Puppeteer Chromium download. Generation still uses the accounts you configure in `hypit.runtime.json` (HypiHub or your own provider). HADES does not invent API keys.

Write/network tools (`prepare`, `runtime_init`, `media_cut`, `media_fetch`, `build`) are **not autonomous**. Global block policy still wins.

## Install in HADES

### Marketplace (this repo)

1. HADES → **Plugins** → **Marketplace**
2. Install **Hypit**
3. Enable when status is Ready
4. Run `prepare` if you want the executable (optional for skill/inspect)

### Packed archive (full upstream tree)

```bat
python plugins\hypit\pack_hadesplugin.py --out plugins\hypit\dist
```

Then Plugins → **ZIP / .HadesPlugin** → `hypit-0.1.0.HadesPlugin`.

Packaging clones `https://github.com/hypit-ai/hypit` and overlays the HADES bridge. Runtime type is Python so HADES will **not** run `npm install` on Hypit's pnpm workspace during convert (that would fail). CLI install stays an explicit `prepare`.

## Windows notes

- Node 22.x from HADES PREPARE is required for CLI tools. Hypit asks for **22.15+**.
- Commands use argv arrays and `shell=False`.
- `npm.cmd` / `node.exe` are resolved without a Unix-only PATH.

## License

Upstream: [Hypit Open Source License](./UPSTREAM_LICENSE) (Apache-2.0 with additional conditions). Videos you produce belong to you; model-service terms are separate. This wrapper does not grant a multi-tenant Hypit SaaS license.
