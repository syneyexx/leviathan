"""Scenario and stress engine (W18 / institutional Wave 6 stress catalog).

Canonical owner for scenario/stress — do **not** create ScenarioRiskV2.

Honesty contract:
- Stress scenarios are deterministic ASSUMED shocks, not forecasts.
- No fabricated occurrence probabilities.
- Missing inputs → measurement UNMEASURED (never fake PASS / invented PnL).
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


# ---------------------------------------------------------------------------
# Core types (W18) — extended, not replaced
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    name: str
    shocks: Mapping[str, float]  # symbol -> return shock (e.g. -0.1 = -10%)
    description: str = ""
    status: str = "ASSUMED"  # ASSUMED | CALIBRATED | UNMEASURED
    kind: str = "price_return"  # price_return | spread | liquidity | mixed
    params: Mapping[str, float] = field(default_factory=dict)
    seed: int | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "scenarioId": self.scenario_id,
            "name": self.name,
            "shocks": dict(self.shocks),
            "description": self.description,
            "status": self.status,
            "kind": self.kind,
            "params": dict(self.params),
            "seed": self.seed,
            "truth": {
                "scenario_is_ASSUMED_unless_calibrated": self.status != "CALIBRATED",
                "stress_scenario_is_not_a_forecast": True,
                "no_fabricated_probabilities": True,
                "not_live_trading": True,
            },
        }


@dataclass
class ScenarioResult:
    scenario_id: str
    base_equity: float
    shocked_equity: float
    pnl: float
    pnl_pct: float
    position_impacts: list[dict[str, Any]] = field(default_factory=list)
    measurement: str = "ASSUMED"
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "scenarioId": self.scenario_id,
            "baseEquity": self.base_equity,
            "shockedEquity": self.shocked_equity,
            "pnl": self.pnl,
            "pnlPct": self.pnl_pct,
            "positionImpacts": self.position_impacts,
            "measurement": self.measurement,
            "notes": list(self.notes),
            "truth": {
                "deterministic_shock_application": True,
                "stress_scenario_is_not_a_forecast": True,
                "no_fabricated_probabilities": True,
                "missing_data_is_UNMEASURED": True,
            },
        }


def apply_scenario(
    *,
    positions: Mapping[str, Mapping[str, Any]],
    marks: Mapping[str, float],
    cash: float,
    scenario: ScenarioSpec,
) -> ScenarioResult:
    """Apply price shocks to marks; long qty*px, short uses side if provided."""
    base_mv = 0.0
    shocked_mv = 0.0
    impacts: list[dict[str, Any]] = []
    for sym, pos in positions.items():
        qty = float(pos.get("qty") or 0)
        if qty == 0:
            continue
        side = str(pos.get("side") or "LONG").upper()
        px = float(marks.get(sym, pos.get("avg_entry") or 0))
        shock = float(scenario.shocks.get(sym, 0.0))
        shocked_px = px * (1.0 + shock)
        sign = 1.0 if side == "LONG" else -1.0
        base = sign * qty * px
        shocked = sign * qty * shocked_px
        base_mv += base
        shocked_mv += shocked
        impacts.append(
            {
                "symbol": sym,
                "side": side,
                "shock": shock,
                "baseValue": base,
                "shockedValue": shocked,
                "delta": shocked - base,
            }
        )
    base_eq = float(cash) + base_mv
    shocked_eq = float(cash) + shocked_mv
    pnl = shocked_eq - base_eq
    pnl_pct = (pnl / base_eq * 100.0) if base_eq else 0.0
    measurement = scenario.status if scenario.status in {"ASSUMED", "CALIBRATED", "UNMEASURED"} else "ASSUMED"
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        base_equity=base_eq,
        shocked_equity=shocked_eq,
        pnl=pnl,
        pnl_pct=pnl_pct,
        position_impacts=impacts,
        measurement=measurement,
    )


# Built-in legacy example — ASSUMED
EQUITY_CRASH_10 = ScenarioSpec(
    scenario_id="equity_crash_10",
    name="Broad equity -10%",
    shocks={},
    description="Apply -10% to all provided equity marks via caller-supplied shocks",
)


# ---------------------------------------------------------------------------
# Wave 6 — deterministic stress catalog
# ---------------------------------------------------------------------------

# Canonical required stress IDs. ``rate_move`` *or* ``fx_move`` satisfies the
# rate/FX requirement; both are published in the catalog.
STRESS_SCENARIO_IDS: tuple[str, ...] = (
    "equity_crash",
    "volatility_shock",
    "rate_move",
    "fx_move",
    "crypto_gap",
    "spread_widening",
    "liquidity_reduction",
    "correlated_selloff",
)

REQUIRED_STRESS_SCENARIO_IDS: frozenset[str] = frozenset(
    {
        "equity_crash",
        "volatility_shock",
        "crypto_gap",
        "spread_widening",
        "liquidity_reduction",
        "correlated_selloff",
    }
)
# rate_move OR fx_move (at least one must exist)
_RATE_OR_FX_IDS: frozenset[str] = frozenset({"rate_move", "fx_move"})

# ASSUMED shock magnitudes — labelled stress parameters, not forecasts / probs.
_ASSUMED_PARAMS: dict[str, dict[str, float]] = {
    "equity_crash": {"equity_return": -0.20},
    "volatility_shock": {"vol_mult": 2.0, "base_move": -0.05},
    "rate_move": {"rate_sensitive_return": -0.08},
    "fx_move": {"fx_return": -0.05},
    "crypto_gap": {"gap_return": -0.25},
    "spread_widening": {"spread_widen_frac": 0.04},  # adverse half-spread ≈ 2%
    "liquidity_reduction": {"liquidity_haircut": 0.15},
    "correlated_selloff": {"risk_asset_return": -0.18, "seed_jitter_bps": 25.0},
}

_CATALOG_META: dict[str, dict[str, str]] = {
    "equity_crash": {
        "name": "Equity crash stress",
        "description": "ASSUMED broad equity price decline. Stress scenario ≠ forecast.",
        "kind": "price_return",
    },
    "volatility_shock": {
        "name": "Volatility shock stress",
        "description": "ASSUMED adverse move scaled by a vol multiplier. Not a vol forecast.",
        "kind": "price_return",
    },
    "rate_move": {
        "name": "Rate move stress",
        "description": "ASSUMED adverse move for rate-sensitive instruments. Not a rate forecast.",
        "kind": "price_return",
    },
    "fx_move": {
        "name": "FX move stress",
        "description": "ASSUMED adverse FX spot move. Not an FX forecast.",
        "kind": "price_return",
    },
    "crypto_gap": {
        "name": "Crypto gap stress",
        "description": "ASSUMED discontinuous crypto gap. Not a probability of gap.",
        "kind": "price_return",
    },
    "spread_widening": {
        "name": "Spread widening stress",
        "description": "ASSUMED bid-ask widening applied as adverse mark shock. Not a spread forecast.",
        "kind": "spread",
    },
    "liquidity_reduction": {
        "name": "Liquidity reduction stress",
        "description": "ASSUMED liquidation haircut on marks. Not a liquidity forecast.",
        "kind": "liquidity",
    },
    "correlated_selloff": {
        "name": "Correlated selloff stress",
        "description": "ASSUMED simultaneous risk-asset selloff; seed only jitters magnitudes. Not a crash probability.",
        "kind": "mixed",
    },
}


def _stable_unit_float(seed: int, *parts: str) -> float:
    """Deterministic float in [0, 1) from seed + parts (no RNG object drift)."""
    h = hashlib.sha256()
    h.update(struct.pack(">q", int(seed)))
    for p in parts:
        h.update(b"\0")
        h.update(str(p).encode("utf-8"))
    digest = h.digest()[:8]
    return int.from_bytes(digest, "big") / float(2**64)


def _normalize_family(raw: str | None) -> str:
    text = str(raw or "").strip().lower()
    aliases = {
        "eq": "equity",
        "stock": "equity",
        "stocks": "equity",
        "etf": "equity",
        "fi": "fixed_income",
        "bond": "fixed_income",
        "bonds": "fixed_income",
        "rates": "fixed_income",
        "rate": "fixed_income",
        "fx": "forex",
        "forex": "forex",
        "currency": "forex",
        "crypto": "crypto",
        "digital": "crypto",
        "btc": "crypto",
        "perp": "crypto",
    }
    return aliases.get(text, text or "unknown")


def _infer_family(symbol: str, asset_families: Mapping[str, str] | None) -> str:
    if asset_families and symbol in asset_families:
        return _normalize_family(asset_families[symbol])
    sym = symbol.upper()
    if any(tok in sym for tok in ("BTC", "ETH", "SOL", "USDT", "USDC", "CRYPTO")):
        return "crypto"
    if any(tok in sym for tok in ("USD", "EUR", "JPY", "GBP", "CHF", "FX")) and len(sym) <= 10:
        # crude FX heuristic — caller should pass asset_families for honesty
        if sym.endswith("USD") or sym.startswith("USD") or "FX" in sym:
            return "forex"
    if any(tok in sym for tok in ("BOND", "TNX", "UST", "YIELD", "10Y", "2Y", "30Y")):
        return "fixed_income"
    return "equity"


def stress_catalog() -> dict[str, ScenarioSpec]:
    """Built-in stress scenario templates (empty shocks until bound to symbols)."""
    out: dict[str, ScenarioSpec] = {}
    for sid in STRESS_SCENARIO_IDS:
        meta = _CATALOG_META[sid]
        out[sid] = ScenarioSpec(
            scenario_id=sid,
            name=meta["name"],
            shocks={},
            description=meta["description"],
            status="ASSUMED",
            kind=meta["kind"],
            params=dict(_ASSUMED_PARAMS[sid]),
            seed=None,
        )
    return out


def list_stress_scenario_ids() -> tuple[str, ...]:
    return STRESS_SCENARIO_IDS


def required_stress_scenarios_present(catalog: Mapping[str, Any] | None = None) -> bool:
    """True when the Wave 6 required set exists (rate_move or fx_move counts)."""
    ids = set((catalog or stress_catalog()).keys())
    if not REQUIRED_STRESS_SCENARIO_IDS.issubset(ids):
        return False
    return bool(ids & _RATE_OR_FX_IDS)


def get_stress_scenario(scenario_id: str) -> ScenarioSpec | None:
    return stress_catalog().get(str(scenario_id))


def bind_stress_scenario(
    scenario_id: str,
    *,
    symbols: Sequence[str],
    asset_families: Mapping[str, str] | None = None,
    seed: int = 0,
) -> ScenarioSpec:
    """Bind a catalog scenario to symbols with deterministic ASSUMED shocks.

    Same ``scenario_id`` + ``symbols`` + ``asset_families`` + ``seed`` → identical shocks.
    Does not attach occurrence probabilities (stress ≠ forecast).
    """
    sid = str(scenario_id).strip()
    template = get_stress_scenario(sid)
    if template is None:
        return ScenarioSpec(
            scenario_id=sid or "unknown",
            name="Unknown stress scenario",
            shocks={},
            description="Unknown scenario_id — UNMEASURED",
            status="UNMEASURED",
            kind="price_return",
            params={},
            seed=int(seed),
        )

    syms = [str(s) for s in symbols if str(s).strip()]
    if not syms:
        return ScenarioSpec(
            scenario_id=sid,
            name=template.name,
            shocks={},
            description=template.description + " (no symbols — UNMEASURED)",
            status="UNMEASURED",
            kind=template.kind,
            params=dict(template.params),
            seed=int(seed),
        )

    params = dict(template.params)
    shocks: dict[str, float] = {}
    families = {s: _infer_family(s, asset_families) for s in syms}

    if sid == "equity_crash":
        mag = float(params["equity_return"])
        for s in syms:
            if families[s] == "equity":
                shocks[s] = mag
            else:
                shocks[s] = 0.0

    elif sid == "volatility_shock":
        base = float(params["base_move"]) * float(params["vol_mult"])
        for s in syms:
            # Tiny deterministic jitter from seed so seed affects output without claiming probs.
            jitter = (_stable_unit_float(seed, sid, s) - 0.5) * 0.002
            shocks[s] = base + jitter

    elif sid == "rate_move":
        mag = float(params["rate_sensitive_return"])
        for s in syms:
            shocks[s] = mag if families[s] in {"fixed_income", "equity"} else 0.0

    elif sid == "fx_move":
        mag = float(params["fx_return"])
        for s in syms:
            shocks[s] = mag if families[s] == "forex" else 0.0

    elif sid == "crypto_gap":
        mag = float(params["gap_return"])
        for s in syms:
            shocks[s] = mag if families[s] == "crypto" else 0.0

    elif sid == "spread_widening":
        # Adverse mark ≈ half of widened spread fraction.
        adverse = -0.5 * float(params["spread_widen_frac"])
        for s in syms:
            shocks[s] = adverse

    elif sid == "liquidity_reduction":
        haircut = -abs(float(params["liquidity_haircut"]))
        for s in syms:
            shocks[s] = haircut

    elif sid == "correlated_selloff":
        base = float(params["risk_asset_return"])
        jitter_bps = float(params.get("seed_jitter_bps", 25.0))
        for s in syms:
            if families[s] in {"equity", "crypto", "forex"}:
                j = (_stable_unit_float(seed, sid, s) - 0.5) * 2.0 * (jitter_bps / 10_000.0)
                shocks[s] = base + j
            else:
                shocks[s] = 0.0

    else:
        return ScenarioSpec(
            scenario_id=sid,
            name=template.name,
            shocks={},
            description="Unhandled catalog id — UNMEASURED",
            status="UNMEASURED",
            kind=template.kind,
            params=params,
            seed=int(seed),
        )

    return ScenarioSpec(
        scenario_id=sid,
        name=template.name,
        shocks=shocks,
        description=template.description,
        status="ASSUMED",
        kind=template.kind,
        params=params,
        seed=int(seed),
    )


def run_stress_scenario(
    *,
    scenario_id: str,
    positions: Mapping[str, Mapping[str, Any]] | None,
    marks: Mapping[str, float] | None,
    cash: float | None,
    asset_families: Mapping[str, str] | None = None,
    seed: int = 0,
    symbols: Sequence[str] | None = None,
) -> ScenarioResult:
    """Run a catalog stress scenario with honesty for missing inputs.

    Missing / empty positions, marks, or cash → UNMEASURED (no fabricated PASS PnL).
    """
    notes: list[str] = []
    if positions is None:
        notes.append("positions_missing")
    if marks is None:
        notes.append("marks_missing")
    if cash is None:
        notes.append("cash_missing")

    if notes:
        return ScenarioResult(
            scenario_id=str(scenario_id),
            base_equity=0.0,
            shocked_equity=0.0,
            pnl=0.0,
            pnl_pct=0.0,
            position_impacts=[],
            measurement="UNMEASURED",
            notes=notes + ["stress_scenario_is_not_a_forecast"],
        )

    pos = dict(positions or {})
    mk = {str(k): float(v) for k, v in dict(marks or {}).items()}
    if not pos:
        return ScenarioResult(
            scenario_id=str(scenario_id),
            base_equity=float(cash or 0.0),
            shocked_equity=float(cash or 0.0),
            pnl=0.0,
            pnl_pct=0.0,
            position_impacts=[],
            measurement="UNMEASURED",
            notes=["positions_empty", "stress_scenario_is_not_a_forecast"],
        )

    # Held symbols without marks → UNMEASURED (do not invent prices).
    held = [s for s, p in pos.items() if float(p.get("qty") or 0) != 0]
    missing_marks = [s for s in held if s not in mk and _avg_entry_missing(pos[s])]
    if missing_marks:
        return ScenarioResult(
            scenario_id=str(scenario_id),
            base_equity=0.0,
            shocked_equity=0.0,
            pnl=0.0,
            pnl_pct=0.0,
            position_impacts=[],
            measurement="UNMEASURED",
            notes=[f"marks_missing:{','.join(sorted(missing_marks))}", "stress_scenario_is_not_a_forecast"],
        )

    syms = list(symbols) if symbols is not None else sorted(set(held) | set(mk))
    spec = bind_stress_scenario(
        scenario_id,
        symbols=syms,
        asset_families=asset_families,
        seed=seed,
    )
    if spec.status == "UNMEASURED":
        return ScenarioResult(
            scenario_id=spec.scenario_id,
            base_equity=0.0,
            shocked_equity=0.0,
            pnl=0.0,
            pnl_pct=0.0,
            position_impacts=[],
            measurement="UNMEASURED",
            notes=["scenario_unmeasured", "stress_scenario_is_not_a_forecast"],
        )

    result = apply_scenario(positions=pos, marks=mk, cash=float(cash), scenario=spec)
    result.notes = ["stress_scenario_is_not_a_forecast", "no_fabricated_probabilities"]
    return result


def _avg_entry_missing(pos: Mapping[str, Any]) -> bool:
    """True when position has no usable avg_entry fallback for mark."""
    try:
        avg = float(pos.get("avg_entry") or 0)
    except (TypeError, ValueError):
        return True
    return avg <= 0
