#!/usr/bin/env python
"""Windows-friendly entrypoint for the source ingestion worker.

Uses the same JobStore ``source_ingestion.*`` capabilities as the API process.
Set ``LEVIATHAN_SOURCE_INGESTION_RUNNER=external`` before starting the API so the
in-process runner does not compete with this worker.

  python scripts/source_ingestion_worker.py
  python scripts/source_ingestion_worker.py --once
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Data.modules.source_ingestion.worker import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
