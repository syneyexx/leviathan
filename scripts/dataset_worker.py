#!/usr/bin/env python
"""Windows-friendly entrypoint for the shared dataset job worker.

When ``LEVIATHAN_DATASET_JOBS_RUNNER=external``, this process is the **sole**
runnable claim owner via Job Kernel ``dataset.process`` (pool ``dataset``).
Domain ``dataset_jobs`` retain metadata/history. Set the env before starting
the API so the in-process runner does not compete.

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
