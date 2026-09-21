# Sinwindie OSINT — HADES plugin

Installable `.HadesPlugin` wrapper around
[sinwindie/OSINT](https://github.com/sinwindie/OSINT).

Upstream is a toolkit of OSINT attack-surface guides, bookmarklets, and the
**SULTAN** username checker. HADES ships a non-interactive JSON bridge:

| Tool | Purpose |
|------|---------|
| `doctor` | Bundle/dependency check |
| `search_username` | SULTAN-style public profile probes |
| `list_sites` | Curated URL templates / categories |
| `list_topics` | Topic + resource index (PDFs listed, not bundled) |
| `list_bookmarklets` / `get_bookmarklet` | Packaged bookmarklet helpers |

Autonomous use is **disabled**. Network required for `search_username`.

## Pack / install

```bat
python plugins\sinwindie-osint\pack_hadesplugin.py --out plugins\sinwindie-osint\dist
```

In HADES → Plugins → ZIP / `.HadesPlugin` → import `sinwindie-osint-0.1.0.HadesPlugin`.

## Author terms

Upstream README: personal investigative toolkit use; do **not** sell or host
without permission. Accept no liability — do no evil.
