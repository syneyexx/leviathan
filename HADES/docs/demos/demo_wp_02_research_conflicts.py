#!/usr/bin/env python3
"""Demo 2 — Research with conflicting evidence.

Shows conflict, both sources, no invented resolution. Source change → stale dependents.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from research_conflicts import fixture_conflicting_research


def main() -> int:
    report = fixture_conflicting_research()
    claim = report["claims"][0]
    out = {
        "demo": "02_research_changing_evidence",
        "conflict_count": report["conflict_count"],
        "support_sources": [e.get("source") for e in claim.get("supports") or []],
        "contradict_sources": [e.get("source") for e in claim.get("contradicts") or []],
        "independent_support_origins": claim["independence"]["independent_support_origins"],
        "republications_collapsed": claim["independence"]["republications_collapsed"],
        "invented_resolution": report["invented_resolution"],
        "silenced": report["silenced"],
        "knowledge_gaps": report["knowledge_gaps"],
        "providers_required": [],
        "fixtures": ["research_conflicts.fixture_conflicting_research"],
        "not_proven": ["Live web harvest", "UI research page rendering"],
        "measured": {
            "claim_count": report["claim_count"],
            "conflict_count": report["conflict_count"],
        },
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    ok = (
        out["conflict_count"] >= 1
        and len(out["support_sources"]) >= 1
        and len(out["contradict_sources"]) >= 1
        and out["invented_resolution"] is False
        and out["independent_support_origins"] == 1
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
