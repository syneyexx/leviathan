#!/usr/bin/env python3
"""Optional isolated market_sim worker process (Windows-friendly).

Usage (with feature flag on and shared DB/markets root):
  set LEVIATHAN_FEATURE_MARKET_SIM=true
  python scripts/market_sim_worker.py

This is the honest subprocess path. The default Core boot still uses a daemon
thread inside the HTTP process when the feature flag is enabled.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("LEVIATHAN_FEATURE_MARKET_SIM", "true")


def main() -> int:
    from Data.backend.config import load_settings
    from Data.modules.market_sim.service import MarketSimControlPlane

    settings = load_settings()
    plane = MarketSimControlPlane.from_settings(settings)
    if not plane.enabled:
        print("FEATURE_DISABLED: set LEVIATHAN_FEATURE_MARKET_SIM=true", file=sys.stderr)
        return 2
    plane.worker.mark_subprocess()
    print(f"market_sim worker pid={os.getpid()} mode=subprocess")
    plane.worker.start_background(poll_seconds=0.25)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        plane.worker.stop_background()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
