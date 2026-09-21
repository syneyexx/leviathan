#!/usr/bin/env python3
"""DEMO 06 — Context quality comparison scaffolding (legacy vs compiler).

Runs shadow_compare offline. Never claims live model quality.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from gen2.context_compiler import shadow_compare


def main() -> int:
    result = shadow_compare(
        query="What is HADES local-first security model?",
        legacy_chunks=[
            {"text": "HADES is offline-first.", "source": "docs"},
            {"text": "Unrelated trading note.", "source": "noise"},
        ],
        compiler_chunks=[
            {"text": "HADES is offline-first.", "source": "docs"},
            {"text": "Policy is deterministic code, not the model.", "source": "docs"},
            {"text": "Security decisions must fail closed.", "source": "docs"},
        ],
    )
    if result.get("not_model_quality") is not True:
        print("FAIL: missing not_model_quality honesty flag")
        return 1
    if result.get("compiler_coverage_proxy", 0) < result.get("legacy_coverage_proxy", 0):
        # Not required to win — but with this fixture compiler should not be worse.
        print("FAIL: compiler coverage proxy regressed on fixture")
        return 1
    print("PASS demo_06_context_quality")
    print(
        f"  legacy_cov={result['legacy_coverage_proxy']} "
        f"compiler_cov={result['compiler_coverage_proxy']} "
        f"delta={result['coverage_delta']}"
    )
    print("  note=lexical_proxy_only_not_live_model_quality")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
