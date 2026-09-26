"""W48 — Leverage / margin / collateral with ASSUMED model labels.

Extends short_margin + PortfolioBook margin fields — no parallel margin engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .status import MeasurementState, StatusedValue, DEFAULT_TRUTH


@dataclass(frozen=True)
class CollateralHaircut:
    instrument_id: str
    haircut_pct: float  # e.g. 15.0 means 15% haircut
    model: str = "ASSUMED_flat_haircut"

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "haircutPct": self.haircut_pct,
            "model": self.model,
            "truth": {"haircut_model_ASSUMED": self.model.startswith("ASSUMED")},
        }


@dataclass
class MarginPosition:
    instrument_id: str
    mv: float
    side: str = "LONG"
    initial_margin_pct: float = 50.0
    maintenance_margin_pct: float = 30.0

    def public_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "mv": self.mv,
            "side": self.side,
            "initialMarginPct": self.initial_margin_pct,
            "maintenanceMarginPct": self.maintenance_margin_pct,
        }


@dataclass
class LeverageMarginReport:
    nav: float
    gross_exposure: float
    leverage: StatusedValue
    initial_margin_required: StatusedValue
    maintenance_margin_required: StatusedValue
    collateral_value: StatusedValue
    excess_liquidity: StatusedValue
    model_label: str
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "nav": self.nav,
            "grossExposure": self.gross_exposure,
            "leverage": self.leverage.public_dict(),
            "initialMarginRequired": self.initial_margin_required.public_dict(),
            "maintenanceMarginRequired": self.maintenance_margin_required.public_dict(),
            "collateralValue": self.collateral_value.public_dict(),
            "excessLiquidity": self.excess_liquidity.public_dict(),
            "modelLabel": self.model_label,
            "notes": list(self.notes),
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "extends_short_margin": True,
                "model_is_ASSUMED_not_broker_official": True,
            },
        }


def collateral_after_haircut(
    positions: Sequence[Mapping[str, Any]],
    haircuts: Sequence[CollateralHaircut | Mapping[str, Any]],
) -> StatusedValue:
    cut_map: dict[str, float] = {}
    for raw in haircuts:
        if isinstance(raw, CollateralHaircut):
            cut_map[raw.instrument_id] = raw.haircut_pct
        else:
            cut_map[str(raw.get("instrument_id") or raw.get("instrumentId"))] = float(
                raw.get("haircut_pct") or raw.get("haircutPct") or 0
            )
    if not positions:
        return StatusedValue(0.0, MeasurementState.EMPTY, methodology="ASSUMED_flat_haircut")
    total = 0.0
    missing = False
    for pos in positions:
        inst = str(pos.get("instrument_id") or pos.get("instrumentId") or "")
        mv = abs(float(pos.get("mv") or 0))
        if inst not in cut_map:
            missing = True
            # Fail closed: treat unknown haircut as 100% (no collateral credit).
            continue
        total += mv * (1.0 - cut_map[inst] / 100.0)
    state = MeasurementState.ASSUMED if not missing else MeasurementState.DEGRADED
    notes = ["unknown_instrument_haircut_treated_as_zero_credit"] if missing else []
    return StatusedValue(
        total,
        state,
        unit="currency",
        methodology="ASSUMED_flat_haircut",
        notes=notes,
    )


def compute_leverage_margin(
    positions: Sequence[MarginPosition | Mapping[str, Any]],
    *,
    nav: float,
    cash: float = 0.0,
    haircuts: Sequence[CollateralHaircut | Mapping[str, Any]] | None = None,
    model_label: str = "ASSUMED_reg_t_style",
) -> LeverageMarginReport:
    normalized: list[MarginPosition] = []
    for raw in positions:
        if isinstance(raw, MarginPosition):
            normalized.append(raw)
        else:
            normalized.append(
                MarginPosition(
                    instrument_id=str(raw.get("instrument_id") or raw.get("instrumentId") or ""),
                    mv=float(raw.get("mv") or 0),
                    side=str(raw.get("side") or "LONG").upper(),
                    initial_margin_pct=float(
                        raw.get("initial_margin_pct") or raw.get("initialMarginPct") or 50.0
                    ),
                    maintenance_margin_pct=float(
                        raw.get("maintenance_margin_pct")
                        or raw.get("maintenanceMarginPct")
                        or 30.0
                    ),
                )
            )

    notes: list[str] = ["model_ASSUMED", "not_broker_official_margin"]
    gross = sum(abs(p.mv) for p in normalized)

    if nav <= 0:
        leverage = StatusedValue(
            None, MeasurementState.INFEASIBLE, methodology=model_label, notes=["nav_non_positive"]
        )
    else:
        leverage = StatusedValue(
            gross / nav, MeasurementState.ASSUMED, unit="x", methodology=model_label
        )

    initial = sum(abs(p.mv) * p.initial_margin_pct / 100.0 for p in normalized)
    maintenance = sum(abs(p.mv) * p.maintenance_margin_pct / 100.0 for p in normalized)

    # Optionally import short_margin policy labels for honesty.
    try:
        from ..short_margin import ShortMarginPolicy

        _ = ShortMarginPolicy  # owner presence check
        notes.append("short_margin_owner_present")
    except Exception:  # noqa: BLE001
        notes.append("short_margin_owner_UNAVAILABLE")

    pos_maps = [p.public_dict() for p in normalized]
    if haircuts:
        collat = collateral_after_haircut(pos_maps, haircuts)
    else:
        collat = StatusedValue(
            cash,
            MeasurementState.ASSUMED,
            unit="currency",
            methodology="cash_only_collateral_ASSUMED",
            notes=["no_haircuts_supplied_cash_only"],
        )
        notes.append("collateral_cash_only_ASSUMED")

    collat_val = float(collat.value or 0.0) + (cash if haircuts else 0.0)
    # Avoid double-counting cash when haircuts path already excludes cash.
    if haircuts:
        collat_val = float(collat.value or 0.0) + float(cash)
        collat = StatusedValue(
            collat_val,
            MeasurementState.ASSUMED,
            unit="currency",
            methodology="ASSUMED_flat_haircut_plus_cash",
            notes=list(collat.notes),
        )

    excess = StatusedValue(
        float(collat.value or 0.0) - maintenance,
        MeasurementState.ASSUMED,
        unit="currency",
        methodology=model_label,
    )

    return LeverageMarginReport(
        nav=nav,
        gross_exposure=gross,
        leverage=leverage,
        initial_margin_required=StatusedValue(
            initial, MeasurementState.ASSUMED, unit="currency", methodology=model_label
        ),
        maintenance_margin_required=StatusedValue(
            maintenance, MeasurementState.ASSUMED, unit="currency", methodology=model_label
        ),
        collateral_value=collat,
        excess_liquidity=excess,
        model_label=model_label,
        notes=notes,
    )
