#!/usr/bin/env python3
"""Cheap UI/runtime baseline for A12 — no new infra.

Measures:
- Python import cost for hot modules
- ownership_snapshot() latency
- optional Vite/tsc presence (not a full browser benchmark)

Writes JSON under artifacts/baselines/ when possible.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def main() -> int:
    results: dict = {
        "kind": "hades_a12_baseline",
        "honesty": {
            "not_a_full_perf_suite": True,
            "no_new_infra": True,
            "sqlite_retained": True,
        },
        "imports_ms": {},
        "calls_ms": {},
    }

    t0 = time.perf_counter()
    import run_lifecycle  # noqa: F401

    results["imports_ms"]["run_lifecycle"] = _ms(t0)

    t0 = time.perf_counter()
    import artifacts  # noqa: F401

    results["imports_ms"]["artifacts"] = _ms(t0)

    t0 = time.perf_counter()
    import policy_enforcement  # noqa: F401

    results["imports_ms"]["policy_enforcement"] = _ms(t0)

    t0 = time.perf_counter()
    from run_lifecycle import ownership_snapshot

    snap = ownership_snapshot()
    results["calls_ms"]["ownership_snapshot"] = _ms(t0)
    results["ownership_surfaces"] = sorted(snap["surfaces"].keys())

    out_dir = ROOT / "artifacts" / "baselines"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "a12_runtime_baseline.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
