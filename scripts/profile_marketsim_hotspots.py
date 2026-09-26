#!/usr/bin/env python3
"""W186 — Profile MarketSim / TradingGym hotspots under cProfile.

Runs a small deterministic TradingGym workload over a synthetic OHLCV fixture,
writes evidence JSON with top cumulative functions. Does not assume simulation
is the bottleneck — reports measured facts only.

Usage:
  python scripts/profile_marketsim_hotspots.py
  python scripts/profile_marketsim_hotspots.py --bars 200 --out Data/backend/tests/marketsim_hotspot_profile.json
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "Data" / "backend" / "tests" / "marketsim_hotspot_profile.json"


def _write_csv(path: Path, n: int) -> None:
    dt0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("timestamp,open,high,low,close,volume\n")
        for i in range(n):
            ts = (dt0 + timedelta(minutes=i)).isoformat(timespec="seconds")
            px = 100.0 + (i % 500) * 0.01
            fh.write(f"{ts},{px},{px + 0.5},{px - 0.5},{px + 0.1},{10 + (i % 7)}\n")


def _run_workload(bars: int) -> dict:
    # Import inside workload so import time is visible in the profile.
    from Data.backend.migrations import MigrationRunner
    from Data.modules.market_sim.gym import GymAction, GymActionKind, TradingGym
    from Data.modules.market_sim.ohlcv import iter_ohlcv, validate_ohlcv_file
    from Data.modules.market_sim.store import MarketSimStore
    from Data.modules.market_sim.types import RunStatus, SimRun

    with tempfile.TemporaryDirectory(prefix="marketsim-profile-") as tmp:
        root = Path(tmp)
        path = root / "BTCUSDT_1m.csv"
        _write_csv(path, bars)

        # Streaming validation pass (ingest-shaped hotspot candidate)
        validation = validate_ohlcv_file(path)
        streamed = sum(1 for _ in iter_ohlcv(path))

        db = root / "leviathan.db"
        MigrationRunner(db).apply_all()
        store = MarketSimStore(db)
        now = "2024-01-01T00:00:00+00:00"
        run = SimRun(
            run_id="profile-gym-1",
            status=RunStatus.CREATED.value,
            source_id="src",
            strategy_id=None,
            strategy_version=None,
            symbol="BTCUSDT",
            timeframe="1m",
            start_ts="",
            end_ts="",
            data_hash="",
            seed=7,
            created_at=now,
            updated_at=now,
        )
        store.create_run(run)
        gym = TradingGym(store)
        gym.reset(
            run,
            bars_path=str(path),
            entry_rules={"kind": "hold"},
            exit_rules={"kind": "hold"},
        )
        steps = 0
        done = False
        while not done and steps < bars - 1:
            kind = GymActionKind.HOLD if steps % 5 else GymActionKind.BUY
            if steps % 11 == 0:
                kind = GymActionKind.SELL
            result = gym.step(GymAction(kind=kind, qty=1.0 if kind != GymActionKind.HOLD else None))
            done = bool(result.done)
            steps += 1

        return {
            "bars": bars,
            "streamed_bars": streamed,
            "validation_ok": bool(validation.ok),
            "gym_steps": steps,
            "gym_done": done,
        }


def _top_cumulative(stats: pstats.Stats, limit: int = 40) -> list[dict]:
    # Mirror pstats cumulative ordering without parsing print_stats text.
    entries: list[tuple[float, float, int, str]] = []
    for func, (cc, _nc, tt, ct, _callers) in stats.stats.items():  # type: ignore[attr-defined]
        filename, line, name = func
        label = f"{filename}:{line}:{name}"
        entries.append((float(ct), float(tt), int(cc), label))
    entries.sort(key=lambda x: x[0], reverse=True)
    out: list[dict] = []
    for ct, tt, cc, label in entries[:limit]:
        out.append(
            {
                "function": label,
                "cumulative_seconds": round(ct, 6),
                "total_seconds": round(tt, 6),
                "call_count": cc,
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=240, help="synthetic OHLCV bar count")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="evidence JSON path")
    parser.add_argument("--top", type=int, default=40, help="top cumulative functions to keep")
    args = parser.parse_args(argv)

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    profiler = cProfile.Profile()
    workload_meta: dict = {}
    profiler.enable()
    try:
        workload_meta = _run_workload(int(args.bars))
    finally:
        profiler.disable()

    stream = StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.strip_dirs()
    stats.sort_stats("cumulative")
    top = _top_cumulative(stats, limit=int(args.top))
    total_calls = sum(int(e["call_count"]) for e in top)
    # Best-effort total time from pstats
    total_tt = sum(float(v[2]) for v in stats.stats.values())  # type: ignore[attr-defined]

    # Classify whether a pure deterministic kernel is an obvious win.
    pure_markers = (
        "ohlcv.py",
        "iter_ohlcv",
        "validate_ohlcv",
        "_normalize_ts",
        "check_ohlc",
        "load_ohlcv",
    )
    sim_markers = (
        "gym.py",
        "engine.py",
        "execution.py",
        "risk_guard",
        "accounting",
        "reward.py",
        "store.py",
        "sqlite",
    )
    top_cum = top[0]["cumulative_seconds"] if top else 0.0
    pure_share = 0.0
    sim_share = 0.0
    for entry in top[:15]:
        fn = entry["function"]
        share = entry["cumulative_seconds"]
        if any(m in fn for m in pure_markers):
            pure_share += share
        if any(m in fn for m in sim_markers):
            sim_share += share

    evidence = {
        "wave": "W186",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": "cProfile",
        "workload": {
            "description": "TradingGym reset+step over synthetic OHLCV + streaming validate",
            **workload_meta,
        },
        "totals": {
            "profiled_total_time_seconds": round(total_tt, 6),
            "top_entries": len(top),
            "top_call_count_sum": total_calls,
        },
        "top_cumulative_functions": top,
        "classification": {
            "pure_ohlcv_marker_cumulative_seconds_top15": round(pure_share, 6),
            "sim_engine_marker_cumulative_seconds_top15": round(sim_share, 6),
            "leading_function": top[0]["function"] if top else None,
            "leading_cumulative_seconds": top_cum,
            "notes": (
                "Shares are heuristic marker sums over top-15 cumulative entries; "
                "overlapping call stacks can double-count. Use as evidence, not proof."
            ),
        },
        "truth": {
            "does_not_assume_simulation_is_bottleneck": True,
            "evidence_only": True,
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"leading={evidence['classification']['leading_function']}")
    print(
        "pure_ohlcv_top15={:.4f}s sim_engine_top15={:.4f}s".format(
            pure_share,
            sim_share,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
