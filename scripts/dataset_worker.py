#!/usr/bin/env python
"""Windows-friendly entrypoint for the shared dataset job worker.

Uses the same ``dataset_jobs`` table and KnowledgeStore as the API process.
Set ``LEVIATHAN_DATASET_JOBS_RUNNER=external`` before starting the API so the
in-process runner does not compete with this worker.

  python scripts/dataset_worker.py
  python scripts/dataset_worker.py --once
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Data.modules.datasets.worker import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
