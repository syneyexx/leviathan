# GhostTrack — HADES plugin

Installable `.HadesPlugin` wrapper around
[HunxByts/GhostTrack](https://github.com/HunxByts/GhostTrack) OSINT helpers.

Upstream `GhostTR.py` is an interactive menu. HADES uses `hades_bridge.py`, which
exposes the same public lookups as JSON tools:

| Tool | Purpose |
|------|---------|
| `doctor` | Dependency / upstream presence check |
| `track_ip` | IP geolocation via ipwho.is |
| `show_ip` | This host's public IP via ipify |
| `track_phone` | Phone metadata via phonenumbers (not live GPS) |
| `track_username` | Public social URL probes (HTTP 200 heuristic) |
| `open_terminal` | Launch original interactive `GhostTR.py` |

Autonomous use is **disabled**. Network is required for IP and username tools.

## Pack

```bat
python plugins\ghosttrack\pack_hadesplugin.py --out plugins\ghosttrack\dist
```

## Install in HADES

1. Plugins → **ZIP / .HadesPlugin**
2. Select `ghosttrack-0.1.0.HadesPlugin`
3. Approve dependency install (`pip` into plugin venv: `requests`, `phonenumbers`)
4. Enable when status is Ready
5. Run tools from the Plugins UI (manual approval)

## Notes

- Phone lookup returns carrier/region metadata only — not device location.
- Username results use the same HTTP-200 heuristic as upstream and can include false positives.
- Upstream GhostTrack currently ships without a formal LICENSE file; respect the author's README terms.
