"""W49 — Multi-asset capability matrix truth pack.

Wraps market_sim.capabilities / instruments — truthful states only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .status import MeasurementState, DEFAULT_TRUTH


@dataclass
class AssetClassCapability:
    family: str
    historical_sim: str
    live_paper: str
    live_trading: str
    data_providers: list[str] = field(default_factory=list)
    notes: str = ""
    owner: str = "market_sim.capabilities"

    def public_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "HISTORICAL_SIM_AVAILABLE": self.historical_sim,
            "LIVE_PAPER_AVAILABLE": self.live_paper,
            "LIVE_TRADING_AVAILABLE": self.live_trading,
            "dataProviders": list(self.data_providers),
            "notes": self.notes,
            "owner": self.owner,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "enum_existence_is_not_market_support": True,
            },
        }


@dataclass
class MultiAssetTruthPack:
    feature_enabled: bool
    families: list[AssetClassCapability]
    source: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "featureEnabled": self.feature_enabled,
            "families": [f.public_dict() for f in self.families],
            "source": self.source,
            "liveTradingDefault": MeasurementState.BLOCKED.value,
            "truth": {
                **DEFAULT_TRUTH.public_dict(),
                "capability_from_adapters": True,
                "not_from_ui_presence": True,
            },
        }


def build_multi_asset_truth_pack(
    *,
    feature_enabled: bool = True,
    capabilities_builder: Callable[..., dict[str, Any]] | None = None,
) -> MultiAssetTruthPack:
    """Delegate to market_sim.capabilities.build_market_capabilities when available."""
    builder = capabilities_builder
    source = "market_sim.capabilities"
    if builder is None:
        try:
            from ..capabilities import build_market_capabilities

            builder = build_market_capabilities
        except Exception:  # noqa: BLE001
            builder = None
            source = "fallback_static"

    if builder is not None:
        raw = builder(feature_enabled=feature_enabled)
        families = [
            AssetClassCapability(
                family=str(m.get("family")),
                historical_sim=str(m.get("HISTORICAL_SIM_AVAILABLE")),
                live_paper=str(m.get("LIVE_PAPER_AVAILABLE")),
                live_trading=str(m.get("LIVE_TRADING_AVAILABLE") or MeasurementState.BLOCKED.value),
                data_providers=list(m.get("data_providers") or []),
                notes=str(m.get("notes") or ""),
            )
            for m in raw.get("markets") or []
        ]
        return MultiAssetTruthPack(
            feature_enabled=bool(raw.get("feature_enabled", feature_enabled)),
            families=families,
            source=source,
        )

    # Static fallback aligned with instruments.SUPPORTED_SIM_FAMILIES honesty.
    families = [
        AssetClassCapability("equity", "AVAILABLE", "AVAILABLE", "BLOCKED"),
        AssetClassCapability("crypto_spot", "AVAILABLE", "AVAILABLE", "BLOCKED"),
        AssetClassCapability("futures", "AVAILABLE", "AVAILABLE", "BLOCKED"),
        AssetClassCapability("forex", "AVAILABLE", "AVAILABLE", "BLOCKED"),
        AssetClassCapability(
            "options",
            MeasurementState.NOT_IMPLEMENTED.value,
            MeasurementState.NOT_IMPLEMENTED.value,
            MeasurementState.BLOCKED.value,
            notes="identity only",
        ),
        AssetClassCapability(
            "fixed_income",
            MeasurementState.NOT_IMPLEMENTED.value,
            MeasurementState.NOT_IMPLEMENTED.value,
            MeasurementState.BLOCKED.value,
            notes="identity only",
        ),
    ]
    return MultiAssetTruthPack(feature_enabled=feature_enabled, families=families, source=source)


def family_status(pack: MultiAssetTruthPack, family: str) -> dict[str, Any]:
    for item in pack.families:
        if item.family == family:
            return item.public_dict()
    return {
        "family": family,
        "HISTORICAL_SIM_AVAILABLE": MeasurementState.UNAVAILABLE.value,
        "LIVE_PAPER_AVAILABLE": MeasurementState.UNAVAILABLE.value,
        "LIVE_TRADING_AVAILABLE": MeasurementState.BLOCKED.value,
        "truth": {"unknown_family": True},
    }
