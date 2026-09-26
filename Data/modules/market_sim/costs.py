"""Execution cost model pack with MEASURED / ASSUMED / UNMEASURED provenance (W13C)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import MetricStatus


@dataclass(frozen=True)
class CostComponent:
    name: str
    value: float | None
    unit: str  # bps | currency | seconds | fraction
    status: MetricStatus
    provenance: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "status": self.status.value,
            "provenance": self.provenance,
            "truth": {
                "unmeasured_is_not_zero_cost": self.status == MetricStatus.UNMEASURED,
                "assumed_is_not_measured": self.status == MetricStatus.ASSUMED,
            },
        }


# Named model aliases required by the Trading Lab cost pack contract.
SpreadModel = CostComponent
ImpactModel = CostComponent
LatencyModel = CostComponent
FeeSchedule = CostComponent
FundingModel = CostComponent
BorrowModel = CostComponent


@dataclass
class CostModelPack:
    """Spread / Impact / Latency / Fee / Funding / Borrow — deterministic with seed/config."""

    fee: CostComponent
    spread: CostComponent
    impact: CostComponent
    latency: CostComponent
    funding: CostComponent
    borrow: CostComponent
    seed: int | None = None
    version: str = "cost_pack-1"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_fee_slippage_bps(
        cls,
        *,
        fee_bps: float = 0.0,
        slippage_bps: float = 0.0,
        seed: int | None = None,
    ) -> CostModelPack:
        """Compatibility constructor — fee MEASURED/ASSUMED from config; spread ASSUMED from slippage."""
        fee_status = MetricStatus.ASSUMED if fee_bps else MetricStatus.UNMEASURED
        slip_status = MetricStatus.ASSUMED if slippage_bps else MetricStatus.UNMEASURED
        unmeasured = CostComponent("unset", None, "bps", MetricStatus.UNMEASURED, "not_modelled")
        return cls(
            fee=CostComponent("fee", float(fee_bps), "bps", fee_status, "config.fee_bps"),
            spread=CostComponent(
                "spread", float(slippage_bps), "bps", slip_status, "config.slippage_bps_as_spread_proxy"
            ),
            impact=CostComponent("impact", None, "bps", MetricStatus.UNMEASURED, "no_L2_data"),
            latency=CostComponent("latency", None, "seconds", MetricStatus.UNMEASURED, "not_modelled"),
            funding=CostComponent("funding", None, "bps", MetricStatus.UNMEASURED, "not_modelled"),
            borrow=CostComponent("borrow", None, "bps", MetricStatus.UNMEASURED, "not_modelled"),
            seed=seed,
            metadata={"compatibility": "fee_slippage_bps"},
        )

    def effective_fee_bps(self) -> float:
        return float(self.fee.value or 0.0) if self.fee.status != MetricStatus.UNMEASURED else 0.0

    def effective_spread_bps(self) -> float:
        return float(self.spread.value or 0.0) if self.spread.status != MetricStatus.UNMEASURED else 0.0

    def total_assumed_friction_bps(self) -> float:
        """Sum of fee+spread+impact when not UNMEASURED — never invents UNMEASURED as zero silently in truth."""
        total = 0.0
        for comp in (self.fee, self.spread, self.impact):
            if comp.status != MetricStatus.UNMEASURED and comp.value is not None:
                total += float(comp.value)
        return total

    def public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "seed": self.seed,
            "fee": self.fee.public_dict(),
            "spread": self.spread.public_dict(),
            "impact": self.impact.public_dict(),
            "latency": self.latency.public_dict(),
            "funding": self.funding.public_dict(),
            "borrow": self.borrow.public_dict(),
            "effective_fee_bps": self.effective_fee_bps(),
            "effective_spread_bps": self.effective_spread_bps(),
            "total_assumed_friction_bps": self.total_assumed_friction_bps(),
            "metadata": dict(self.metadata),
            "truth": {
                "no_fake_microstructure_without_data": True,
                "ohlcv_assumptions_remain_visible": True,
                "seed_makes_deterministic": self.seed is not None,
            },
        }
