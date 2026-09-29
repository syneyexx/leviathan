#!/usr/bin/env python
"""LEGACY / diagnostics entrypoint for standalone source ingestion.

Production Source Ingestion is owned by Worker Fabric::

    Data.modules.workers.entrypoints.source_ingestion

Do NOT run this script alongside an enabled WorkerSupervisor source_ingestion
pool — both would claim the same JobStore queue.

Canonical runner modes (``LEVIATHAN_SOURCE_INGESTION_RUNNER``):

  fabric              production (Worker Fabric pool) — default; legacy alias: external
  standalone_legacy   this script (dev/diagnostics only)
  inprocess_test      API-thread runner (tests)
  disabled            no executor

  python scripts/source_ingestion_worker.py
  python scripts/source_ingestion_worker.py --once
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Data.modules.source_ingestion.worker import (  # noqa: E402
    assert_single_source_ingestion_owner,
    fabric_owns_source_ingestion,
    main,
    resolve_runner_mode,
)


def _guarded_main(argv: list[str] | None = None) -> int:
    import os

    mode = resolve_runner_mode()
    unsafe = (os.environ.get("LEVIATHAN_ALLOW_STANDALONE_SOURCE_INGESTION") or "").strip().lower()
    if mode == "standalone_legacy" and unsafe not in {"1", "true", "yes", "on"}:
        print(
            "[source-ingestion-worker] REFUSING: standalone_legacy requires "
            "LEVIATHAN_ALLOW_STANDALONE_SOURCE_INGESTION=1 (dev/diagnostics only). "
            "Production owner is Worker Fabric.",
            flush=True,
        )
        return 2
    if fabric_owns_source_ingestion() and mode != "standalone_legacy":
        print(
            "[source-ingestion-worker] REFUSING to start: Worker Fabric owns "
            "source_ingestion. Set LEVIATHAN_SOURCE_INGESTION_RUNNER=standalone_legacy "
            "and LEVIATHAN_ALLOW_STANDALONE_SOURCE_INGESTION=1 only for explicit "
            "diagnostics, and disable fabric workers first.",
            flush=True,
        )
        return 2
    if mode == "standalone_legacy":
        # Explicit opt-in — still refuse if fabric pools are clearly active.
        try:
            assert_single_source_ingestion_owner(allow_standalone=True)
        except RuntimeError as exc:
            print(f"[source-ingestion-worker] {exc}", flush=True)
            return 2
        print(
            "[source-ingestion-worker] LEGACY standalone mode — diagnostics only",
            flush=True,
        )
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(_guarded_main())
