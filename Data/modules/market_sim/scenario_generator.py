"""Deterministic offline market scenario generation for paper replay.

Architecture (canonical MarketSim authority — not a page-local simulator):

  UI / API
    → structured ScenarioSpec (regime sequence, vol, drift, shocks, seed)
    → optional Model Control Plane for STRUCTURED constraints only
    → deterministic OHLCV generator (never trust freehand LLM candles)
    → MarketDataStore register + provenance
    → selectable by historical replay / SimulationEngine

PAPER ONLY. Does not enable live money.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


GENERATOR_VERSION = "market_sim.scenario_generator.v1"


@dataclass
class RegimeSegment:
    name: str
    bars: int
    drift_bps: float = 0.0
    vol_bps: float = 20.0
    shock_bps: float = 0.0  # one-time jump at segment start


@dataclass
class ScenarioSpec:
    scenario_id: str
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    seed: int = 42
    start_price: float = 50_000.0
    start_ts: str = "2022-01-01T00:00:00Z"
    segments: list[RegimeSegment] = field(default_factory=list)
    narrative: str = ""
    prompt: str = ""
    model_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "scenarioId": self.scenario_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "seed": self.seed,
            "startPrice": self.start_price,
            "startTs": self.start_ts,
            "segments": [asdict(s) for s in self.segments],
            "narrative": self.narrative,
            "prompt": self.prompt,
            "modelId": self.model_id,
            "generatorVersion": GENERATOR_VERSION,
            "provenance": dict(self.provenance),
            "truth": {
                "deterministic_from_spec": True,
                "llm_does_not_emit_ohlcv_rows": True,
                "paper_replay_only": True,
                "not_live_money": True,
            },
        }


PRESETS: dict[str, list[RegimeSegment]] = {
    "range_chop": [
        RegimeSegment("chop_a", 80, drift_bps=0.0, vol_bps=12.0),
        RegimeSegment("chop_b", 80, drift_bps=0.0, vol_bps=18.0),
        RegimeSegment("chop_c", 80, drift_bps=0.0, vol_bps=10.0),
    ],
    "trend_up": [
        RegimeSegment("base", 40, drift_bps=1.0, vol_bps=15.0),
        RegimeSegment("impulse", 100, drift_bps=8.0, vol_bps=25.0),
        RegimeSegment("grind", 60, drift_bps=3.0, vol_bps=12.0),
    ],
    "crash_recovery": [
        RegimeSegment("calm", 40, drift_bps=1.0, vol_bps=10.0),
        RegimeSegment("crash", 20, drift_bps=-40.0, vol_bps=80.0, shock_bps=-800.0),
        RegimeSegment("capitulation", 40, drift_bps=-5.0, vol_bps=50.0),
        RegimeSegment("recovery", 100, drift_bps=6.0, vol_bps=30.0),
    ],
}


def _parse_ts(ts: str) -> datetime:
    raw = str(ts or "").strip().replace("Z", "+00:00")
    return datetime.fromisoformat(raw).astimezone(timezone.utc)


def _tf_delta(timeframe: str) -> timedelta:
    tf = str(timeframe or "1h").lower()
    if tf.endswith("m") and tf[:-1].isdigit():
        return timedelta(minutes=int(tf[:-1]))
    if tf.endswith("h") and tf[:-1].isdigit():
        return timedelta(hours=int(tf[:-1]))
    if tf.endswith("d") and tf[:-1].isdigit():
        return timedelta(days=int(tf[:-1]))
    return timedelta(hours=1)


def validate_spec(spec: ScenarioSpec) -> list[str]:
    errors: list[str] = []
    if not spec.symbol:
        errors.append("symbol_required")
    if not spec.segments:
        errors.append("segments_required")
    total = sum(max(0, int(s.bars)) for s in spec.segments)
    if total <= 0:
        errors.append("bars_required")
    if total > 50_000:
        errors.append("bars_exceed_bound")
    if spec.start_price <= 0:
        errors.append("start_price_invalid")
    try:
        _parse_ts(spec.start_ts)
    except Exception:
        errors.append("start_ts_invalid")
    return errors


def generate_ohlcv_rows(spec: ScenarioSpec) -> list[dict[str, Any]]:
    """Deterministic OHLCV from structured constraints + seed."""
    errs = validate_spec(spec)
    if errs:
        raise ValueError("invalid_scenario_spec:" + ",".join(errs))
    rng = random.Random(int(spec.seed))
    ts0 = _parse_ts(spec.start_ts)
    step = _tf_delta(spec.timeframe)
    price = float(spec.start_price)
    rows: list[dict[str, Any]] = []
    i = 0
    for seg in spec.segments:
        if seg.shock_bps:
            price *= 1.0 + float(seg.shock_bps) / 10_000.0
        for _ in range(max(0, int(seg.bars))):
            drift = float(seg.drift_bps) / 10_000.0
            vol = max(0.0, float(seg.vol_bps) / 10_000.0)
            # Box-Muller-ish via rng.gauss
            shock = rng.gauss(drift, vol) if vol > 0 else drift
            open_px = price
            close_px = max(1e-8, open_px * (1.0 + shock))
            wick = abs(rng.gauss(0.0, vol * 0.5))
            high = max(open_px, close_px) * (1.0 + wick)
            low = min(open_px, close_px) * (1.0 - wick)
            low = max(1e-8, low)
            volume = abs(rng.gauss(1000.0, 200.0))
            t = ts0 + step * i
            rows.append(
                {
                    "timestamp": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "open": round(open_px, 8),
                    "high": round(high, 8),
                    "low": round(low, 8),
                    "close": round(close_px, 8),
                    "volume": round(volume, 4),
                    "regime": seg.name,
                }
            )
            price = close_px
            i += 1
    # Causality / monotonic timestamps already by construction.
    for a, b in zip(rows, rows[1:]):
        if a["timestamp"] >= b["timestamp"]:
            raise ValueError("timestamp_not_monotonic")
        if not (b["low"] <= b["open"] <= b["high"] and b["low"] <= b["close"] <= b["high"]):
            raise ValueError("ohlc_invariant_broken")
    return rows


def dataset_hash(rows: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update(
            f"{r['timestamp']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}\n".encode()
        )
    return h.hexdigest()


def write_scenario_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["timestamp", "open", "high", "low", "close", "volume"],
        )
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in ("timestamp", "open", "high", "low", "close", "volume")})


def materialize_scenario(
    *,
    markets_root: Path,
    spec: ScenarioSpec,
) -> dict[str, Any]:
    """Generate bars, write CSV under markets_root, return registration payload."""
    rows = generate_ohlcv_rows(spec)
    digest = dataset_hash(rows)
    rel = Path("_scenarios") / f"{spec.scenario_id}_{spec.symbol}_{spec.timeframe}.csv"
    dest = Path(markets_root) / rel
    write_scenario_csv(dest, rows)
    meta_path = dest.with_suffix(".scenario.json")
    payload = {
        **spec.public_dict(),
        "datasetHash": digest,
        "barCount": len(rows),
        "path": str(dest),
        "relativePath": str(rel).replace("\\", "/"),
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "validation": {
            "monotonicTimestamps": True,
            "ohlcInvariants": True,
            "barCount": len(rows),
        },
    }
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def spec_from_request(body: dict[str, Any]) -> ScenarioSpec:
    """Build ScenarioSpec from API body. Supports preset names or explicit segments."""
    sid = str(body.get("scenarioId") or body.get("scenario_id") or f"scn-{uuid.uuid4().hex[:12]}")
    preset = str(body.get("preset") or "").strip().lower()
    segments_raw = body.get("segments")
    segments: list[RegimeSegment] = []
    if isinstance(segments_raw, list) and segments_raw:
        for s in segments_raw:
            if not isinstance(s, dict):
                continue
            segments.append(
                RegimeSegment(
                    name=str(s.get("name") or "seg"),
                    bars=int(s.get("bars") or 0),
                    drift_bps=float(s.get("driftBps") or s.get("drift_bps") or 0),
                    vol_bps=float(s.get("volBps") or s.get("vol_bps") or 20),
                    shock_bps=float(s.get("shockBps") or s.get("shock_bps") or 0),
                )
            )
    elif preset in PRESETS:
        segments = list(PRESETS[preset])
    else:
        # Default mild chop if nothing provided — still deterministic.
        segments = list(PRESETS["range_chop"])

    return ScenarioSpec(
        scenario_id=sid,
        symbol=str(body.get("symbol") or "BTCUSDT").upper(),
        timeframe=str(body.get("timeframe") or "1h"),
        seed=int(body.get("seed") or 42),
        start_price=float(body.get("startPrice") or body.get("start_price") or 50_000.0),
        start_ts=str(body.get("startTs") or body.get("start_ts") or "2022-01-01T00:00:00Z"),
        segments=segments,
        narrative=str(body.get("narrative") or ""),
        prompt=str(body.get("prompt") or ""),
        model_id=(str(body["modelId"]) if body.get("modelId") else None),
        provenance={
            "preset": preset or None,
            "source": "api",
        },
    )


def maybe_enrich_spec_from_model_constraints(
    spec: ScenarioSpec,
    constraints: dict[str, Any] | None,
) -> ScenarioSpec:
    """Apply structured model-produced constraints (never raw OHLCV rows)."""
    if not constraints or not isinstance(constraints, dict):
        return spec
    segs = constraints.get("segments")
    if isinstance(segs, list) and segs:
        built: list[RegimeSegment] = []
        for s in segs:
            if not isinstance(s, dict):
                continue
            built.append(
                RegimeSegment(
                    name=str(s.get("name") or "seg")[:64],
                    bars=max(1, min(5000, int(s.get("bars") or 1))),
                    drift_bps=float(s.get("driftBps") or s.get("drift_bps") or 0),
                    vol_bps=max(0.0, float(s.get("volBps") or s.get("vol_bps") or 20)),
                    shock_bps=float(s.get("shockBps") or s.get("shock_bps") or 0),
                )
            )
        if built:
            spec.segments = built
    if constraints.get("narrative"):
        spec.narrative = str(constraints["narrative"])[:2000]
    if constraints.get("startPrice") or constraints.get("start_price"):
        spec.start_price = float(constraints.get("startPrice") or constraints.get("start_price"))
    spec.provenance["model_constraints_applied"] = True
    return spec
