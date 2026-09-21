# GeoLibre — HADES plugin

Installable `.HadesPlugin` wrapper around the MIT-licensed
[opengeos/GeoLibre](https://github.com/opengeos/GeoLibre) geospatial platform,
plus a HADES-native offline data adapter so Chat/Work Runtime can actually use
GeoJSON datasets and spatial query results (not only open the map UI).

## What this gives HADES

1. **Map UI service** — GeoLibre Vite app on `http://127.0.0.1:5173` with the
   usual doctor/start/health/status/logs/stop lifecycle.
2. **Programmatic geospatial tools** — stdlib Python adapter (`geolibre_hades.py`)
   that loads local GeoJSON, analyzes schemas/stats, runs bbox/property/spatial
   queries, and returns compact JSON including a `hades_knowledge` evidence
   envelope the model loop can reuse.

Internet stays optional for the data tools: remote URLs are rejected. Remote
basemaps inside the Vite UI still need network when you choose to open them.

## Requirements

- **Node.js 22 or newer** (UI service only)
- npm on PATH (UI service only)
- Python 3.10+ already used by HADES (data tools; no extra GIS packages)
- Git only when building the `.HadesPlugin` package
- Port **5173** available locally when starting the UI

## Build the package

From the HADES repository root:

```bat
python plugins\geolibre\pack_hadesplugin.py --out plugins\geolibre\dist
```

Pinned upstream commit:
`cf02ccd881a3bc7b72f1af68a668dddffa0ffd7d` (GeoLibre `2.9.0`).
Override deliberately with `--ref <git-ref>`.

The packer vendors upstream GeoLibre source and overlays the HADES manifest plus
`geolibre_hades.py` / fixtures.

## Install in HADES

1. HADES → **Plugins** → **ZIP / .HadesPlugin**
2. Select `geolibre-0.2.0.HadesPlugin`
3. Approve dependency installation when prompted (`npm ci`)
4. Keep the plugin enabled once it reaches **Ready**
5. Use data tools immediately (no UI start required), or run **doctor** + **start**
   for the map UI and open **http://127.0.0.1:5173**

## Tools

| Tool | Autonomous | Purpose |
|---|---:|---|
| `geolibre_inspect` | yes | Feature counts, geometry types, bbox, property schema, samples |
| `geolibre_analyze` | yes | Geometry distribution + numeric property stats |
| `geolibre_load` | yes | Persist GeoJSON under a `dataset_id` for reuse |
| `geolibre_list` | yes | List loaded datasets |
| `geolibre_query` | yes | Bbox / property / contains-point / distance queries |
| `doctor` | no | Verify Node.js 22+ |
| `start` | no | Start GeoLibre UI on `127.0.0.1:5173` |
| `health` / `status` / `logs` / `stop` | no | Service lifecycle |

Plugin-level `autonomous` is enabled so research chat can select the data tools.
Lifecycle tools opt out per-tool so the model cannot silently start/stop the UI.

## Example inputs

Load inline GeoJSON:

```json
{
  "dataset_id": "demo-cities",
  "geojson": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "properties": {"name": "Amsterdam", "pop": 900000},
        "geometry": {"type": "Point", "coordinates": [4.9, 52.37]}
      }
    ]
  }
}
```

Query a loaded dataset:

```json
{
  "dataset_id": "demo-cities",
  "where": {"name": {"contains": "Amster"}},
  "bbox": [4.0, 52.0, 5.5, 53.0],
  "limit": 20
}
```

Polygon contains-point:

```json
{
  "dataset_id": "regions",
  "contains_point": [4.9, 52.37]
}
```

## Evidence contract

Successful data tools include:

```json
{
  "hades_knowledge": [
    {
      "title": "...",
      "uri": "file:///...",
      "source_type": "geolibre_dataset",
      "content": "...",
      "metadata": {
        "provider": "GeoLibre",
        "retrieved_at": "...",
        "content_sha256": "...",
        "dataset_id": "..."
      }
    }
  ]
}
```

This is evidence for HADES reasoning/knowledge workflows, not model-weight training.

## Adapter tests

```bat
python -m unittest plugins.geolibre.tests.test_geolibre_hades backend.tests.test_plugin_geolibre -v
```

## License and upstream

- GeoLibre source: MIT License, copyright Qiusheng Wu
- Upstream repository: `opengeos/GeoLibre`
- HADES adapter (`geolibre_hades.py`): part of this repository's plugin packaging
- Third-party datasets, basemaps, APIs, and services used through the UI may
  have their own licenses, credentials, quotas, and terms
